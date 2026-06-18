# LeLamp Runtime

![](./assets/images/Banner.png)

> **Fork 说明 / Attribution**
> 本仓库 fork 自 [humancomputerlab/lelamp_runtime](https://github.com/humancomputerlab/lelamp_runtime)，
> 原项目 [LeLamp](https://github.com/humancomputerlab/LeLamp) 由 [Human Computer Lab](https://www.humancomputerlab.com/) 开发，遵循 **GNU GPL-3.0**。
> 本 fork 延续 GPL-3.0（见 [LICENSE](./LICENSE)）。
>
> **本 fork 相对上游的改动（GPL §5 要求注明修改）：**
> - 语音后端从 OpenAI Realtime 改为**火山豆包新版统一 API 的 STT + LLM + TTS 三段式**：STT/TTS 用本仓库自写插件 `lelamp/voice/volc_v3`（v3 单 X-Api-Key），LLM 走方舟 Ark；工具调用可用。
> - 新增**无硬件运行**支持：`MotorsService`/`RGBService` 在缺硬件库或设 `LELAMP_NO_HARDWARE=1` 时降级为 mock（只打日志，不碰串口/GPIO），便于在 PC 上做纯语音复现。
> - 人设中文化（小灯）；锁 `livekit-agents==1.5.17`（对齐 voice_test 验证版本）；硬件依赖移入 `pyproject` 的可选 `hardware`。
> - 新增 `tools/smoke_doubao.py`：不开麦的连接/首音延迟冒烟。

本仓库是「小灯」——把上游 [LeLamp](https://github.com/humancomputerlab/LeLamp)（基于 [Apple Elegnt](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement) 的开源机器人台灯，由 [Human Computer Lab](https://www.humancomputerlab.com/) 开发）复现为**中文豆包三段式语音版**的运行时代码。提供电机控制、动作录制/回放、语音对话（工具可用）、RGB 灯光与硬件自检能力。

## 系统架构

> 📐 **完整架构文档见 [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)** —— 整体架构、交互范式、模块清单、运行时能力、与上游差异、关键认知。

一句话定位：**这不是「机器人」，而是给台灯套了一个能自主调动作和灯光的语音 Agent**。代码本身只负责「硬件抽象 + 把硬件暴露成 LLM 工具」，对话智能来自外部语音大模型（上游 OpenAI Realtime → 本仓库火山豆包三段式 STT+LLM+TTS）。

```
                  main.py  (LiveKit Agent 入口)
                       │
        ┌──────────────┴───────────────┐
 语音大脑(STT+LLM+TTS 三段式)      硬件控制(@function_tool)
   常开麦 / 服务端 VAD / 说话           │
                       ┌───────────┼────────────┐
                  MotorsService  RGBService   set_volume(amixer)
                       │
              ServiceBase (后台线程 + 优先级事件队列, base.py)
                       │
              LeLampFollower → lerobot → 串口舵机
```

**关键认知（详见架构文档）：**
- 「智能」全在大模型，代码零决策逻辑——换模型 = 换大脑，硬件层不动。
- 动作是「死」的，只能回放固定 10 段 CSV，想要新表情得离线 `record.py` 重录。
- 交互是**常开免唤醒**：进程启动即常驻开麦，靠服务端 VAD 判断说话，无关键词唤醒。

## 快速开始（无硬件，Windows / macOS / Ubuntu 都行）

> 📖 完整的部署/测试/排坑（含树莓派、真机、常见报错）见 **[`docs/部署与测试.md`](./docs/部署与测试.md)**——发给别人测就发这份。

不需要树莓派、不需要机械臂，一台带麦克风的电脑就能跑通**语音 + 视觉 + 工具调用**。

```bash
# 1. 装 uv（https://docs.astral.sh/uv/），然后：
git clone https://github.com/dd-rongfa/lelamp_runtime.git
cd lelamp_runtime
uv sync                      # 只装语音那套轻依赖，不碰硬件库

# 2. 配凭据（需要你自己的火山豆包 key，见 .env.example 注释里怎么拿）
cp .env.example .env         # Windows PowerShell: copy .env.example .env
#   填 VOLCENGINE_VOICE_API_KEY（语音）和 LLM_API_KEY（方舟 Ark）两把 key

# 3. 跑（要麦克风/扬声器；.env 里已默认 LELAMP_NO_HARDWARE=1 走 mock）
uv run main.py console
```

跑起来后对小灯说话即可。试试：
- 「你好呀」→ 它会用中文搭话（顺带 mock 一个动作/灯光，日志里能看到）
- 「**你看看这是啥？**」→ 它调 `look` 看 `assets/images/1_lamp_3d.png`（仓库自带）并吐槽
- 「**开心地点个头**」→ 它调 `play_recording`（mock 模式只打日志，真机才会动）

**不想接麦克风、只想验证三段式通不通**（连通性 + 各段延迟）：
```bash
uv run tools/smoke_doubao.py     # 不开麦，逐段测 STT/LLM/TTS，打印 PASS/FAIL + 延迟
```

> 真树莓派 / LeLamp 真机部署（让机械臂和灯真的动）见下方 [Installation](#installation) 与 [开机自启](#4-start-upon-boot)，
> 需要 `uv sync --extra hardware` + 舵机标定；ARM 上 lerobot/torch 体积大、装得慢，留足时间。

## 目录结构

```
lelamp_runtime/
├── main.py                 # 运行入口（装配豆包语音 + Agent + 工具）
├── docs/ARCHITECTURE.md    # 软件架构文档
├── tools/smoke_doubao.py   # 豆包语音连接/首音延迟冒烟测试
├── pyproject.toml          # 依赖与项目配置
├── lelamp/                 # 核心包
│   ├── voice/volc_v3/      # 自写火山 v3 单 key STT/TTS 插件（三段式用，移植自 voice_test）
│   ├── service/            # 事件驱动服务框架（base / motors / rgb）
│   ├── recordings/*.csv    # 10 段预录动作
│   ├── setup_motors.py     # 舵机 ID 设置
│   ├── calibrate.py        # 舵机标定
│   ├── list_recordings.py  # 列出动作
│   ├── record.py           # 录制动作
│   ├── replay.py           # 回放动作
│   ├── follower/           # 从动臂（台灯本体）
│   ├── leader/             # 主动臂（遥操作）
│   └── test/               # 硬件自检
└── uv.lock                 # 依赖锁
```

## 安装（真机 / 硬件）

> 只想无硬件体验语音+视觉+工具？看上面的 [快速开始](#快速开始无硬件windows--macos--ubuntu-都行) 就够了。
> 本节是给接了树莓派 / 机械臂的人。

```bash
git clone https://github.com/dd-rongfa/lelamp_runtime.git
cd lelamp_runtime
uv sync                    # 纯软件（语音/视觉/工具），任何电脑都行
uv sync --extra hardware   # 接了舵机/LED 的树莓派再加这个
```

装得慢或 LFS 报错：`GIT_LFS_SKIP_SMUDGE=1 uv sync`、`export UV_CONCURRENT_DOWNLOADS=1`。

**依赖分两层（这也回答了"到底要什么"）：**
- **软件核心**（`uv sync` 就装）：`livekit-agents[openai]`（框架 + 官方 OpenAI SDK 接方舟 Ark）、
  自写 `lelamp/voice/volc_v3`（STT/TTS，无额外包）、`numpy`、`sounddevice`、`python-dotenv`。
- **硬件专用**（`--extra hardware` 才装）：`feetech-servo-sdk`、`lerobot`（机械臂）、
  `rpi-ws281x` / `neopixel`（LED）、`pyaudio`。**无机械臂时完全不需要。**

> API 只需两把火山 key：`VOLCENGINE_VOICE_API_KEY`（语音）+ `LLM_API_KEY`（方舟 Ark，含视觉）。
> 不需要 OpenAI 账号、不需要 LiveKit 云密钥。

## 硬件操作（真机：标定 / 录制 / 回放）

Prior to following the instructions here, you should have an overview of how to control LeLamp through [this tutorial](https://github.com/humancomputerlab/LeLamp/blob/master/docs/5.%20LeLamp%20Control.md).

### 1. Motor Setup and Calibration

1. **Find the servo driver port**:

This command finds the port your motor driver is connected to.

```bash
uv run lerobot-find-port
```

2. **Setup motors with unique IDs**:

This command set up each motor of LeLamp with an unique ID.

```bash
uv run -m lelamp.setup_motors --id your_lamp_name --port the_port_found_in_previous_step
```

3. **Calibrate motors**:

This command calibrate your motors.

```bash
sudo uv run -m lelamp.calibrate --id your_lamp_name --port the_port_found_in_previous_step
```

The calibration process will:

- Calibrate both follower and leader modes
- Ensure proper servo positioning and response
- Set baseline positions for accurate movement

### 2. Unit Testing

The runtime includes comprehensive testing modules to verify all hardware components:

#### RGB LEDs

```bash
# Run with sudo for hardware access
sudo uv run -m lelamp.test.test_rgb
```

#### Audio System (Microphone and Speaker)

```bash
uv run -m lelamp.test.test_audio
```

#### Motors

```bash
uv run -m lelamp.test.test_motors --id your_lamp_name --port the_port_found_in_previous_step
```

### 3. Record and Replay Episodes

One of LeLamp's key features is the ability to record and replay movement sequences:

#### Recording Movement

To record a movement sequence:

```bash
uv run -m lelamp.record --id your_lamp_name --port the_port_found_in_previous_step --name movement_sequence_name
```

This will:

- Put the lamp in recording mode
- Allow you to manually manipulate the lamp
- Save the movement data to a CSV file

#### Replaying Movement

To replay a recorded movement:

```bash
uv run -m lelamp.replay --id your_lamp_name --port the_port_found_in_previous_step --name movement_sequence_name
```

The replay system will:

- Load the movement data from the CSV file
- Execute the recorded movements with proper timing
- Reproduce the original motion sequence

#### Listing Recordings

To view all recordings for a specific lamp:

```bash
uv run -m lelamp.list_recordings --id your_lamp_name
```

This will display:

- All available recordings for the specified lamp
- File information including row count
- Recording names that can be used for replay

#### File Format

Recorded movements are saved as CSV files with the naming convention:
`{sequence_name}.csv`

## 4. Start upon boot

If you want to start LeLamp's voice app upon booting. Create a systemd service file:

```bash
sudo nano /etc/systemd/system/lelamp.service
```

Add this content:

```bash
ini[Unit]
Description=Lelamp Runtime Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/lelamp_runtime
ExecStart=/usr/bin/sudo uv run main.py console
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lelamp.service
sudo systemctl start lelamp.service
```

For other service controls:

```bash
# Disable from starting on boot
sudo systemctl disable lelamp.service

# Stop the currently running service
sudo systemctl stop lelamp.service

# Check status (should show "disabled" and "inactive")
sudo systemctl status lelamp.service
```

Note: Boot time might vary with each run and extended usage (>1 hour) can burn the motors.

## Sample Apps

Sample apps to test LeLamp's capabilities.

### LiveKit Voice Agent

本 fork 用 **STT + LLM + TTS 三段式**，全程走火山**新版统一 API**，工具调用可用（能驱动动作/灯光）：

| 环节 | 用什么 | 说明 |
|---|---|---|
| STT | `lelamp/voice/volc_v3`（自写） | 火山新版 v3「单 X-Api-Key」，seedasr 2.0，自带服务端 VAD 断句 |
| LLM | 官方 **openai SDK** 接方舟 Ark（默认 Doubao-Seed-2.0-lite **全模态**） | 豆包全系列吃 OpenAI 格式，`AsyncClient` 直连；支持 `function_tool`；全模态=聊天+看图一颗脑；换 DeepSeek 等只改 `LLM_BASE_URL` |
| TTS | `lelamp/voice/volc_v3`（自写） | 火山新版 v3「单 X-Api-Key」，按音色自动选 resource_id |

> `volc_v3` 是**本仓库自写插件**（自包含 WS/HTTP 协议，移植自 voice_test），不依赖旧 volcengine 插件的 STT/TTS。
> 它对应 livekit-agents **1.5.x**，本仓库即锁 1.5.17（与 voice_test 一致）。
> 旧的 `volcengine.RealtimeModel`（端到端实时、旧 API、不支持工具）已**弃用移除**。

console 本地模式直连麦克风/扬声器，**不需要** LiveKit 云端密钥。在仓库根目录建 `.env`：

```bash
VOLCENGINE_VOICE_API_KEY=          # STT/TTS 共用：火山新版 v3 单 X-Api-Key（volc_v3 用）
LLM_API_KEY=                       # LLM：方舟 Ark 的 LLM key（与语音 key 两套，不可混用；旧名 VOLCENGINE_LLM_API_KEY 仍兼容）
# 可选：LLM_MODEL（默认 doubao-seed-2-0-lite-260428，Doubao-Seed-2.0-lite 全模态）/ LLM_BASE_URL（默认 Ark；换 DeepSeek 等改这里）
# 可选：LLM_THINKING（默认 disabled；豆包 Seed 默认开思考会让 TTFT 飙到 7~12s，关掉降到 ~1s，语音必关）/ LAMP_SPEAKER（默认 uranus 女声 Vivi 2.0）
# 可选（视觉）：LAMP_VISION_IMAGE（指一张图，小灯 look 时用它；无摄像头也能验证视觉）/ LAMP_CAMERA_INDEX（cv2 摄像头序号，默认 0）
```

运行：

```bash
sudo uv run main.py console

# 平滑动画模式
sudo uv run smooth_animation.py console
```

无硬件（PC 上纯语音复现）时设 `LELAMP_NO_HARDWARE=1`，电机/灯光降级为 mock 只打日志。
断句/打断用本地 **silero VAD**（基础依赖，`uv sync` 自动装）——本地端点比 STT 服务端 VAD 跟手。
（注：1.5.x 的 turn-handling 会与 volc_v3.STT 协调，不会双重触发；早期在 1.2.9 上叠 silero 曾导致回复重复，升级到 1.5.17 后解决。）

In case your lamp is not `lelamp`, change the id of the lamp inside main.py:

```py
async def entrypoint(ctx: agents.JobContext):
    agent = LeLamp(lamp_id="lelamp") # <- Chnage the name here
```

## Contributing

This is an open-source project by Human Computer Lab. Contributions are welcome through the GitHub repository.

## Maintainers
Maintained by [Human Computer Lab](https://www.humancomputerlab.com).

## Acknowledgments & Sponsors
See [CONTRIBUTORS.md](./CONTRIBUTORS.md) for contributors and their roles.  
See [SPONSORS.md](./SPONSORS.md) for sponsor thanks and how to support the project.

## License

本项目遵循 **GNU General Public License v3.0**（GPL-3.0），与上游 [LeLamp](https://github.com/humancomputerlab/LeLamp) 一致。完整条款见 [LICENSE](./LICENSE)。

GPL-3.0 是传染性 copyleft：你可以自由使用、修改、再分发本代码，但衍生作品在分发时必须同样以 GPL-3.0 开源并提供源码、保留版权与署名、注明所做修改。
