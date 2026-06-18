r"""
火山豆包 TTS —— v3「HTTP 单向流式 + 单 X-Api-Key」，封装为 LiveKit tts.TTS。
对应 livekit-agents 1.5.x。
"""
from __future__ import annotations

import base64
import json

import aiohttp
from livekit.agents import tts, utils, APIConnectOptions
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

V3_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"  # Vivi 2.0
SAMPLE_RATE = 24000


def resource_for_speaker(speaker: str) -> str:
    """按音色"星球后缀"选 X-Api-Resource-Id，错配会报 55000000。"""
    if speaker.startswith("S_"):
        return "seed-icl-2.0"
    if "_uranus_" in speaker or speaker.startswith("saturn_"):
        return "seed-tts-2.0"
    return "seed-tts-1.0"


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        speaker: str = DEFAULT_SPEAKER,
        sample_rate: int = SAMPLE_RATE,
        resource_id: str | None = None,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._api_key = api_key
        self._speaker = speaker
        self._sample_rate = sample_rate
        self._resource_id = resource_id or resource_for_speaker(speaker)
        self._session = http_session

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = utils.http_context.http_session()
        return self._session

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS):
        return _ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _ChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._v3: TTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        headers = {
            "X-Api-Key": self._v3._api_key,
            "X-Api-Resource-Id": self._v3._resource_id,
            "Content-Type": "application/json",
        }
        body = {
            "user": {"uid": "lelamp"},
            "req_params": {
                "text": self._input_text,
                "speaker": self._v3._speaker,
                "audio_params": {"format": "pcm", "sample_rate": self._v3._sample_rate},
            },
        }
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._v3._sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            stream=False,
        )
        session = self._v3._ensure_session()
        async with session.post(
            V3_URL, headers=headers, json=body,
            timeout=aiohttp.ClientTimeout(total=self._conn_options.timeout),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                code = obj.get("code")
                if code not in (0, 20000000):
                    raise RuntimeError(f"火山 TTS code={code} msg={obj.get('message')}")
                data = obj.get("data")
                if data:
                    output_emitter.push(base64.b64decode(data))
                if code == 20000000:
                    break
        output_emitter.flush()
