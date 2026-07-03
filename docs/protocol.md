# Radar UART Protocol

The demo uses a compact binary frame so that the same payload can be produced by a radar module, replayed from Python, or consumed by STM32 firmware.

## Frame Format

| Field | Bytes | Type | Description |
| --- | ---: | --- | --- |
| magic | 2 | `0xAA55` | Frame start marker |
| version | 1 | `uint8` | Protocol version, currently `1` |
| seq | 1 | `uint8` | Rolling frame sequence |
| count | 1 | `uint8` | Number of target measurements |
| targets | `8 * count` | repeated struct | Encoded radar targets |
| crc | 2 | `uint16_le` | CRC-16/CCITT over header and payload |

Each target is encoded as:

| Field | Bytes | Type | Unit |
| --- | ---: | --- | --- |
| range | 2 | `int16_le` | centimeters |
| velocity | 2 | `int16_le` | centimeters per second |
| angle | 2 | `int16_le` | centi-degrees |
| snr | 2 | `uint16_le` | Q8 dB |

## Parser Behavior

The parser is designed for UART DMA or interrupt reception:

1. Ignore bytes until `0xAA 0x55`.
2. Read version, sequence, and target count.
3. Calculate the expected frame length.
4. Validate CRC before exposing the decoded frame.
5. Reset parser state on malformed headers or oversize frames.

## Why This Protocol

The frame is intentionally small because many radar demos run over 115200 or 921600 baud UART links. Fixed-size target records avoid dynamic allocation on STM32, and CRC validation prevents clutter bytes from being misinterpreted as real targets.
