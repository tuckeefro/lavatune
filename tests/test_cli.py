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

    def test_renderer_kitty_routes_to_terminal_pixel_companion(self) -> None:
        with (
            patch("sys.argv", ["lavatune", "--renderer", "kitty", "--demo"]),
            patch("lavatune.__main__.load_config", return_value=AppConfig()),
            patch("lavatune.kitty.run_kitty", return_value=29) as run_kitty,
        ):
            self.assertEqual(main(), 29)

        config, demo = run_kitty.call_args.args
        self.assertEqual(config.render.renderer, "kitty")
        self.assertTrue(demo)

    def test_window_flag_routes_to_standalone_window(self) -> None:
        with (
            patch("sys.argv", ["lavatune", "--window", "--demo"]),
            patch("lavatune.__main__.load_config", return_value=AppConfig()),
            patch("lavatune.window.run_window", return_value=42) as run_window,
        ):
            self.assertEqual(main(), 42)

        config, demo = run_window.call_args.args
        self.assertEqual(config.render.renderer, "window")
        self.assertTrue(demo)

    def test_window_and_canvas_flags_cannot_be_combined(self) -> None:
        errors = io.StringIO()
        with (
            patch("sys.argv", ["lavatune", "--window", "--canvas"]),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--canvas and --window cannot be combined", errors.getvalue())

    def test_window_renderer_and_trace_once_are_incompatible(self) -> None:
        errors = io.StringIO()
        with (
            patch("sys.argv", ["lavatune", "--window", "--trace-once", "10"]),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cannot be used with the window renderer", errors.getvalue())

    def test_kitty_renderer_and_trace_once_are_incompatible(self) -> None:
        errors = io.StringIO()
        with (
            patch(
                "sys.argv",
                ["lavatune", "--renderer", "kitty", "--trace-once", "10"],
            ),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cannot be used with the kitty renderer", errors.getvalue())

    def test_list_backends_includes_sox(self) -> None:
        backend_choices = [b for b in build_parser()._actions if b.dest == "backend"][0].choices
        self.assertIn("sox", backend_choices)

    def test_main_list_backends_outputs_sox(self) -> None:
        output = io.StringIO()
        with patch("sys.argv", ["lavatune", "--list-backends"]), redirect_stdout(output):
            code = main()

        self.assertEqual(code, 0)
        self.assertIn("sox", output.getvalue().splitlines())


if __name__ == "__main__":
    unittest.main()
