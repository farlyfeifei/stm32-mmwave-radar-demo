from __future__ import annotations

import argparse
import csv
import math
import random
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


MAGIC = b"\xAA\x55"
VERSION = 1
MAX_TARGETS = 8
TARGET_STRUCT = struct.Struct("<hhhH")
HEADER_STRUCT = struct.Struct("<2sBBB")


@dataclass(frozen=True)
class Measurement:
    range_m: float
    velocity_mps: float
    angle_deg: float
    snr_db: float


@dataclass
class Track:
    track_id: int
    range_m: float
    velocity_mps: float
    angle_deg: float
    confidence: float
    age: int = 1
    missed: int = 0

    @property
    def stable(self) -> bool:
        return self.age >= 3 and self.confidence >= 10.0 and self.missed <= 2


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _quantize(value: float, scale: float, minimum: int, maximum: int) -> int:
    quantized = int(round(value * scale))
    return max(minimum, min(maximum, quantized))


def encode_frame(seq: int, measurements: Sequence[Measurement]) -> bytes:
    if len(measurements) > MAX_TARGETS:
        raise ValueError(f"at most {MAX_TARGETS} targets can be encoded in one frame")

    payload = bytearray()
    for item in measurements:
        payload.extend(
            TARGET_STRUCT.pack(
                _quantize(item.range_m, 100.0, -32768, 32767),
                _quantize(item.velocity_mps, 100.0, -32768, 32767),
                _quantize(item.angle_deg, 100.0, -32768, 32767),
                _quantize(item.snr_db, 256.0, 0, 65535),
            )
        )

    header = HEADER_STRUCT.pack(MAGIC, VERSION, seq & 0xFF, len(measurements))
    body = header + payload
    return body + struct.pack("<H", crc16_ccitt(body))


def decode_frame(raw: bytes) -> tuple[int, list[Measurement]]:
    if len(raw) < HEADER_STRUCT.size + 2:
        raise ValueError("frame is too short")

    magic, version, seq, count = HEADER_STRUCT.unpack(raw[: HEADER_STRUCT.size])
    if magic != MAGIC:
        raise ValueError("bad frame magic")
    if version != VERSION:
        raise ValueError(f"unsupported protocol version: {version}")
    if count > MAX_TARGETS:
        raise ValueError("too many targets in frame")

    expected = HEADER_STRUCT.size + count * TARGET_STRUCT.size + 2
    if len(raw) != expected:
        raise ValueError(f"bad frame length: expected {expected}, got {len(raw)}")

    received_crc = struct.unpack("<H", raw[-2:])[0]
    calculated_crc = crc16_ccitt(raw[:-2])
    if received_crc != calculated_crc:
        raise ValueError("crc mismatch")

    measurements: list[Measurement] = []
    offset = HEADER_STRUCT.size
    for _ in range(count):
        range_cm, velocity_cms, angle_cdeg, snr_q8 = TARGET_STRUCT.unpack(
            raw[offset : offset + TARGET_STRUCT.size]
        )
        measurements.append(
            Measurement(
                range_m=range_cm / 100.0,
                velocity_mps=velocity_cms / 100.0,
                angle_deg=angle_cdeg / 100.0,
                snr_db=snr_q8 / 256.0,
            )
        )
        offset += TARGET_STRUCT.size

    return seq, measurements


def parse_stream(stream: bytes) -> Iterator[tuple[int, list[Measurement]]]:
    cursor = 0
    while cursor < len(stream):
        start = stream.find(MAGIC, cursor)
        if start < 0 or start + HEADER_STRUCT.size > len(stream):
            return
        _, version, seq, count = HEADER_STRUCT.unpack(stream[start : start + HEADER_STRUCT.size])
        if version != VERSION or count > MAX_TARGETS:
            cursor = start + 1
            continue
        length = HEADER_STRUCT.size + count * TARGET_STRUCT.size + 2
        frame = stream[start : start + length]
        if len(frame) < length:
            return
        try:
            yield decode_frame(frame)
            cursor = start + length
        except ValueError:
            cursor = start + 1


