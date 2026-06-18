r"""三段式分段冒烟（不开麦克风）。

逐段验证「火山豆包新版统一 API」三段式各自通不通 + 测每段延迟：
  [LLM] openai 插件 → 方舟 Ark：文本进 → 文本出（TTFT 首字 + 总时长）
  [TTS] volc_v3.TTS：文本进 → 音频出（首帧延迟 + 音频时长/字节）
  [STT] volc_v3.STT：把 TTS 产出的 16k PCM 喂回去 → 转写（首结果延迟 + 终稿文本）

STT 直接吃 TTS 的输出（统一 16k PCM），所以**不需要麦克风**，还顺带验证 TTS↔STT 闭环。

跑（lelamp_runtime 目录）：
    .\.venv\Scripts\python.exe tools\smoke_doubao.py                 # 跑全部三段
    .\.venv\Scripts\python.exe tools\smoke_doubao.py --stage llm     # 只测某段
    .\.venv\Scripts\python.exe tools\smoke_doubao.py --text "你好呀"  # 自定义文本

凭据（.env）：
  VOLCENGINE_VOICE_API_KEY  —— STT/TTS 共用的火山新版 v3 单 X-Api-Key
  LLM_API_KEY               —— 方舟 Ark 的 LLM key（旧名 VOLCENGINE_LLM_API_KEY 仍兼容）
缺哪段的 key，对应段打 SKIP，不影响其它段。
"""
import argparse
import asyncio
import os
import sys
import time

import aiohttp
from dotenv import load_dotenv

import openai as openai_sdk  # 官方 OpenAI SDK：豆包全系列吃 OpenAI 格式
from livekit import rtc
from livekit.agents import APIConnectOptions
from livekit.agents import llm as livekit_llm
from livekit.agents import stt as livekit_stt
from livekit.plugins import openai

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lelamp.voice import volc_v3  # noqa: E402

load_dotenv()

SR = 16000  # 统一 16k：TTS 直接出 16k、STT 也吃 16k，省去重采样
STAGE_TIMEOUT = 25.0
# 冒烟要的是快速「通/不通」，所以少重试、短超时（默认会重试 3-4 次，又慢又吵）。
CONN = APIConnectOptions(max_retry=1, timeout=10.0)


def _env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


async def smoke_llm() -> bool | None:
    """openai 插件接方舟 Ark：测连通 + 首字(TTFT) + 总时长。"""
    key = _env("LLM_API_KEY", "VOLCENGINE_LLM_API_KEY")
    if not key:
        print("[LLM ] SKIP  缺 LLM_API_KEY（方舟 Ark）")
        return None
    model = os.getenv("LLM_MODEL", "doubao-seed-2-0-lite-260428")  # Doubao-Seed-2.0-lite 全模态
    base_url = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/")
    client = openai_sdk.AsyncClient(api_key=key, base_url=base_url)  # 官方 SDK 客户端
    brain = openai.LLM(model=model, client=client)
    # 豆包 Seed 默认开「思考」，TTFT 7~12s；关掉降到 ~1s。冒烟按实际用法关思考。
    extra = {}
    if "doubao" in model.lower() or "volces" in base_url:
        extra["extra_kwargs"] = {"extra_body": {"thinking": {"type": os.getenv("LLM_THINKING", "disabled")}}}

    ctx = livekit_llm.ChatContext.empty()
    ctx.add_message(role="system", content="你是小灯，一盏爱吐槽的台灯，用一句简短中文回答。")
    ctx.add_message(role="user", content="用一句话跟我打个招呼。")

    t0 = time.perf_counter()
    ttft = None
    buf = ""
    stream = brain.chat(chat_ctx=ctx, conn_options=CONN, **extra)
    try:
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            piece = getattr(delta, "content", None) if delta else None
            if piece:
                if ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
                buf += piece
    finally:
        await stream.aclose()

    if not buf:
        print("[LLM ] FAIL  连上了但没拿到文本（检查 model/base_url）")
        return False
    total = (time.perf_counter() - t0) * 1000
    print(f"[LLM ] PASS  TTFT {ttft:.0f}ms  总 {total:.0f}ms  回复：{buf.strip()[:40]}")
    return True


