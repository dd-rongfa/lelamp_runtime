r"""
火山豆包大模型流式语音识别 —— 二进制 WS 协议。
移植自 livekit-plugins-volcengine 1.3.0 的 bigmodel_stt.py（仅协议部分，去掉对旧插件的依赖）。

帧结构：
  byte0: protocol_version(4) | header_size(4)
  byte1: message_type(4)     | message_type_specific_flags(4)
  byte2: serialization(4)    | compression(4)
  byte3: reserved
  [sequence(4, 可选)] [payload_size(4)] [payload(gzip+json 或 gzip+pcm)]
"""
from __future__ import annotations

import gzip
import json

PROTOCOL_VERSION = 0b0001

# message_type
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# message_type_specific_flags
NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_WITH_SEQUENCE = 0b0011

# serialization / compression
JSON = 0b0001
GZIP = 0b0001


def _header(message_type: int, flags: int) -> bytearray:
    h = bytearray()
    h.append((PROTOCOL_VERSION << 4) | 1)        # version | header_size=1
    h.append((message_type << 4) | flags)
    h.append((JSON << 4) | GZIP)                  # json + gzip
    h.append(0x00)                                # reserved
    return h


def _before_payload(sequence: int) -> bytearray:
    return bytearray(sequence.to_bytes(4, "big", signed=True))


def build_config_request(*, sample_rate: int, num_channels: int, bits: int,
                         enable_itn: bool, enable_punc: bool, enable_ddc: bool,
                         vad_segment_duration: int, end_window_size: int,
                         force_to_speech_time: int, uid: str) -> bytearray:
    """首包：完整客户端请求(识别参数配置)。"""
    payload = {
        "user": {"uid": uid},
        "audio": {"format": "pcm", "rate": sample_rate, "bits": bits,
                  "channels": num_channels, "codec": "raw"},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": enable_itn, "enable_punc": enable_punc, "enable_ddc": enable_ddc,
            "show_utterance": True, "result_type": "single",
            "vad_segment_duration": vad_segment_duration,
            "end_window_size": end_window_size,
            "force_to_speech_time": force_to_speech_time,
        },
    }
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    req = _header(FULL_CLIENT_REQUEST, POS_SEQUENCE)
    req.extend(_before_payload(1))
    req.extend(len(body).to_bytes(4, "big"))
    req.extend(body)
    return req


def build_audio_request(chunk: bytes, *, seq: int, last: bool) -> bytearray:
    """音频包：gzip 压缩的 PCM。last=True 时用负序号标记结束。"""
    body = gzip.compress(chunk)
    flags = NEG_WITH_SEQUENCE if last else POS_SEQUENCE
    req = _header(AUDIO_ONLY_REQUEST, flags)
    req.extend(_before_payload(seq))
    req.extend(len(body).to_bytes(4, "big"))
    req.extend(body)
    return req


def parse_response(res: bytes) -> dict:
    """解析服务器帧，返回 {payload_msg, code?, is_last_package, ...}。"""
    header_size = res[0] & 0x0F
    message_type = res[1] >> 4
    flags = res[1] & 0x0F
    serialization = res[2] >> 4
    compression = res[2] & 0x0F
    payload = res[header_size * 4:]
    result: dict = {"is_last_package": False, "message_type": message_type}

    if flags & 0x01:
        result["payload_sequence"] = int.from_bytes(payload[:4], "big", signed=True)
        payload = payload[4:]
    if flags & 0x02:
        result["is_last_package"] = True

    payload_msg = None
    if message_type == FULL_SERVER_RESPONSE:
        size = int.from_bytes(payload[:4], "big", signed=True)
        payload_msg = payload[4:]
        result["payload_size"] = size
    elif message_type == SERVER_ACK:
        result["seq"] = int.from_bytes(payload[:4], "big", signed=True)
        if len(payload) >= 8:
            payload_msg = payload[8:]
    elif message_type == SERVER_ERROR_RESPONSE:
        result["code"] = int.from_bytes(payload[:4], "big", signed=False)
        payload_msg = payload[8:]

    if payload_msg is not None:
        if compression == GZIP and payload_msg:
            payload_msg = gzip.decompress(payload_msg)
        if serialization == JSON:
            payload_msg = json.loads(payload_msg.decode("utf-8"))
        else:
            payload_msg = payload_msg.decode("utf-8", "ignore")
        result["payload_msg"] = payload_msg
    return result
