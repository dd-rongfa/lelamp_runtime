r"""
volc_v3 —— 火山豆包语音「新版 v3 单 X-Api-Key」自包含适配器（STT + TTS）。

为何自写：官方 livekit-plugins-volcengine 1.3.0 走旧版双参鉴权，且锁死 livekit-agents==1.2.9，
无法用新版控制台的单 X-Api-Key，也挡住框架升级。本包对应 livekit-agents 1.5.x，零旧插件依赖。

用法：
    from volc_v3 import STT, TTS
    stt = STT(api_key=KEY)                      # 默认 seedasr 2.0
    tts = TTS(api_key=KEY, speaker="zh_female_vv_uranus_bigtts")
"""
from .stt import STT, RESOURCE_1_0, RESOURCE_2_0
from .tts import TTS, resource_for_speaker

__all__ = ["STT", "TTS", "resource_for_speaker", "RESOURCE_1_0", "RESOURCE_2_0"]
