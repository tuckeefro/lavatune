from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lavatune.audio import AudioFrame, CapturedAudioFrame
from lavatune.config import AppConfig
from lavatune.trace import TraceRecorder, capture_trace
from lavatune.motion import MotionAnalyzer, capture_motion_analysis


class FakeCapture:
    def __init__(self, _config) -> None:
        self.started = False
        self.stopped = False
        self.frames = [
            CapturedAudioFrame(
                1,
                AudioFrame(0.20, [0.12] * 8, 0.08, 0.10, 10.0),
            ),
            CapturedAudioFrame(
                2,
                AudioFrame(0.48, [0.55] * 8, 0.42, 0.18, 10.12),
            ),
        ]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def drain_after(self, sequence: int) -> list[CapturedAudioFrame]:
        return [frame for frame in self.frames if frame.sequence > sequence]

    def error(self) -> None:
        return None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TraceTests(unittest.TestCase):
    def test_recorder_keeps_feature_values_not_audio(self) -> None:
        recorder = TraceRecorder(AppConfig())
        recorder.observe(AudioFrame(0.20, [0.10] * 8, 0.04, 0.08, 1.0))
        recorder.observe(AudioFrame(0.42, [0.50] * 8, 0.32, 0.18, 1.05))
        recorder.observe(AudioFrame(0.55, [0.66] * 8, 0.46, 0.20, 1.12))
        payload = recorder.payload()

        self.assertEqual(recorder.frames, 3)
        self.assertEqual(len(payload["samples"]), 2)
        self.assertIn("rupture", payload["peaks"])
        self.assertNotIn("pcm", payload["samples"][0])
        self.assertNotIn("waveform", payload["samples"][0])

    def test_one_shot_trace_stops_capture_and_writes_a_bounded_report(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "track.json"
            result = capture_trace(
                AppConfig(),
                0.01,
                output,
                capture_factory=FakeCapture,
                clock=clock,
                sleeper=clock.sleep,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.path, output)
        self.assertEqual(result.frames, 2)
        self.assertEqual(result.samples, 2)
        self.assertEqual(payload["format"], "lavatune-feature-trace-v1")
        self.assertEqual(payload["captured_analysis_frames"], 2)


class MotionAnalysisTests(unittest.TestCase):
    def test_motion_analyzer_keeps_derived_body_telemetry_without_pcm(self) -> None:
        analyzer = MotionAnalyzer(AppConfig())
        analyzer.observe(AudioFrame(0.30, [0.12] * 8, 0.08, 0.10, 1.0))
        analyzer.observe(AudioFrame(0.58, [0.72] * 8, 0.48, 0.22, 1.05))
        payload = analyzer.payload()

        self.assertEqual(payload["format"], "lavatune-motion-analysis-v1")
        self.assertIn("summary", payload)
        self.assertIn("bodies", payload["samples"][0])
        self.assertIn("float_drive", payload["samples"][0]["bodies"][0])
        self.assertIn("chop_drive", payload["samples"][0]["bodies"][0])
        self.assertNotIn("pcm", payload)

    def test_live_motion_analysis_stops_capture_and_writes_bounded_report(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "motion.json"
            result = capture_motion_analysis(
                AppConfig(),
                0.01,
                output,
                capture_factory=FakeCapture,
                clock=clock,
                sleeper=clock.sleep,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.path, output)
        self.assertEqual(result.frames, 2)
        self.assertEqual(result.samples, 2)
        self.assertIn("Motion analysis", result.summary)
        self.assertEqual(payload["captured_analysis_frames"], 2)


if __name__ == "__main__":
    unittest.main()
