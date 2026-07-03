import unittest

from host.radar_demo import (
    Measurement,
    RadarTracker,
    decode_frame,
    encode_frame,
    generate_scenario,
    parse_stream,
)


class RadarDemoTests(unittest.TestCase):
    def test_frame_round_trip(self) -> None:
        measurements = [
            Measurement(range_m=12.34, velocity_mps=-0.8, angle_deg=-5.3, snr_db=18.0),
            Measurement(range_m=7.2, velocity_mps=0.4, angle_deg=11.1, snr_db=12.5),
        ]

        raw = encode_frame(7, measurements)
        seq, decoded = decode_frame(raw)

        self.assertEqual(seq, 7)
        self.assertEqual(len(decoded), 2)
        self.assertAlmostEqual(decoded[0].range_m, 12.34, places=2)
        self.assertAlmostEqual(decoded[0].velocity_mps, -0.8, places=2)
        self.assertAlmostEqual(decoded[1].angle_deg, 11.1, places=2)

    def test_stream_parser_recovers_from_noise(self) -> None:
        raw = encode_frame(3, [Measurement(10.0, 0.2, 4.0, 15.0)])
        frames = list(parse_stream(b"\x00\xFF" + raw + b"\x13\x37"))

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], 3)
        self.assertEqual(len(frames[0][1]), 1)

    def test_tracker_filters_low_snr_clutter(self) -> None:
        tracker = RadarTracker()
        for _ in range(5):
            stable = tracker.update(
                [
                    Measurement(12.0, -0.4, 2.0, 16.0),
                    Measurement(30.0, 1.0, -20.0, 5.0),
                ]
            )

        self.assertEqual(len(stable), 1)
        self.assertAlmostEqual(stable[0].range_m, 12.0, places=1)

    def test_scenario_produces_tracks(self) -> None:
        tracker = RadarTracker()
        stable_count = 0
        for _, measurements in generate_scenario(40):
            stable_count += len(tracker.update(measurements))

        self.assertGreater(stable_count, 0)


if __name__ == "__main__":
    unittest.main()
