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


class FakeNoFramesCapture:
    def __init__(self, _config) -> None:
        self.stopped = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True

    def frames_received(self) -> int:
        return 0

    def latest(self) -> AudioFrame:
        return AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 0.0)

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

    @patch("lavatune.doctor._terminal_color_count", return_value=256)
    @patch("lavatune.doctor.platform.system", return_value="Linux")
    @patch("lavatune.doctor.shutil.which")
    def test_missing_audio_frames_are_reported_as_error(self, which, _system, _colors) -> None:
        which.side_effect = lambda binary: f"/usr/bin/{binary}" if binary == "pw-cat" else None

        report = inspect_environment(
            load_config(None, None),
            probe_audio=True,
            probe_timeout=0.2,
            capture_factory=FakeNoFramesCapture,
        )

        self.assertEqual(report.errors, 1)
        self.assertIn("no PCM arrived within 0.2s", format_report(report))

    @patch("lavatune.doctor._terminal_color_count", return_value=256)
    @patch("lavatune.doctor.platform.system", return_value="Windows")
    @patch("lavatune.doctor.shutil.which")
    def test_unsupported_environment_reports_skipped_audio_probe(self, which, _system, _colors) -> None:
        which.side_effect = lambda binary: f"/usr/bin/{binary}" if binary == "ffmpeg" else None
        probe_used = {"called": False}

        def _never_called(_: object) -> object:
            probe_used["called"] = True
            raise AssertionError("audio probe should be skipped on unsupported platforms")

        report = inspect_environment(
            load_config(None, None),
            probe_audio=True,
            capture_factory=_never_called,
        )

        self.assertFalse(probe_used["called"])
        self.assertEqual(report.errors, 1)
        self.assertEqual(report.checks[-1].status, "skip")
        self.assertIn("audio probe is not supported on Windows", format_report(report))


if __name__ == "__main__":
    unittest.main()
