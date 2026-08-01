from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from lavatune import __version__
from lavatune.__main__ import build_parser, main


class CliTests(unittest.TestCase):
    def test_version_comes_from_package_version(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"lavatune {__version__}")

    def test_audio_probe_option_is_reserved_for_doctor(self) -> None:
        errors = io.StringIO()
        with (
            patch("sys.argv", ["lavatune", "--no-audio-probe"]),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("requires --doctor", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
