r"""豆包 RealtimeModel 非交互冒烟 + 首音延迟测试（不开麦克风）。

验证：凭据 / WebSocket 握手 / 端到端协议 / livekit 插件 四者打通。
做法：建 RealtimeModel → session() 自动连接并发送 opening 开场白 →
监听 generation_created，消费返回的 text/audio 流，测「连接 → 首个音频帧」延迟。

跑（lelamp_runtime 目录）：
    .\.venv\Scripts\python.exe tools\smoke_doubao.py
"""
import asyncio
import os
import time

import aiohttp
from dotenv import load_dotenv

from livekit.plugins import volcengine

load_dotenv()


async def main() -> None:
    app_id = os.getenv("VOLCENGINE_REALTIME_APP_ID") or os.getenv("VOLCENGINE_APP_ID")
    token = os.getenv("VOLCENGINE_REALTIME_ACCESS_TOKEN")
    if not app_id or not token:
        raise SystemExit("缺少 VOLCENGINE_APP_ID / VOLCENGINE_REALTIME_ACCESS_TOKEN（看 .env）")

    async with aiohttp.ClientSession() as http:
        t0 = time.time()
        model = volcengine.RealtimeModel(
            app_id=app_id,
            access_token=token,
            model="O",
            bot_name="小灯",
            system_role="你是小灯，一盏爱吐槽的台灯，用简短中文回答。",
            speaker="zh_female_vv_jupiter_bigtts",
            opening="哒哒——我是小灯！",
            http_session=http,
        )
        sess = model.session()

        first_audio_ms = {}
        done = asyncio.Event()

        def on_generation(ev) -> None:
            async def consume() -> None:
                async for msg in ev.message_stream:
                    async def read_audio(m=msg) -> None:
                        frames = 0
                        async for _frame in m.audio_stream:
                            if "ms" not in first_audio_ms:
                                first_audio_ms["ms"] = (time.time() - t0) * 1000
                                print(f"[首个音频帧] {first_audio_ms['ms']:.0f} ms")
                            frames += 1
                        print(f"[音频结束] 共 {frames} 帧")
                        done.set()

                    async def read_text(m=msg) -> None:
                        buf = ""
                        async for t in m.text_stream:
                            buf += t
                        print(f"[模型文本] {buf}")

                    asyncio.create_task(read_audio())
                    asyncio.create_task(read_text())

            asyncio.create_task(consume())

        def on_error(ev) -> None:
            print(f"[ERROR] {getattr(ev, 'error', ev)}")
            done.set()

        sess.on("generation_created", on_generation)
        sess.on("error", on_error)

        print("已发起连接，等待开场白音频…（最多 15s）")
        try:
            await asyncio.wait_for(done.wait(), timeout=15)
        except asyncio.TimeoutError:
            print("[超时] 15s 内没收到音频——多半是凭据/网络/服务未开通")
        finally:
            await sess.aclose()


if __name__ == "__main__":
    asyncio.run(main())
