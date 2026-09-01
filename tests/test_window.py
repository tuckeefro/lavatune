"""Tests for the standalone floating window renderer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from lavatune.config import AppConfig
from lavatune.window import WindowCompanion, _flatten_points, _rgb_to_hex, run_window


class WindowRendererTests(unittest.TestCase):
    def test_rgb_to_hex_formatting(self) -> None:
        self.assertEqual(_rgb_to_hex((0.0, 0.0, 0.0)), "#000000")
        self.assertEqual(_rgb_to_hex((1.0, 1.0, 1.0)), "#ffffff")
        self.assertEqual(_rgb_to_hex((0.5, 0.25, 0.75)), "#8040bf")
        self.assertEqual(_rgb_to_hex((-0.1, 1.2, 0.5)), "#00ff80")

    def test_flatten_points(self) -> None:
        pts = ((10.0, 20.0), (30.0, 40.0), (50.0, 60.0))
        self.assertEqual(_flatten_points(pts), [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])

    def test_missing_tkinter_raises_runtime_error(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=True)
        with patch.dict("sys.modules", {"tkinter": None}):
            with self.assertRaises(RuntimeError) as ctx:
                companion.run()
            self.assertIn("tkinter", str(ctx.exception).lower())

    def test_tcl_error_raises_runtime_error(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=True)
        mock_tk = MagicMock()
        import tkinter
        mock_tk.TclError = tkinter.TclError
        mock_tk.Tk.side_effect = tkinter.TclError("no display name and no $DISPLAY environment variable")
        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with self.assertRaises(RuntimeError) as ctx:
                companion.run()
            self.assertIn("failed to initialize gui display", str(ctx.exception).lower())

    def test_run_window_invokes_companion(self) -> None:
        config = AppConfig()
        with patch.object(WindowCompanion, "run", return_value=0) as mock_run:
            self.assertEqual(run_window(config, demo=True), 0)
            mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
