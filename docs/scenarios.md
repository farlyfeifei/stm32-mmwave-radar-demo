# Custom Scenario Configuration

The radar demo supports JSON-driven custom simulation scenarios. Instead of the
hardcoded `generate_scenario`, you can describe your own targets, trajectories,
clutter, and dropouts in a JSON file.

## Quick Start

```powershell
# Run a preset scenario with the ASCII viewer
python host/radar_demo.py --scenario scenarios/formation.json --ascii-map

# Run a preset scenario with the PyQt5 viewer
python host/radar_viewer.py --scenario scenarios/crossing.json

# Generate a CSV from a scenario for replay later
python host/radar_demo.py --scenario scenarios/evasive.json --csv data/evasive.csv
```

## JSON Schema

```json
{
  "name": "场景名称",
  "description": "场景描述",
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
```

## Field Reference

### Top-level

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | filename | Display name |
| `description` | string | "" | Human-readable description |
| `frame_count` | int | 120 | Total frames to generate |
| `frame_interval_s` | float | 0.08 | Time between frames (determines target motion) |
| `targets` | array | [] | List of target specs |
| `clutter` | object | — | Clutter injection config |

### Target spec

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `range_start_m` | float | required | Initial range (meters) |
| `velocity_mps` | float | required | Radial velocity (m/s, negative = approaching) |
| `angle_start_deg` | float | 0 | Initial azimuth (degrees) |
| `angle_rate_dps` | float | 0 | Angular velocity (deg/s) |
| `snr_db` | float | 15 | Mean SNR (dB) |
| `start_frame` | int | 0 | Frame when target appears |
| `dropout_every` | int | 0 | Inject a missed detection every N frames (0 = never) |
| `noise.range` | float | 0.08 | Range jitter (meters, ±uniform) |
| `noise.velocity` | float | 0.04 | Velocity jitter (m/s) |
| `noise.angle` | float | 0.3 | Angle jitter (degrees) |
| `noise.snr` | float | 1.0 | SNR jitter (dB) |

### Clutter spec

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `every` | int | 0 | Inject one clutter point every N frames (0 = none) |
| `range` | [min, max] | [2.0, 50.0] | Clutter range bounds (meters) |
| `velocity` | [min, max] | [-2.0, 2.0] | Clutter velocity bounds (m/s) |
| `angle` | [min, max] | [-35.0, 35.0] | Clutter angle bounds (degrees) |
| `snr` | [min, max] | [3.0, 7.0] | Clutter SNR bounds (dB, kept low to test filtering) |

## Preset Scenarios

| File | Targets | Clutter | Tests |
|------|---------|---------|-------|
| `crossing.json` | 2 | medium | Nearest-neighbor association under crossing trajectories |
| `formation.json` | 3 | light | Track separation and ID retention for close targets |
| `evasive.json` | 1 | none | Tracker response to a single maneuvering target |
| `clutter_storm.json` | 1 | heavy (every 4 frames) | SNR gating and track robustness in dense false alarms |

## Creating Your Own Scenario

1. Copy any preset from `scenarios/` as a starting point.
2. Edit the JSON — add targets, adjust velocities, change clutter density.
3. Run it:

```powershell
python host/radar_viewer.py --scenario scenarios/my_scenario.json
```

The scenario system is designed for hardware-in-the-loop preparation: tune the
scenario to match your expected radar environment, validate the tracker response,
then port the same C tracker to STM32 and feed it live UART data.