class RadarTracker:
    def __init__(self, max_tracks: int = 6) -> None:
        self.max_tracks = max_tracks
        self.next_id = 1
        self.tracks: list[Track] = []

    @staticmethod
    def _distance(track: Track, measurement: Measurement) -> float:
        return (
            abs(track.range_m - measurement.range_m)
            + abs(track.velocity_mps - measurement.velocity_mps) * 0.4
            + abs(track.angle_deg - measurement.angle_deg) * 0.05
        )

    @staticmethod
    def _valid(measurement: Measurement) -> bool:
        return 0.3 <= measurement.range_m <= 80.0 and measurement.snr_db >= 8.0

    def update(self, measurements: Sequence[Measurement]) -> list[Track]:
        for track in self.tracks:
            track.missed += 1

        used: set[int] = set()
        for measurement in measurements:
            if not self._valid(measurement):
                continue

            best_index = None
            best_score = 2.5
            for index, track in enumerate(self.tracks):
                if index in used:
                    continue
                score = self._distance(track, measurement)
                if score < best_score:
                    best_score = score
                    best_index = index

            if best_index is None:
                if len(self.tracks) >= self.max_tracks:
                    continue
                self.tracks.append(
                    Track(
                        track_id=self.next_id,
                        range_m=measurement.range_m,
                        velocity_mps=measurement.velocity_mps,
                        angle_deg=measurement.angle_deg,
                        confidence=measurement.snr_db,
                    )
                )
                self.next_id += 1
                used.add(len(self.tracks) - 1)
                continue

            track = self.tracks[best_index]
            alpha = 0.35
            track.range_m = alpha * measurement.range_m + (1.0 - alpha) * track.range_m
            track.velocity_mps = alpha * measurement.velocity_mps + (1.0 - alpha) * track.velocity_mps
            track.angle_deg = alpha * measurement.angle_deg + (1.0 - alpha) * track.angle_deg
            track.confidence = alpha * measurement.snr_db + (1.0 - alpha) * track.confidence
            track.age += 1
            track.missed = 0
            used.add(best_index)

        self.tracks = [track for track in self.tracks if track.missed <= 5]
        return [track for track in self.tracks if track.stable]


def generate_scenario(frame_count: int) -> Iterator[tuple[int, list[Measurement]]]:
    for seq in range(frame_count):
        rng = random.Random(2026 + seq)
        time_s = seq * 0.08
        measurements: list[Measurement] = []

        # Two deterministic targets with a few controlled dropouts and clutter.
        if seq % 17 != 0:
            measurements.append(
                Measurement(
                    range_m=18.0 - 0.55 * time_s + rng.uniform(-0.08, 0.08),
                    velocity_mps=-0.55 + rng.uniform(-0.04, 0.04),
                    angle_deg=-11.0 + 0.9 * time_s + rng.uniform(-0.3, 0.3),
                    snr_db=17.0 + rng.uniform(-1.2, 1.2),
                )
            )
        if seq > 12 and seq % 23 != 0:
            measurements.append(
                Measurement(
                    range_m=9.0 + 0.35 * time_s + rng.uniform(-0.08, 0.08),
                    velocity_mps=0.35 + rng.uniform(-0.04, 0.04),
                    angle_deg=8.0 - 0.55 * time_s + rng.uniform(-0.3, 0.3),
                    snr_db=13.5 + rng.uniform(-1.0, 1.0),
                )
            )
        if seq % 9 == 0:
            measurements.append(
                Measurement(
                    range_m=rng.uniform(2.0, 50.0),
                    velocity_mps=rng.uniform(-2.0, 2.0),
                    angle_deg=rng.uniform(-35.0, 35.0),
                    snr_db=rng.uniform(3.0, 7.0),
                )
            )

        yield seq, measurements[:MAX_TARGETS]


# --------------------------------------------------------------------------- #
# Custom scenario configuration (JSON-driven simulation)
# --------------------------------------------------------------------------- #
import json


@dataclass
class TargetSpec:
    """One moving target in a scenario file."""
    range_start_m: float
    velocity_mps: float
    angle_start_deg: float
    angle_rate_dps: float = 0.0
    snr_db: float = 15.0
    start_frame: int = 0
    dropout_every: int = 0
    noise_range: float = 0.08
    noise_velocity: float = 0.04
    noise_angle: float = 0.3
    noise_snr: float = 1.0


