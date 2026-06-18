# LeLamp Runtime

![](./assets/images/Banner.png)

> **Fork 说明 / Attribution**
> 本仓库 fork 自 [humancomputerlab/lelamp_runtime](https://github.com/humancomputerlab/lelamp_runtime)，
> 原项目 [LeLamp](https://github.com/humancomputerlab/LeLamp) 由 [Human Computer Lab](https://www.humancomputerlab.com/) 开发，遵循 **GNU GPL-3.0**。
> 本 fork 延续 GPL-3.0（见 [LICENSE](./LICENSE)）。
>
> **本 fork 相对上游的改动（GPL §5 要求注明修改）：**
> - 语音后端从 OpenAI Realtime 替换为**豆包端到端实时语音大模型**（`livekit-plugins-volcengine` 的 `RealtimeModel`）。
> - 新增**无硬件运行**支持：`MotorsService`/`RGBService` 在缺硬件库或设 `LELAMP_NO_HARDWARE=1` 时降级为 mock（只打日志，不碰串口/GPIO），便于在 PC 上做纯语音复现。
> - 人设中文化（小灯）；锁定 `livekit-agents==1.2.9`；硬件依赖移入 `pyproject` 的可选 `hardware`。
> - 新增 `tools/smoke_doubao.py`：不开麦的连接/首音延迟冒烟。

本仓库是「小灯」——把上游 [LeLamp](https://github.com/humancomputerlab/LeLamp)（基于 [Apple Elegnt](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement) 的开源机器人台灯，由 [Human Computer Lab](https://www.humancomputerlab.com/) 开发）复现为**中文豆包端到端实时语音版**的运行时代码。提供电机控制、动作录制/回放、实时语音对话、RGB 灯光与硬件自检能力。

## 系统架构

> 📐 **完整架构文档见 [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)** —— 整体架构、交互范式、模块清单、运行时能力、与上游差异、关键认知。

一句话定位：**这不是「机器人」，而是给台灯套了一个能自主调动作和灯光的实时语音 Agent**。代码本身只负责「硬件抽象 + 把硬件暴露成 LLM 工具」，对话智能完全来自外部实时语音大模型（上游 OpenAI Realtime → 本仓库豆包 / volcengine Realtime）。

```
                  main.py  (LiveKit Agent 入口)
                       │
        ┌──────────────┴───────────────┐
   语音大脑(豆包 Realtime)          硬件控制(@function_tool)
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

## 目录结构

```
lelamp_runtime/
├── main.py                 # 运行入口（装配豆包语音 + Agent + 工具）
├── docs/ARCHITECTURE.md    # 软件架构文档
├── tools/smoke_doubao.py   # 豆包语音连接/首音延迟冒烟测试
├── pyproject.toml          # 依赖与项目配置
├── lelamp/                 # 核心包
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

## Installation

### Prerequisites

- UV package manager
- Hardware components properly assembled (see main LeLamp documentation)

### Setup

1. Clone the runtime repository:

```bash
git clone https://github.com/dd-rongfa/lelamp_runtime.git
cd lelamp_runtime
```

2. Install UV (if not already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. Install dependencies:

```bash
# If on your personal computer
uv sync

# If on Raspberry Pi
uv sync --extra hardware
```

**Note**: For motor setup and control, LeLamp Runtime can run on your computer and you only need to run `uv sync`. For other functionality that connects to the head Pi (LED control, audio, camera), you need to install LeLamp Runtime on that Pi and run `uv sync --extra hardware`.

If you have LFS problems, run the following command:

```bash
GIT_LFS_SKIP_SMUDGE=1 uv sync
```

If your installation process is slow, use the following environment variable:

```bash
export UV_CONCURRENT_DOWNLOADS=1
```

### Dependencies

The runtime includes several key dependencies:

- **feetech-servo-sdk**: For servo motor control
- **lerobot**: Robotics framework integration
- **livekit-agents**: Real-time voice interaction
- **numpy**: Mathematical operations
- **sounddevice**: Audio input/output
- **adafruit-circuitpython-neopixel**: RGB LED control (hardware)
- **rpi-ws281x**: Raspberry Pi LED control (hardware)

## Core Functionality

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

本 fork 用**豆包端到端实时语音**，运行前在仓库根目录建 `.env`：

```bash
# 豆包 / 火山引擎实时语音（main.py 读取）
VOLCENGINE_REALTIME_APP_ID=
VOLCENGINE_REALTIME_ACCESS_TOKEN=
```

> 凭据说明：插件默认读 `VOLCENGINE_REALTIME_APP_ID` / `VOLCENGINE_REALTIME_ACCESS_TOKEN`；
> `main.py` 也兼容 `VOLCENGINE_APP_ID` 命名。注意新版单 key 与旧版双参不可混用。

console 本地模式直连麦克风/扬声器，**不需要** LiveKit 云端密钥。运行：

```bash
# Pick one of the below
# 离散动画模式（默认）
sudo uv run main.py console

# 平滑动画模式
sudo uv run smooth_animation.py console
```

无硬件（PC 上纯语音复现）时设 `LELAMP_NO_HARDWARE=1`，电机/灯光降级为 mock 只打日志。
连接/首音延迟冒烟（不开麦）：`uv run tools/smoke_doubao.py`。

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
