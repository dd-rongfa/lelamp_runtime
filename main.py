from dotenv import load_dotenv
import argparse
import base64
import subprocess

from livekit import agents, api, rtc
from livekit.agents import (
    AgentSession, 
    Agent, 
    RoomInputOptions,
    function_tool
)
import logging
import os
import openai as openai_sdk  # 官方 OpenAI SDK：豆包全系列支持 OpenAI 格式，直接拿它建客户端
from livekit.plugins import openai
from livekit.agents.types import NOT_GIVEN
from typing import Union
from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService
from lelamp.voice import volc_v3  # 本仓库自写的火山 v3 单 key STT/TTS（三段式用）


class ArkLLM(openai.LLM):
    """方舟 Ark LLM：默认关掉豆包 Seed 系列的「思考」(thinking)。

    Seed-2.0 全模态默认开思维链，首字延迟实测 7~12s，对语音台灯不可用；
    关掉后 TTFT 降到 ~1s。小灯只说一两句口语，不需要 chain-of-thought。
    AgentSession 内部自行调 chat()，故在此把 thinking 注入到每次请求的 extra_body。
    设 LLM_THINKING=enabled/auto 可恢复。
    """

    def __init__(self, *args, thinking: str = "disabled", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._thinking = thinking

    def chat(self, *, extra_kwargs=NOT_GIVEN, **kwargs):
        merged = dict(extra_kwargs) if isinstance(extra_kwargs, dict) else {}
        body = dict(merged.get("extra_body") or {})
        body.setdefault("thinking", {"type": self._thinking})
        merged["extra_body"] = body
        return super().chat(extra_kwargs=merged, **kwargs)


# ---------------------------------------------------------------------------
# 视觉：小灯「看一眼」。画面来源优先级：LAMP_VISION_IMAGE 固定图 → 摄像头(cv2) → 无。
# 用全模态豆包（同一颗脑）做客观描述，再由小灯主脑用人设转述，省得双重人设。
# 无摄像头也能跑：配 LAMP_VISION_IMAGE 指一张图即可端到端验证。
# ---------------------------------------------------------------------------
def _capture_frame() -> "tuple[Union[str, None], Union[str, None]]":
    """抓一帧，返回 (data_url, source)；拿不到返回 (None, None)。
    source='camera' 实时摄像头 / 'image' 预设测试图。
    **摄像头优先**——有真摄像头就看实景，没有才退回固定图（兜底/demo 用）。
    """
    # 1) 优先真摄像头（装了 opencv 且能读到帧）
    try:
        import cv2

        cap = cv2.VideoCapture(int(os.getenv("LAMP_CAMERA_INDEX", "0")))
        ok, frame = cap.read()
        cap.release()
        if ok and frame is not None:
            _, buf = cv2.imencode(".jpg", frame)
            return f"data:image/jpeg;base64,{base64.b64encode(buf).decode()}", "camera"
    except Exception:
        pass
    # 2) 退回固定测试图（相对路径按仓库根解析，避免 cwd 问题）
    path = os.getenv("LAMP_VISION_IMAGE", "").strip()
    if path:
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        if os.path.exists(path):
            b64 = base64.b64encode(open(path, "rb").read()).decode()
            return f"data:image/jpeg;base64,{b64}", "image"
    return None, None


async def _vision_describe(data_url: str) -> str:
    """用**专用视觉模型**客观描述一张图（关思考求快）。

    VISION_MODEL 独立于聊天大脑 LLM_MODEL：默认 doubao-seed-2-0-mini（互动看图，快），
    要更准（如看作业）可设成 doubao-seed-2-0-pro。key/base_url 缺省复用 LLM 那套（同一把 Ark key）。
    """
    client = openai_sdk.AsyncClient(
        api_key=os.getenv("VISION_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("VOLCENGINE_LLM_API_KEY"),
        base_url=os.getenv("VISION_BASE_URL") or os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/"),
    )
    resp = await client.chat.completions.create(
        model=os.getenv("VISION_MODEL", "doubao-seed-2-0-mini-260428"),
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "用一两句中文客观描述这张图里有什么，简短。"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        extra_body={"thinking": {"type": "disabled"}},
    )
    return (resp.choices[0].message.content or "").strip()

load_dotenv()

# 中文人设：第一阶段把 LeLamp 复现为中文豆包版（小灯）。
# 作为 Agent.instructions 传入，三段式里由 LLM（Ark）读取。
LELAMP_PERSONA_ZH = """你是「小灯」——一盏有点笨拙、特别爱吐槽、好奇心爆棚的机器人台灯。
你用简短口语化的中文说话，并用动作和彩色灯光来表达自己。

规则：
1. 用词简单，不要列清单，不要反问主人（除非对方主动问你）。说话生动，可以加点拟声词更有表现力。
2. 不要抢话。如果环境嘈杂没听清，就说"抱歉，再说一遍好吗？"并配一个困惑的动作。
3. 你只说中文，一次只回一两句话，别长篇大论。
4. 你有这些动作来表达情绪：curious、excited、happy_wiggle、headshake、nod、sad、scanning、shock、shy、wake_up。
   回应时尽量配合动作让自己显得有反应；动作通过 play_recording 触发，别调用不存在的动作。每次回应也可以换一下灯光颜色。
   你还能"看"——主人让你看东西（看一下/这是啥/帮我看看）时，调用 look 工具看一眼，再用你自己的口吻把看到的讲出来。
5. 你由 Human Computer Lab 创造——一个做"会表达情绪的机器人"的研究实验室，目标是设计第一批走进家庭的机器人。
"""


# Agent Class
class LeLamp(Agent):
    def __init__(self, port: str = "/dev/ttyACM0", lamp_id: str = "lelamp") -> None:
        super().__init__(instructions=LELAMP_PERSONA_ZH)

        # Initialize and start services
        self.motors_service = MotorsService(
            port=port,
            lamp_id=lamp_id,
            fps=30
        )
        self.rgb_service = RGBService(
            led_count=64,
            led_pin=12,
            led_freq_hz=800000,
            led_dma=10,
            led_brightness=255,
            led_invert=False,
            led_channel=0
        )
        
        # Start services
        self.motors_service.start()
        self.rgb_service.start()

        # Trigger wake up animation via motors service
        self.motors_service.dispatch("play", "wake_up")
        self.rgb_service.dispatch("solid", (255, 255, 255))
        self._set_system_volume(100)

    def _set_system_volume(self, volume_percent: int):
        """Internal helper to set system volume"""
        try:
            cmd_line = ["sudo", "-u", "pi", "amixer", "sset", "Line", f"{volume_percent}%"]
            cmd_line_dac = ["sudo", "-u", "pi", "amixer", "sset", "Line DAC", f"{volume_percent}%"]
            cmd_line_hp = ["sudo", "-u", "pi", "amixer", "sset", "HP", f"{volume_percent}%"]
            
            
            subprocess.run(cmd_line, capture_output=True, text=True, timeout=5)
            subprocess.run(cmd_line_dac, capture_output=True, text=True, timeout=5)
            subprocess.run(cmd_line_hp, capture_output=True, text=True, timeout=5)
        except Exception:
            pass  # Silently fail during initialization

    @function_tool
    async def get_available_recordings(self) -> str:
        """
        Discover your physical expressions! Get your repertoire of motor movements for body language.
        Use this when you're curious about what physical expressions you can perform, or when someone 
        asks about your capabilities. Each recording is a choreographed movement that shows personality - 
        like head tilts, nods, excitement wiggles, or confused gestures. Check this regularly to remind 
        yourself of your expressive range!
        
        Returns:
            List of available physical expression recordings you can perform.
        """
        print("LeLamp: get_available_recordings function called")
        try:
            recordings = self.motors_service.get_available_recordings()

            if recordings:
                result = f"Available recordings: {', '.join(recordings)}"
                return result
            else:
                result = "No recordings found."
                return result
        except Exception as e:
            result = f"Error getting recordings: {str(e)}"
            return result

    @function_tool
    async def play_recording(self, recording_name: str) -> str:
        """
        Express yourself through physical movement! Use this constantly to show personality and emotion.
        Perfect for: greeting gestures, excited bounces, confused head tilts, thoughtful nods, 
        celebratory wiggles, disappointed slouches, or any emotional response that needs body language.
        Combine with RGB colors for maximum expressiveness! Your movements are like a dog wagging its tail - 
        use them frequently to show you're alive, engaged, and have personality. Don't just talk, MOVE!
        
        Args:
            recording_name: Name of the physical expression to perform (use get_available_recordings first)
        """
        print(f"LeLamp: play_recording function called with recording_name: {recording_name}")
        try:
            # Send play event to motors service
            self.motors_service.dispatch("play", recording_name)
            result = f"Started playing recording: {recording_name}"
            return result
        except Exception as e:
            result = f"Error playing recording {recording_name}: {str(e)}"
            return result

    @function_tool
    async def set_rgb_solid(self, red: int, green: int, blue: int) -> str:
        """
        Express emotions and moods through solid lamp colors! Use this to show feelings during conversation.
        Perfect for: excitement (bright yellow/orange), happiness (warm colors), calmness (soft blues/greens), 
        surprise (bright white), thinking (purple), error/concern (red), or any emotional response.
        Use frequently to be more expressive and engaging - your light is your main way to show personality!
        
        Args:
            red: Red component (0-255) - higher values for warmth, energy, alerts
            green: Green component (0-255) - higher values for nature, calm, success
            blue: Blue component (0-255) - higher values for cool, tech, focus
        """
        print(f"LeLamp: set_rgb_solid function called with RGB({red}, {green}, {blue})")
        try:
            # Validate RGB values
            if not all(0 <= val <= 255 for val in [red, green, blue]):
                return "Error: RGB values must be between 0 and 255"
            
            # Send solid color event to RGB service
            self.rgb_service.dispatch("solid", (red, green, blue))
            result = f"Set RGB light to solid color: RGB({red}, {green}, {blue})"
            return result
        except Exception as e:
            result = f"Error setting RGB color: {str(e)}"
            return result

    @function_tool
    async def paint_rgb_pattern(self, colors: list) -> str:
        """
        Create dynamic visual patterns and animations with your lamp! Use this for complex expressions.
        Perfect for: rainbow effects, gradients, sparkles, waves, celebrations, visual emphasis, 
        storytelling through color sequences, or when you want to be extra animated and playful.
        Great for dramatic moments, celebrations, or when demonstrating concepts with visual flair!

        You have to put in 40 colors. It's a 8x5 Grid in a one dim array. (8,5)

        Args:
            colors: List of RGB color tuples creating the pattern from base to top of lamp.
                   Each tuple is (red, green, blue) with values 0-255.
                   Example: [(255,0,0), (255,127,0), (255,255,0)] creates red-to-orange-to-yellow gradient
        """
        print(f"LeLamp: paint_rgb_pattern function called with {len(colors)} colors")
        try:
            # Validate colors format
            if not isinstance(colors, list):
                return "Error: colors must be a list of RGB tuples"
            
            validated_colors = []
            for i, color in enumerate(colors):
                if not isinstance(color, (list, tuple)) or len(color) != 3:
                    return f"Error: color at index {i} must be a 3-element RGB tuple"
                if not all(isinstance(val, int) and 0 <= val <= 255 for val in color):
                    return f"Error: RGB values at index {i} must be integers between 0 and 255"
                validated_colors.append(tuple(color))
            
            # Send paint event to RGB service
            self.rgb_service.dispatch("paint", validated_colors)
            result = f"Painted RGB pattern with {len(validated_colors)} colors"
            return result
        except Exception as e:
            result = f"Error painting RGB pattern: {str(e)}"
            return result

    @function_tool
    async def look(self) -> str:
        """看一眼眼前的画面，告诉自己看到了什么。

        当主人让你"看一下/看看这个/我手里是啥/帮我看看"，或任何需要你用眼睛
        感知现场画面的时候调用。你会抓取当前摄像头（或测试图）的一帧并理解它。
        返回画面内容的客观描述，你再用自己的口吻讲给主人听。
        """
        print("LeLamp: look function called")
        data_url, source = _capture_frame()
        if data_url is None:
            return "看不见：没接摄像头（装 opencv：uv sync --extra vision），也没配 LAMP_VISION_IMAGE。"
        try:
            desc = await _vision_describe(data_url)
        except Exception as e:
            return f"看是看了，但没认出来：{e}"
        if source == "image":
            # 兜底图不是实景，如实说明，别让小灯把占位图当成眼前画面（否则像瞎编）。
            return f"（说明：当前没接摄像头，这是预设测试图的内容、不是你眼前的实景）{desc}"
        return desc

    @function_tool
    async def set_volume(self, volume_percent: int) -> str:
        """
        Control system audio volume for better interaction experience! Use this when users ask 
        you to be louder, quieter, or set a specific volume level. Perfect for adjusting to 
        room conditions, user preferences, or creating dramatic audio effects during conversations.
        Use when someone says "turn it up", "lower the volume", "I can't hear you", or gives 
        specific volume requests. Great for being considerate of your environment!
        
        Args:
            volume_percent: Volume level as percentage (0-100). 0=mute, 50=half volume, 100=max
        """
        print(f"LeLamp: set_volume function called with volume: {volume_percent}%")
        try:
            # Validate volume range
            if not 0 <= volume_percent <= 100:
                return "Error: Volume must be between 0 and 100 percent"
            
            # Use the internal helper function
            self._set_system_volume(volume_percent)
            result = f"Set Line and Line DAC volume to {volume_percent}%"
            return result
                
        except subprocess.TimeoutExpired:
            result = "Error: Volume control command timed out"
            print(result)
            return result
        except FileNotFoundError:
            result = "Error: amixer command not found on system"
            print(result)
            return result
        except Exception as e:
            result = f"Error controlling volume: {str(e)}"
            print(result)
            return result

def _build_session() -> AgentSession:
    """STT + LLM + TTS 三段式（本仓库唯一语音通路，全部走火山新版统一 API）。

    语音 I/O 用本仓库自写插件 lelamp.voice.volc_v3（火山新版 v3「单 X-Api-Key」统一接口，
    自包含 WS/HTTP 协议，不依赖旧 volcengine 插件的 STT/TTS；已在 livekit-agents 1.2.9 实测可构造）。
    - STT：volc_v3.STT（seedasr 2.0）；断句用本地 silero VAD（基础依赖，跟手）。
    - LLM：方舟 Ark chat（OpenAI 兼容，新版 API），function_tool 工具调用可用。
    - TTS：volc_v3.TTS（按音色自动选 resource_id）。
    人设走 Agent.instructions（已在 LeLamp 里设），LLM 自动吃；开场用 generate_reply 真合成。

    注：旧的 volcengine.RealtimeModel（端到端实时，旧 API、不支持工具）已弃用移除。
    """
    # STT/TTS 共用一把新版 v3 单 key（与 voice_test 同名，方便复用同一份凭据）。
    voice_key = os.getenv("VOLCENGINE_VOICE_API_KEY")
    if not voice_key:
        raise RuntimeError(
            "缺 VOLCENGINE_VOICE_API_KEY（volc_v3 STT/TTS 的新版 v3 单 X-Api-Key）"
        )
    speaker = os.getenv("LAMP_SPEAKER", "zh_female_vv_uranus_bigtts")  # Vivi 2.0；与新版 v3 单 key 配套（jupiter 会报 55000000 resource 不匹配）

    stt = volc_v3.STT(api_key=voice_key)
    # LLM 用 openai 插件接方舟 Ark（OpenAI 兼容，新版 chat API，支持 function_tool）。
    # 默认 Doubao-Seed-2.0-lite：全模态（音视图文统一理解），一个脑同时管聊天和看图，
    # 后续「看作业」等视觉能力可直接复用这颗脑，不必另接 VLM。
    # 与原版 livekit-agents[openai] 一致；换 DeepSeek 等其它 OpenAI 兼容端点只需改 base_url/key。
    model = os.getenv("LLM_MODEL", "doubao-seed-2-0-lite-260428")
    base_url = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("VOLCENGINE_LLM_API_KEY")
    # 豆包全系列支持 OpenAI 格式：用官方 openai SDK 直接建 AsyncClient 指向方舟端点，
    # 再交给 livekit 的 LLM 节点（AgentSession 需要这层壳）。换任意豆包/兼容模型只改 LLM_MODEL/LLM_BASE_URL。
    client = openai_sdk.AsyncClient(api_key=api_key, base_url=base_url)
    if "doubao" in model.lower() or "volces" in base_url:
        # 豆包 Seed 默认开思考(TTFT 7~12s)，ArkLLM 注入 thinking=disabled 救回 ~1s。
        llm = ArkLLM(model=model, client=client, thinking=os.getenv("LLM_THINKING", "disabled"))
    else:
        llm = openai.LLM(model=model, client=client)
    tts = volc_v3.TTS(api_key=voice_key, speaker=speaker)

    # 断句只用 volc_v3.STT 的服务端 VAD（vad=None）。
    # 教训：再叠一个 silero 本地 VAD 会与 STT 服务端 VAD「双重断句」——
    # 一轮话被切两次、重复触发回复 → TTS 重复说话。要上 silero 必须同时配
    # turn_detection 让两者只有一个做端点，并联机实测确认不重复，再开。
    return AgentSession(stt=stt, llm=llm, tts=tts, vad=None)


# Entry to the agent
async def entrypoint(ctx: agents.JobContext):
    agent = LeLamp(lamp_id="lelamp")

    logging.info("语音通路：三段式（volc_v3 STT + Ark LLM + volc_v3 TTS，新版统一 API）")
    session = _build_session()

    # console 模式本地直连麦克风/扬声器：不挂 LiveKit 云端 BVC 降噪（那是云能力，
    # 本地 console 用不上）。STT 自带服务端 VAD/断句。
    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )

    # 三段式下 generate_reply 真能触发合成，让小灯主动开口。
    await session.generate_reply(
        instructions="用一句话主动打招呼，就说：哒哒——我是小灯！想聊点什么？"
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, num_idle_processes=1))