@dataclass
class ClutterSpec:
    """Random clutter (false alarms) injected periodically."""
    every: int = 0
    range_min: float = 2.0
    range_max: float = 50.0
    velocity_min: float = -2.0
    velocity_max: float = 2.0
    angle_min: float = -35.0
    angle_max: float = 35.0
    snr_min: float = 3.0
    snr_max: float = 7.0


@dataclass
class ScenarioConfig:
    """Full scenario configuration loaded from JSON."""
    name: str
    description: str
    frame_count: int
    frame_interval_s: float
    targets: list[TargetSpec]
    clutter: ClutterSpec

    @classmethod
    def from_json(cls, path: Path) -> "ScenarioConfig":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        targets = [
            TargetSpec(
                range_start_m=t["range_start_m"],
                velocity_mps=t["velocity_mps"],
                angle_start_deg=t.get("angle_start_deg", 0.0),
                angle_rate_dps=t.get("angle_rate_dps", 0.0),
                snr_db=t.get("snr_db", 15.0),
                start_frame=t.get("start_frame", 0),
                dropout_every=t.get("dropout_every", 0),
                noise_range=t.get("noise", {}).get("range", 0.08),
                noise_velocity=t.get("noise", {}).get("velocity", 0.04),
                noise_angle=t.get("noise", {}).get("angle", 0.3),
                noise_snr=t.get("noise", {}).get("snr", 1.0),
            )
            for t in data.get("targets", [])
        ]
        cl = data.get("clutter", {})
        clutter = ClutterSpec(
            every=cl.get("every", 0),
            range_min=cl.get("range", [2.0, 50.0])[0],
            range_max=cl.get("range", [2.0, 50.0])[1],
            velocity_min=cl.get("velocity", [-2.0, 2.0])[0],
            velocity_max=cl.get("velocity", [-2.0, 2.0])[1],
            angle_min=cl.get("angle", [-35.0, 35.0])[0],
            angle_max=cl.get("angle", [-35.0, 35.0])[1],
            snr_min=cl.get("snr", [3.0, 7.0])[0],
            snr_max=cl.get("snr", [3.0, 7.0])[1],
        )
        return cls(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            frame_count=data.get("frame_count", 120),
            frame_interval_s=data.get("frame_interval_s", 0.08),
            targets=targets,
            clutter=clutter,
        )


def generate_scenario_from_config(path: Path) -> Iterator[tuple[int, list[Measurement]]]:
    """Generate radar measurements from a JSON scenario file.

    Scenario JSON schema (see scenarios/*.json for examples):
    {
      "name": "...",
      "description": "...",
      "frame_count": 200,
      "frame_interval_s": 0.08,
      "targets": [
        {
          "range_start_m": 18.0,
          "velocity_mps": -0.55,
          "angle_start_deg": -11.0,
          "angle_rate_dps": 1.125,
          "snr_db": 17.0,
          "start_frame": 0,
          "dropout_every": 17,
          "noise": {"range": 0.08, "velocity": 0.04, "angle": 0.3, "snr": 1.2}
        }
      ],
      "clutter": {
        "every": 9,
        "range": [2.0, 50.0],
        "velocity": [-2.0, 2.0],
        "angle": [-35.0, 35.0],
        "snr": [3.0, 7.0]
      }
    }
    """
    cfg = ScenarioConfig.from_json(path)
    yield from generate_from_config(cfg)


def generate_from_config(cfg: ScenarioConfig) -> Iterator[tuple[int, list[Measurement]]]:
    """Generate radar measurements from a ScenarioConfig object."""
    for seq in range(cfg.frame_count):
        rng = random.Random(2026 + seq)
        time_s = seq * cfg.frame_interval_s
        measurements: list[Measurement] = []

        for t in cfg.targets:
            if seq < t.start_frame:
                continue
            if t.dropout_every and seq % t.dropout_every == 0:
                continue  # simulated missed detection
            measurements.append(
                Measurement(
                    range_m=t.range_start_m + t.velocity_mps * time_s + rng.uniform(-t.noise_range, t.noise_range),
                    velocity_mps=t.velocity_mps + rng.uniform(-t.noise_velocity, t.noise_velocity),
                    angle_deg=t.angle_start_deg + t.angle_rate_dps * time_s + rng.uniform(-t.noise_angle, t.noise_angle),
                    snr_db=t.snr_db + rng.uniform(-t.noise_snr, t.noise_snr),
                )
            )

        if cfg.clutter.every and seq % cfg.clutter.every == 0:
            measurements.append(
                Measurement(
                    range_m=rng.uniform(cfg.clutter.range_min, cfg.clutter.range_max),
                    velocity_mps=rng.uniform(cfg.clutter.velocity_min, cfg.clutter.velocity_max),
                    angle_deg=rng.uniform(cfg.clutter.angle_min, cfg.clutter.angle_max),
                    snr_db=rng.uniform(cfg.clutter.snr_min, cfg.clutter.snr_max),
                )
            )

        yield seq, measurements[:MAX_TARGETS]


