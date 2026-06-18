# 小灯（LeLamp 豆包版）软件架构文档

> 本文档描述本仓库（`dd-rongfa/lelamp_runtime`，fork 自 `humancomputerlab/lelamp_runtime`）
> 的软件系统组成。第一阶段目标：把上游基于 OpenAI 的 LeLamp 复现为中文豆包版「小灯」。

## 0. 一句话定位

这不是一个「机器人」，而是**给台灯套了一个能自主调动作和灯光的语音 Agent**：
代码本身只负责「硬件抽象 + 把硬件暴露成 LLM 工具」，对话智能来自外部语音大模型
（上游用 OpenAI Realtime，本仓库换成火山豆包新版统一 API 的 STT+LLM+TTS 三段式）。

## 1. 整体架构

```
                  main.py  (LiveKit Agent 入口)
                       │
        ┌──────────────┴───────────────┐
 语音大脑(STT+LLM+TTS 三段式)      硬件控制(@function_tool)
   常开麦 / 服务端 VAD / 说话           │
                       ┌───────────┼────────────┐
                  MotorsService  RGBService   set_volume(amixer)
                  (电机/动作)     (灯珠)
                       │
              ServiceBase (后台线程 + 优先级事件队列, base.py)
                       │
              LeLampFollower → lerobot → 串口舵机
```

核心设计模式：**事件驱动的服务框架**。每个硬件是一个独立后台线程（`ServiceBase`），
主程序通过 `dispatch(event_type, payload, priority)` 投递事件，线程间互不阻塞。
大模型通过 `@function_tool` 间接调用这些 `dispatch`。

### 语音大脑：STT + LLM + TTS 三段式（唯一通路，全程新版统一 API）

`main.py` 装配单一 `AgentSession`，三个环节全部走火山**新版统一 API**：

| 环节 | 组成 | 说明 |
|---|---|---|
| STT | `volc_v3.STT` | 火山新版 v3「单 X-Api-Key」，seedasr 2.0，自带服务端 VAD 断句 |
| LLM | 官方 openai SDK 接方舟 Ark（默认 Doubao-Seed-2.0-lite **全模态**） | 豆包全系列吃 OpenAI 格式（`AsyncClient` 直连）；**工具调用可用**（`@function_tool` 驱动动作/灯光）；全模态=聊天+看图一颗脑，「看作业」可复用 |
| TTS | `volc_v3.TTS` | 火山新版 v3「单 X-Api-Key」，按音色自动选 resource_id |

STT/TTS 用**本仓库自写插件 `lelamp/voice/volc_v3`**（自包含 WS/HTTP 协议，移植自 voice_test，
不依赖旧 volcengine 插件的 STT/TTS）。该插件按 **livekit-agents 1.5.x** 写成，本仓库即锁 1.5.17（与 voice_test 一致）。
> 历史：早期为省事曾锁在 1.2.9（volcengine 插件遗留）并把 volc_v3 硬塞上去，但 1.2.9 老 turn-handling 在叠 silero VAD 时会导致 TTS 重复；
> 该插件已移除、1.2.9 锁已无意义，故升到 1.5.17——回到 volc_v3 的亲妈版本，silero 也正常了。

断句用 `volc_v3.STT` 的**服务端 VAD**（`end_window_size` 等参数控制）。
断句/打断用本地 **silero VAD**（`livekit-plugins-silero`，基础依赖）——本地端点比 STT 服务端 VAD 跟手。
> 1.5.x 的 turn-handling 会与 volc_v3.STT 协调，不双重触发（早期 1.2.9 上叠 silero 会导致 TTS 重复，升级后解决）。

> **已弃用移除**：旧的 `volcengine.RealtimeModel`（豆包端到端实时，旧 API、`generate_reply` 空壳、不支持工具调用）。
> 当前只保留新版统一 API 的三段式通路。

## 2. 交互范式：常开免唤醒

- 进程启动后 `session.start()` 即常驻，麦克风全程开启。
- 由**模型服务端自带的 VAD**（语音活动检测）判断用户何时开口 / 说完 / 是否打断，
  **没有关键词唤醒（wake word）**这一层。
- 开场：三段式下 `session.generate_reply(...)` 真能触发 LLM+TTS 合成，让小灯主动说第一句。
- 现状权衡：麦一直开 → 费电 / 费算力、旁人闲聊可能误触发；无唤醒词 → 无法待机省电。

## 3. 模块清单

### 3.1 运行主程序
| 文件 | 作用 |
|---|---|
| `main.py` | 运行入口。装配三段式语音（volc_v3 STT + Ark LLM + volc_v3 TTS）+ LeLamp Agent + 4 个工具，运行 LiveKit console |

### 3.2 服务框架 `lelamp/service/`
| 文件 | 作用 |
|---|---|
| `base.py` | 抽象基类 `ServiceBase`：后台线程 + 优先级事件队列（CRITICAL>HIGH>NORMAL>LOW） |
| `motors/motors_service.py` | 电机服务：收到 `play` 事件读取 CSV 逐帧 `send_action` 驱动舵机；含**无硬件 mock 降级**（缺 lerobot 或设 `LELAMP_NO_HARDWARE` 时只打日志） |
| `motors/animation_service.py` | 动作平滑插值相关 |
| `rgb/rgb_service.py` | 灯珠服务：`solid` / `paint` 事件控制 8×5=40 颗灯 |
| `voice/volc_v3/` | 自写火山 v3「单 X-Api-Key」STT/TTS 插件（`_protocol`/`stt`/`tts`），三段式用，移植自 voice_test |

