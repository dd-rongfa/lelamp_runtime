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

This repository holds the code for controlling LeLamp. The runtime provides a comprehensive control system for the robotic lamp, including motor control, recording/replay functionality, voice interaction, and testing capabilities.

[LeLamp](https://github.com/humancomputerlab/LeLamp) is an open source robot lamp based on [Apple's Elegnt](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement), made by [[Human Computer Lab]](https://www.humancomputerlab.com/)

## Overview

LeLamp Runtime is a Python-based control system that interfaces with the hardware components of LeLamp including:

- Servo motors for articulated movement
- Audio system (microphone and speaker)
- RGB LED lighting
- Camera system
- Voice interaction capabilities

## Project Structure

```
lelamp_runtime/
├── main.py                 # Main runtime entry point
├── pyproject.toml         # Project configuration and dependencies
├── lelamp/                # Core package
│   ├── setup_motors.py    # Motor configuration and setup
│   ├── calibrate.py       # Motor calibration utilities
│   ├── list_recordings.py # List all recorded motor movements
│   ├── record.py          # Movement recording functionality
│   ├── replay.py          # Movement replay functionality
│   ├── follower/          # Follower mode functionality
│   ├── leader/            # Leader mode functionality
│   └── test/              # Hardware testing modules
└── uv.lock               # Dependency lock file
```

## Installation

### Prerequisites

- UV package manager
- Hardware components properly assembled (see main LeLamp documentation)

### Setup

1. Clone the runtime repository:

```bash
git clone https://github.com/humancomputerlab/lelamp_runtime.git
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

To run a conversational agent on LeLamp, create a .env file with the following content in the root of this directory in your Raspberry Pi.

```bash
OPENAI_API_KEY=
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

On how to get LiveKit secrets, please refer to [LiveKit's guide](https://docs.livekit.io/agents/start/voice-ai/). Install LiveKit CLI, then you can run the following command:

```bash
lk app env -w
cat .env.local
```

This will automatically create an `.env.local` file for you, which contains all the secrets on LiveKit side.

On how to get OpenAI secrets, you can follow this [FAQ](https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key).

Then you can run the agent app by:

```bash
# Only need to run this once
sudo uv run main.py download-files

# Pick one of the below
# For Discrete Animation Mode
sudo uv run main.py console

# For Smooth Animation Mode
sudo uv run smooth_animation.py console
```

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
