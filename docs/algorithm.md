# Target Detection Algorithm

This demo keeps the embedded algorithm deliberately lightweight so it can run on STM32-class MCUs without floating-point heavy dependencies.

## Pipeline

1. **Frame validation**: accept only CRC-valid radar frames.
2. **Measurement gating**: reject impossible range values and low-SNR clutter.
3. **Track association**: match each measurement to the closest active track.
4. **Smoothing**: update range, velocity, angle, and confidence with exponential smoothing.
5. **Track lifecycle**: remove tracks after several missed frames.
6. **Stable output**: expose tracks only after enough age and confidence.

## Measurement Gate

Current defaults:

- Range: `0.3m` to `80.0m`
- SNR: at least `8.0dB`
- Association score: less than `2.5`

The distance score mixes range, velocity, and angle:

```text
score = abs(range_error)
      + 0.4 * abs(velocity_error)
      + 0.05 * abs(angle_error)
```

This is not meant to replace EKF/UKF tracking in a production radar stack. It is a compact baseline that makes noisy target detection explainable and easy to tune during hardware bring-up.

## Tuning Notes

- Increase the SNR gate for indoor environments with strong multipath.
- Increase the missed-frame tolerance if the radar module frequently drops targets.
- Lower the association score if crossing targets swap IDs too often.
- Replace exponential smoothing with alpha-beta filtering when the target dynamics are faster.
