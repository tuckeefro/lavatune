from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from lavatune import __version__
from lavatune.__main__ import build_parser, main
from lavatune.config import AppConfig


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

    def test_trace_output_requires_a_one_shot_trace(self) -> None:
        errors = io.StringIO()
        with (
            patch("sys.argv", ["lavatune", "--trace-output", "/tmp/trace.json"]),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("requires --trace-once", errors.getvalue())

    def test_canvas_renderer_and_one_shot_trace_are_incompatible(self) -> None:
        errors = io.StringIO()
        with (
            patch(
                "sys.argv",
                ["lavatune", "--renderer", "canvas", "--trace-once", "20"],
            ),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cannot be used with the canvas renderer", errors.getvalue())

    def test_renderer_canvas_routes_to_the_opt_in_companion(self) -> None:
        with (
            patch("sys.argv", ["lavatune", "--renderer", "canvas", "--demo"]),
            patch("lavatune.__main__.load_config", return_value=AppConfig()),
            patch("lavatune.canvas.run_canvas", return_value=23) as run_canvas,
        ):
            self.assertEqual(main(), 23)

        config, demo = run_canvas.call_args.args
        self.assertEqual(config.render.renderer, "canvas")
        self.assertTrue(demo)


if __name__ == "__main__":
    unittest.main()
