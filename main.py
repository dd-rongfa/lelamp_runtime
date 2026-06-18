from dotenv import load_dotenv
import argparse
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
from livekit.plugins import openai
from typing import Union
from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService
from lelamp.voice import volc_v3  # 本仓库自写的火山 v3 单 key STT/TTS（三段式用）

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
    - STT：volc_v3.STT（seedasr 2.0，自带服务端 VAD 断句，无需 silero）。
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
    # 与原版 livekit-agents[openai] 一致；换 DeepSeek 等其它 OpenAI 兼容端点只需改 base_url/key。
    llm = openai.LLM(
        model=os.getenv("LLM_MODEL", "doubao-1-5-lite-32k-250115"),
        base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/"),
        api_key=os.getenv("LLM_API_KEY") or os.getenv("VOLCENGINE_LLM_API_KEY"),
    )
    tts = volc_v3.TTS(api_key=voice_key, speaker=speaker)

    # 可选 silero VAD：装了就用（更稳的断句/打断）；没装就靠 volc_v3.STT 自带 VAD 断句。
    vad = None
    try:
        from livekit.plugins import silero

        vad = silero.VAD.load()
    except Exception:
        pass

    return AgentSession(stt=stt, llm=llm, tts=tts, vad=vad)


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
