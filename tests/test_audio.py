from __future__ import annotations

import subprocess
import unittest

from lavatune.audio import AudioCapture
from lavatune.config import AudioConfig


def capture_shell(backend: str = "pipewire", source: str | None = None) -> AudioCapture:
    capture = AudioCapture.__new__(AudioCapture)
    capture.backend = backend
    capture.source = source
    capture.config = AudioConfig()
    capture._proc = None
    capture._stderr_tail = bytearray()
    return capture


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
