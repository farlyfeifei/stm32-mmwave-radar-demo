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
│   └── radar_demo.py         # Simulator, parser, tracker, CSV replay, ASCII display
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