### 3.3 机器人本体（lerobot 一套，纯硬件，与语音无关）
| 文件 | 作用 |
|---|---|
| `follower/` | 从动臂（台灯本体，被控端）配置与驱动 |
| `leader/` | 主动臂（遥操作时手动掰的一端）配置与驱动 |
| `record.py` | 录制动作：手动掰 leader，把舵机角度逐帧存为 CSV |
| `replay.py` | 回放某段 CSV 动作 |
| `list_recordings.py` | 列出可用动作 |
| `calibrate.py` / `setup_motors.py` | 舵机标定 / 初始化（设 ID、零点） |
| `turn_off.py` | 安全关机（回零位、断电） |
| `smooth_animation.py` | 动作平滑实验脚本 |

### 3.4 资源 / 测试 / 工具
| 路径 | 作用 |
|---|---|
| `lelamp/recordings/*.csv` | 10 段预录动作：curious / excited / happy_wiggle / headshake / nod / sad / scanning / shock / shy / wake_up |
| `lelamp/test/` | `test_audio` / `test_motors` / `test_rgb` 硬件自检 |
| `tools/smoke_doubao.py` | 豆包语音冒烟测试（本仓库新增） |
| `pyproject.toml` | 依赖（`livekit-agents[openai]`、lerobot 等；已移除 volcengine 插件） |

## 4. 运行时能力清单

对话期间由大模型自主调用的 `@function_tool`：

1. **语音对话** —— STT + LLM + TTS 三段式（火山豆包新版统一 API）
2. `look` —— **看一眼**：抓一帧（`LAMP_VISION_IMAGE` 固定图兜底 / 摄像头 cv2）→ 全模态豆包描述 → 小灯转述。本仓库相对上游的新增能力（上游无视觉）
3. `play_recording` —— 播放 10 段预录肢体动作之一
4. `set_rgb_solid` —— 设灯纯色
5. `paint_rgb_pattern` —— 画灯图案（40 色，8×5 网格）
6. `set_volume` —— 调系统音量（amixer）

开发期命令行能力（不在对话内）：录制新动作、回放、舵机标定、列动作、硬件自检、安全关机。

## 5. 与上游的差异（本仓库改动）

| 维度 | 上游（OpenAI 版） | 本仓库（豆包三段式版） |
|---|---|---|
| 语音架构 | `openai.realtime.RealtimeModel` 端到端单模型 | STT+LLM+TTS 三段式（全程火山新版统一 API） |
| STT/TTS | （含在 realtime 内） | 自写插件 `lelamp/voice/volc_v3`（v3 单 X-Api-Key） |
| LLM | （含在 realtime 内） | 方舟 Ark chat（OpenAI 兼容，工具可用） |
| 人设 | 英文毒舌 LeLamp | 中文「小灯」 |
| 开场 | `generate_reply(...)` | `generate_reply(...)`（三段式真可用） |
| 降噪 | LiveKit BVC 云端降噪 | console 本地直连，依赖 STT 服务端 VAD |
| 无硬件 | 无 | `LELAMP_NO_HARDWARE` mock 降级 |
| 许可 | — | 补 GPL-3.0 LICENSE + 署名与修改说明 |

## 6. 当前边界（本仓库尚未包含）

以下均**不在**本仓库内，属后续阶段或独立模块：

- 关键词唤醒 / 待机
- 记忆 / 数据库 / 多轮上下文管理
- 视觉（看作业 VLM）
- 投影、gaze
- 实时生成新动作（目前只能回放固定的 10 段 CSV）

> 设计要点：本套代码自身**不含任何决策逻辑**——"说什么、配什么动作、用什么颜色"
> 全部由大模型读取 system prompt 后自主调用工具决定。代码的价值在硬件抽象与工具暴露，
> 对话智能是「租来的」。

## 7. 关键认知（要点提醒）

读这套系统时最该记住的三件事，避免对它的能力产生误判：

1. **"智能"全在大模型，不在这份代码。**
   代码零决策逻辑——说什么、配什么动作、用什么颜色，全是大模型读 system prompt 后
   自己调工具决定的。换模型（OpenAI ↔ 豆包）= 换大脑，硬件层完全不动。
   这意味着「对话质量」是采购/调 prompt 的问题，不是写代码的问题。

2. **动作是"死"的，只能回放固定 10 段 CSV。**
   不能实时生成新动作、不能按语义即兴运动。想要新表情，得离线 `record.py` 重新掰录。
   表现力的上限由这 10 段 + 灯光决定。

3. **它是"语音 Agent 套在台灯上"，不是机器人。**
   印证「台灯 ≠ 机器人载体」的判断：本仓库没有自主移动、没有环境感知闭环、
   没有任务规划，只有「常开对话 + 触发预设硬件反应」。把它当机器人本体去对标会高估它。

> 一句话：**LeLamp 代码的真实贡献是「硬件抽象 + 把硬件暴露成 LLM 工具」，
> 对话智能是租来的。** 评估、扩展、汇报时都应以此为基准。
