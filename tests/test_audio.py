from __future__ import annotations

import math
import os
import select
import struct
import subprocess
import unittest
from collections import deque
from unittest.mock import patch

from lavatune.audio import AudioCapture, AudioFrame
from lavatune.config import AudioConfig


def capture_shell(backend: str = "pipewire", source: str | None = None) -> AudioCapture:
    capture = AudioCapture.__new__(AudioCapture)
    capture.backend = backend
    capture.source = source
    capture.config = AudioConfig()
    capture._proc = None
    capture._stderr_tail = bytearray()
    return capture


def atlas_analyzer() -> AudioCapture:
    capture = AudioCapture.__new__(AudioCapture)
    capture.config = AudioConfig(analysis="atlas", sample_rate=16000, frame_size=1024)
    capture._atlas_history = deque([0.0] * 8, maxlen=8)
    capture._atlas_last = 0.0
    capture._atlas_lowpass = 0.0
    capture._atlas_midpass = 0.0
    capture._level_floor = 0.01
    capture._level_ceiling = 0.18
    capture._level_drive = 0.0
    return capture


def sine_chunk(frequency: float, sample_rate: int = 16000, size: int = 1024) -> bytes:
    samples = [
        int(math.sin(math.tau * frequency * index / sample_rate) * 12000)
        for index in range(size)
    ]
    return struct.pack("<" + "h" * size, *samples)


class FakeProcess:
    def __init__(self, timeout_once: bool = False) -> None:
        self.timeout_once = timeout_once
        self.terminated = False
        self.killed = False
        self.waits = 0

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float):
        self.waits += 1
        if self.timeout_once and self.waits == 1:
            raise subprocess.TimeoutExpired("audio-backend", timeout)
        return 0


class AudioProcessTests(unittest.TestCase):
    def test_capture_queue_is_bounded_sequenced_and_wakes_a_waiter(self) -> None:
        with patch("lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"):
            capture = AudioCapture(AudioConfig())
        try:
            for sequence in range(12):
                capture._publish(
                    AudioFrame(0.1, [0.1] * 8, 0.0, 0.0, float(sequence + 1)),
                    0.001,
                )

            readable, _, _ = select.select([capture.fileno()], [], [], 0.05)
            frames = capture.drain_after(0)

            self.assertEqual(readable, [capture.fileno()])
            self.assertEqual(len(frames), 8)
            self.assertEqual([item.sequence for item in frames], list(range(5, 13)))
            frames_seen, analysis_seconds = capture.analysis_metrics()
            self.assertEqual(frames_seen, 12)
            self.assertAlmostEqual(analysis_seconds, 0.012)
            capture.consume_signal()
            with self.assertRaises(BlockingIOError):
                os.read(capture.fileno(), 1)
        finally:
            capture.stop()

    def test_atlas_single_pass_analysis_retains_coarse_tonal_contrast(self) -> None:
        low_capture = atlas_analyzer()
        high_capture = atlas_analyzer()

        for _ in range(4):
            low = low_capture._analyze_atlas(struct.unpack("<1024h", sine_chunk(120.0)))
            high = high_capture._analyze_atlas(struct.unpack("<1024h", sine_chunk(4200.0)))

        self.assertGreater(sum(low.bands[:3]), sum(low.bands[5:]) * 1.35)
        self.assertGreater(sum(high.bands[5:]), sum(high.bands[:3]) * 1.35)

    def test_source_is_one_subprocess_argument(self) -> None:
        source = "monitor; touch /tmp/not-executed"
        capture = capture_shell(source=source)

        command = capture._command()

        self.assertEqual(command[command.index("--target") + 1], source)

    def test_backend_status_and_diagnostics_are_sanitized(self) -> None:
        capture = capture_shell(source="monitor\x1b]0;spoof\x07")
        capture._stderr_tail.extend(b"failed\x1b]0;spoof\x07")

        self.assertEqual(capture.status(), "pipewire:monitor ]0;spoof :atlas")
        self.assertEqual(capture._backend_message(), "failed ]0;spoof")

    def test_stubborn_backend_is_killed_and_reaped(self) -> None:
        capture = capture_shell()
        process = FakeProcess(timeout_once=True)
        capture._proc = process

        capture._terminate_process()

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.waits, 2)


if __name__ == "__main__":
    unittest.main()