def write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["seq", "kind", "id", "range_m", "velocity_mps", "angle_deg", "snr_db"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_measurements_csv(path: Path) -> Iterator[tuple[int, list[Measurement]]]:
    frames: dict[int, list[Measurement]] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("kind") != "measurement":
                continue
            seq = int(row["seq"])
            frames.setdefault(seq, []).append(
                Measurement(
                    range_m=float(row["range_m"]),
                    velocity_mps=float(row["velocity_mps"]),
                    angle_deg=float(row["angle_deg"]),
                    snr_db=float(row["snr_db"]),
                )
            )
    for seq in sorted(frames):
        yield seq, frames[seq]


def ascii_map(tracks: Sequence[Track], width: int = 41) -> str:
    if not tracks:
        return "no stable target"

    line = [" "] * width
    center = width // 2
    line[center] = "|"
    for track in tracks:
        index = int(round(center + track.angle_deg / 45.0 * center))
        if 0 <= index < width:
            line[index] = str(track.track_id % 10)
    labels = ", ".join(
        f"#{track.track_id}: {track.range_m:05.2f}m {track.velocity_mps:+.2f}m/s {track.angle_deg:+.1f}deg"
        for track in tracks
    )
    return f"[{''.join(line)}] {labels}"


def run_frames(frames: Iterable[tuple[int, list[Measurement]]], csv_path: Path | None, show_ascii: bool) -> None:
    tracker = RadarTracker()
    csv_rows: list[dict[str, object]] = []

    for seq, measurements in frames:
        packet = encode_frame(seq, measurements)
        parsed = list(parse_stream(b"\x00\x13" + packet + b"\x99"))
        if not parsed:
            raise RuntimeError("encoded frame could not be parsed")
        _, decoded = parsed[0]
        tracks = tracker.update(decoded)

        for measurement in decoded:
            csv_rows.append(
                {
                    "seq": seq,
                    "kind": "measurement",
                    "id": "",
                    "range_m": f"{measurement.range_m:.2f}",
                    "velocity_mps": f"{measurement.velocity_mps:.2f}",
                    "angle_deg": f"{measurement.angle_deg:.2f}",
                    "snr_db": f"{measurement.snr_db:.2f}",
                }
            )
        for track in tracks:
            csv_rows.append(
                {
                    "seq": seq,
                    "kind": "track",
                    "id": track.track_id,
                    "range_m": f"{track.range_m:.2f}",
                    "velocity_mps": f"{track.velocity_mps:.2f}",
                    "angle_deg": f"{track.angle_deg:.2f}",
                    "snr_db": f"{track.confidence:.2f}",
                }
            )
        if show_ascii and seq % 5 == 0:
            print(f"frame {seq:03d} {ascii_map(tracks)}")

    if csv_path is not None:
        write_csv(csv_path, csv_rows)
        print(f"wrote {csv_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="STM32 mmWave radar target detection demo")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true", help="generate deterministic radar measurements")
    mode.add_argument("--scenario", type=Path, help="generate measurements from a JSON scenario file")
    mode.add_argument("--replay", type=Path, help="replay a measurement CSV")
    parser.add_argument("--frames", type=int, default=80, help="number of simulated frames (only used with --simulate)")
    parser.add_argument("--csv", type=Path, help="optional CSV output path")
    parser.add_argument("--ascii-map", action="store_true", help="print a compact angle/range display")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.simulate:
        run_frames(generate_scenario(args.frames), args.csv, args.ascii_map)
    elif args.scenario:
        run_frames(generate_scenario_from_config(args.scenario), args.csv, args.ascii_map)
    else:
        run_frames(read_measurements_csv(args.replay), args.csv, args.ascii_map)


if __name__ == "__main__":
    main()
