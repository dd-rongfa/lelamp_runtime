r"""
火山豆包 STT —— v3「大模型流式 WS + 单 X-Api-Key」，封装为 LiveKit stt.STT。
对应 livekit-agents 1.5.x。协议见 _protocol.py（自包含，不依赖旧插件）。
"""
from __future__ import annotations

import asyncio

import aiohttp
from livekit import rtc
from livekit.agents import APIConnectOptions, APIStatusError, stt, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr

from . import _protocol as proto

WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
RESOURCE_2_0 = "volc.seedasr.sauc.duration"  # 豆包流式识别 2.0（实测此 key 对应）
RESOURCE_1_0 = "volc.bigasr.sauc.duration"   # 1.0


class STT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str,
        resource_id: str = RESOURCE_2_0,
        sample_rate: int = 16000,
        language: str = "zh-CN",
        enable_itn: bool = False,
        enable_punc: bool = True,
        enable_ddc: bool = False,
        vad_segment_duration: int = 3000,
        end_window_size: int = 500,
        force_to_speech_time: int = 1000,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=True))
        self._api_key = api_key
        self._resource_id = resource_id
        self._sample_rate = sample_rate
        self._language = language
        self._cfg = dict(
            enable_itn=enable_itn, enable_punc=enable_punc, enable_ddc=enable_ddc,
            vad_segment_duration=vad_segment_duration, end_window_size=end_window_size,
            force_to_speech_time=force_to_speech_time,
        )
        self._session = http_session

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = utils.http_context.http_session()
        return self._session

    async def _recognize_impl(self, buffer, *, language=NOT_GIVEN, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        raise NotImplementedError("volc_v3 STT 仅支持流式 stream()")

    def stream(self, *, language: NotGivenOr[str] = NOT_GIVEN,
               conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> "_RecognizeStream":
        return _RecognizeStream(stt=self, conn_options=conn_options)


class _RecognizeStream(stt.RecognizeStream):
    def __init__(self, *, stt: STT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=stt._sample_rate)
        self._st = stt
        self._request_id = utils.shortuuid()
        self._speaking = False
        self._input_ended = False  # 是否已收到 FlushSentinel（正常收尾），用于区分意外断开

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        headers = {
            "X-Api-Resource-Id": self._st._resource_id,
            "X-Api-Key": self._st._api_key,
            "X-Api-Request-Id": self._request_id,
        }
        return await asyncio.wait_for(
            self._st._ensure_session().ws_connect(WS_URL, headers=headers, max_msg_size=1_000_000_000),
            self._conn_options.timeout,
        )

    async def _run(self) -> None:
        sr = self._st._sample_rate

        async def send_task(ws: aiohttp.ClientWebSocketResponse):
            await ws.send_bytes(proto.build_config_request(
                sample_rate=sr, num_channels=1, bits=16, uid=self._request_id, **self._st._cfg))
            bstream = utils.audio.AudioByteStream(
                sample_rate=sr, num_channels=1, samples_per_channel=sr // 10)  # 100ms
            seq = 1
            ended = False
            async for data in self._input_ch:
                frames = []
                if isinstance(data, rtc.AudioFrame):
                    frames = bstream.write(data.data.tobytes())
                elif isinstance(data, self._FlushSentinel):
                    frames = bstream.flush()
                    ended = True
                    self._input_ended = True
                for fr in frames:
                    seq += 1
                    await ws.send_bytes(proto.build_audio_request(
                        fr.data.tobytes(), seq=(-seq if ended else seq), last=ended))

        async def recv_task(ws: aiohttp.ClientWebSocketResponse):
            while True:
                msg = await ws.receive()
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
                    # 输入已正常结束 → 正常收尾；否则视为意外断开，抛可重试错误让基类自动重连
                    if self._input_ended:
                        return
                    raise APIStatusError(message="volc STT WS 意外断开", retryable=True)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if self._process(msg.data):
                        return  # is_last_package

        ws = await self._connect()
        try:
            tasks = [asyncio.create_task(send_task(ws)), asyncio.create_task(recv_task(ws))]
            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)
        finally:
            await ws.close()

    def _process(self, data: bytes) -> bool:
        """处理一帧；返回 True 表示最后一包。"""
        r = proto.parse_response(data)
        if r.get("message_type") == proto.SERVER_ERROR_RESPONSE:
            raise APIStatusError(message=f"volc STT error code={r.get('code')} msg={r.get('payload_msg')}")
        msg = r.get("payload_msg")
        if isinstance(msg, dict):
            result = msg.get("result")
            if result:
                self._emit(result)
        return r.get("is_last_package", False)

    def _emit(self, result: dict) -> None:
        text = result.get("text", "")
        utterances = result.get("utterances", [])
        if not text or not utterances:
            return
        u0 = utterances[0]
        definite = u0.get("definite", False)
        data = [stt.SpeechData(
            language=self._st._language, text=text,
            start_time=u0.get("start_time", 0.0) or 0.0,
            end_time=u0.get("end_time", 0.0) or 0.0,
            confidence=result.get("confidence", 0.0) or 0.0,
        )]
        if not self._speaking:
            self._speaking = True
            self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH))

        if definite:
            self._event_ch.send_nowait(stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT, request_id=self._request_id, alternatives=data))
            self._event_ch.send_nowait(stt.SpeechEvent(
                type=stt.SpeechEventType.END_OF_SPEECH, request_id=self._request_id))
            self._speaking = False
        else:
            self._event_ch.send_nowait(stt.SpeechEvent(
                type=stt.SpeechEventType.INTERIM_TRANSCRIPT, request_id=self._request_id, alternatives=data))
