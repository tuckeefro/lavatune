from __future__ import annotations

import unittest
from unittest.mock import patch

from lavatune.audio import AudioFrame
from lavatune.config import load_config
from lavatune.doctor import format_report, inspect_environment


class FakeCapture:
    def __init__(self, _config) -> None:
        self.stopped = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True

    def frames_received(self) -> int:
        return 1

    def latest(self) -> AudioFrame:
        return AudioFrame(0.125, [0.0] * 8, 0.0, 0.0, 0.0)

    def error(self) -> str | None:
        return None

    def status(self) -> str:
        return "pipewire:monitor:atlas"


class DoctorTests(unittest.TestCase):
    @patch("lavatune.doctor._terminal_color_count", return_value=256)
    @patch("lavatune.doctor.platform.system", return_value="Linux")
    @patch("lavatune.doctor.shutil.which")
    def test_healthy_environment_and_live_probe_pass(self, which, _system, _colors) -> None:
        which.side_effect = lambda binary: f"/usr/bin/{binary}" if binary in {"pw-cat", "playerctl"} else None

        report = inspect_environment(
            load_config(None, None),
            capture_factory=FakeCapture,
        )

        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.errors, 0)
        self.assertIn("received PCM", format_report(report))

    @patch("lavatune.doctor._terminal_color_count", return_value=8)
    @patch("lavatune.doctor.platform.system", return_value="Linux")
    @patch("lavatune.doctor.shutil.which", return_value=None)
    def test_missing_optional_and_required_tools_are_distinguished(self, _which, _system, _colors) -> None:
        report = inspect_environment(load_config(None, None), probe_audio=False)

        self.assertEqual(report.exit_code, 1)
        self.assertEqual(report.errors, 1)
        self.assertEqual(report.warnings, 2)
        self.assertIn("Install pw-cat, parec, or ffmpeg", format_report(report))

    @patch("lavatune.doctor._terminal_color_count", return_value=256)
    @patch("lavatune.doctor.platform.system", return_value="Linux")
    @patch("lavatune.doctor.shutil.which")
    def test_static_doctor_marks_audio_probe_as_skipped(self, which, _system, _colors) -> None:
        which.side_effect = lambda binary: f"/usr/bin/{binary}" if binary == "pw-cat" else None

        report = inspect_environment(load_config(None, None), probe_audio=False)

        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.checks[-1].status, "skip")


if __name__ == "__main__":
    unittest.main()