async def smoke_tts(text: str, http: aiohttp.ClientSession, out: list[bytes]) -> bool | None:
    """volc_v3.TTS：测连通 + 首帧延迟 + 音频量。通过则把 16k PCM 追加到 out 给 STT 用。

    返回三态：True=通过、False=失败、None=跳过（缺 key）。
    """
    key = _env("VOLCENGINE_VOICE_API_KEY")
    if not key:
        print("[TTS ] SKIP  缺 VOLCENGINE_VOICE_API_KEY")
        return None
    tts = volc_v3.TTS(
        api_key=key,
        speaker=os.getenv("LAMP_SPEAKER", "zh_female_vv_uranus_bigtts"),
        sample_rate=SR,
        http_session=http,
    )

    t0 = time.perf_counter()
    first = None
    pcm = bytearray()
    cs = tts.synthesize(text, conn_options=CONN)
    try:
        async for ev in cs:
            if first is None:
                first = (time.perf_counter() - t0) * 1000
            pcm += bytes(ev.frame.data)
    finally:
        await cs.aclose()

    if not pcm:
        print("[TTS ] FAIL  连上了但没拿到音频（检查音色/resource_id）")
        return False
    total = (time.perf_counter() - t0) * 1000
    secs = len(pcm) / 2 / SR
    print(f"[TTS ] PASS  首帧 {first:.0f}ms  总 {total:.0f}ms  音频 {secs:.1f}s / {len(pcm)}B")
    out.append(bytes(pcm))
    return True


async def smoke_stt(pcm: bytes | None, http: aiohttp.ClientSession) -> bool | None:
    """volc_v3.STT：把 TTS 的 PCM 喂回去，测连通 + 首结果延迟 + 终稿文本。"""
    key = _env("VOLCENGINE_VOICE_API_KEY")
    if not key:
        print("[STT ] SKIP  缺 VOLCENGINE_VOICE_API_KEY")
        return None
    if not pcm:
        print("[STT ] SKIP  需要 TTS 的 PCM 作为输入（TTS 未产出）")
        return None

    stt = volc_v3.STT(api_key=key, sample_rate=SR, http_session=http)
    stream = stt.stream(conn_options=CONN)
    chunk_bytes = SR // 10 * 2  # 100ms / 帧

    async def push() -> None:
        for i in range(0, len(pcm), chunk_bytes):
            seg = pcm[i:i + chunk_bytes]
            spc = len(seg) // 2
            if spc:
                stream.push_frame(rtc.AudioFrame(seg, SR, 1, spc))
            await asyncio.sleep(0)
        stream.end_input()

    t0 = time.perf_counter()
    first = None
    final = ""
    pusher = asyncio.create_task(push())
    try:
        async for ev in stream:
            if ev.type == livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT and first is None:
                first = (time.perf_counter() - t0) * 1000
            elif ev.type == livekit_stt.SpeechEventType.FINAL_TRANSCRIPT:
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                if ev.alternatives:
                    final = ev.alternatives[0].text
        await pusher
    finally:
        await stream.aclose()

    if not final:
        print("[STT ] FAIL  连上了但没转出文本（音频可能太短/格式不符）")
        return False
    print(f"[STT ] PASS  首结果 {first:.0f}ms  转写：{final[:40]}")
    return True


async def _guard(name: str, coro):
    """统一超时 + 异常兜底，保证一段挂了不连累其它段。"""
    try:
        return await asyncio.wait_for(coro, STAGE_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"[{name}] TIMEOUT  >{STAGE_TIMEOUT:.0f}s（多半凭据/网络/服务未开通）")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] FAIL  {type(e).__name__}: {e}")
        return False


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["all", "llm", "tts", "stt"], default="all")
    ap.add_argument("--text", default="哒哒，我是小灯，今天想聊点什么呀？")
    args = ap.parse_args()

    print("=== 小灯三段式分段冒烟（新版统一 API，不开麦）===")
    results: dict[str, bool | None] = {}

    if args.stage in ("all", "llm"):
        results["LLM"] = await _guard("LLM ", smoke_llm())

    async with aiohttp.ClientSession() as http:
        pcm_out: list[bytes] = []
        if args.stage in ("all", "tts", "stt"):
            tts_res = await _guard("TTS ", smoke_tts(args.text, http, pcm_out))
            if args.stage in ("all", "tts"):
                results["TTS"] = tts_res
        if args.stage in ("all", "stt"):
            pcm = pcm_out[0] if pcm_out else None
            results["STT"] = await _guard("STT ", smoke_stt(pcm, http))

    flags = [v for v in results.values() if v is not None]
    ok = sum(1 for v in flags if v)
    print(f"--- 小结：{ok}/{len(flags)} 段通过 ---")
    if flags and ok < len(flags):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
