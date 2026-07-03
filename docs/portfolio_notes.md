# Portfolio Notes

This project can be presented as a compact radar engineering demo:

- **Embedded side**: byte-stream parser, CRC validation, fixed-size data structures, no heap allocation.
- **Algorithm side**: SNR/range gate, nearest-neighbor association, track stability rules.
- **Host side**: deterministic simulation, CSV replay, simple visual feedback, testable protocol implementation.
- **Engineering workflow**: validate logic on PC first, then port the stable C core to STM32 UART DMA.

## Suggested Demo Script

1. Run the simulator and show the ASCII target map.
2. Open `data/sample_capture.csv` to explain measurement rows and stable track rows.
3. Show that Python and C share the same frame definition.
4. Explain how a live radar module would replace the simulator.
5. Discuss planned PyQt visualization or CAN/USB telemetry output.

## Possible Extensions

- Add PyQtGraph or Three.js visualization.
- Add alpha-beta filtering for smoother velocity estimates.
- Replace CSV replay with live serial input from a radar module.
- Add STM32CubeMX project files for a specific MCU board.
- Record real indoor/outdoor captures and compare against simulation.
