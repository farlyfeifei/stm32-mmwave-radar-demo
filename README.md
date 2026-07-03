# STM32 mmWave Radar Target Detection Demo

An original portfolio demo for a single-radar low-altitude target detection workflow. The project contains a portable C detection core that can be dropped into an STM32 firmware project, plus a Python host-side simulator/replay tool for validating the packet protocol and tracking logic before hardware testing.

## Highlights

- UART frame protocol for mmWave radar point targets.
- CRC-16/CCITT frame validation and byte-stream parser.
- SNR/range gate filtering for noisy radar measurements.
- Lightweight nearest-neighbor tracker with exponential smoothing.
- Python simulator that generates crossing targets, clutter, and missed detections.
- CSV replay flow for upper-computer visualization or PyQt integration.

## Repository Layout

```text
.
├── firmware/
│   └── radar_demo.c          # Portable C parser + target tracker + STM32 integration notes
├── host/
│   ├── __init__.py
│   ├── radar_demo.py         # Simulator, parser, tracker, CSV replay, ASCII display
│   └── radar_viewer.py       # PyQt5 real-time 2D PPI visualization upper-computer
├── data/
│   └── sample_capture.csv    # Example generated capture
├── docs/
│   ├── algorithm.md
│   ├── portfolio_notes.md
│   └── protocol.md
└── tests/
    └── test_radar_demo.py
```

## Quick Start

Run the host-side simulator and tracker:

```powershell
python .\host\radar_demo.py --simulate --frames 80 --csv .\data\sample_capture.csv --ascii-map
```

Replay an existing CSV capture:

```powershell
python .\host\radar_demo.py --replay .\data\sample_capture.csv --ascii-map
```

### PyQt 可视化上位机

`host/radar_viewer.py` 是一个基于 PyQt5 的实时 2D 雷达可视化上位机,用 QPainter 自绘 PPI 风格画布(不依赖 matplotlib),由 QTimer 每 100ms 取一帧数据驱动。

先安装依赖(Python 3.8+):

```powershell
python -m pip install PyQt5
```

模拟模式 —— 调用 `generate_scenario` 生成确定性场景(两个交叉目标 + 杂波 + 漏检):

```powershell
python .\host\radar_viewer.py --simulate --frames 80
```

回放模式 —— 回放 `radar_demo.py --csv` 导出的 measurement CSV:

```powershell
python .\host\radar_viewer.py --replay .\data\sample_capture.csv
```

画布说明:

- 同心距离环每 10m 一圈(到 30m),十字准线 + 每 30° 方位角刻度,中心为雷达位置,并带 PPI 扫描动画。
- 目标点:稳定航迹(`Track.stable`)为绿色实心圆,不稳定为黄色;圆半径按 SNR(`confidence`)缩放。
- 每个目标标注 `track_id`、距离、速度,并绘制径向速度矢量箭头(粉色,正值远离、负值接近)。
- 目标轨迹拖尾保留最近 10 帧位置,按时间渐变透明度。
- 右侧信息面板显示当前帧号、稳定目标数,以及各航迹的 `track_id / range / velocity / angle / SNR / age / 状态`。
- 深色背景 `#0a0f14`,科技感配色(青色 `#4fd1ff` 网格,绿色 `#50fa7b` 稳定目标)。

> 无显示环境(如 CI/远程)可设置 `QT_QPA_PLATFORM=offscreen` 以确认能无报错启动。

Run the Python tests:

```powershell
python -m unittest discover -s tests
```

Compile the portable C self-test with GCC or MinGW:

```powershell
New-Item -ItemType Directory -Force .\build
gcc .\firmware\radar_demo.c -DRADAR_DEMO_SELF_TEST -o .\build\radar_demo.exe
.\build\radar_demo.exe
```

## Hardware Mapping

The firmware code is intentionally HAL-independent so it can be reused with STM32F4, STM32G4, or STM32H7 projects. A typical wiring setup is:

| Signal | Radar Module | STM32 |
| --- | --- | --- |
| TX | UART TX | USART RX with DMA |
| RX | UART RX | USART TX, optional |
| 5V/3V3 | Power | Regulated supply |
| GND | Ground | Common ground |

Integration points:

- Push DMA/interrupt bytes into `radar_parser_push_byte`.
- Call `tracker_update` whenever a complete frame is decoded.
- Publish stable tracks to UART, CAN, USB CDC, or a Python upper-computer app.

## Portfolio Usage

This project is designed to demonstrate an engineering workflow rather than a copied contest deliverable:

1. Define a compact radar frame protocol.
2. Validate parsing and target tracking using simulation.
3. Port the pure C core into STM32 firmware.
4. Replace simulated CSV frames with live UART packets.
5. Extend the host tool into PyQt or web visualization if needed.

## License

MIT. Keep attribution if you reuse the code.
