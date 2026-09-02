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

    def test_lifecycle_capture_starts_and_stops_exactly_once(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=False)
        mock_tk, mock_root, _ = _make_mock_tk()

        mock_capture = MagicMock()
        mock_capture.error.return_value = None
        mock_capture.drain_after.return_value = []

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with patch("lavatune.window.AudioCapture", return_value=mock_capture):
                def fake_mainloop():
                    self.assertEqual(mock_root.after.call_count, 1)
                    callback = mock_root.after.call_args[0][1]
                    callback()
                    companion.close()

                mock_root.mainloop.side_effect = fake_mainloop
                result = companion.run()
                self.assertEqual(result, 0)

        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

        companion.close()
        mock_capture.stop.assert_called_once()

    def test_duplicate_close_events_are_harmless(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=True)
        mock_tk, mock_root, _ = _make_mock_tk()

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            def fake_mainloop():
                companion.close()
                companion.close()
                companion.close()

            mock_root.mainloop.side_effect = fake_mainloop
            result = companion.run()
            self.assertEqual(result, 0)

    def test_keyboard_interrupt_cleans_up(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=False)
        mock_tk, mock_root, _ = _make_mock_tk()
        mock_capture = MagicMock()
        mock_capture.error.return_value = None

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with patch("lavatune.window.AudioCapture", return_value=mock_capture):
                mock_root.mainloop.side_effect = KeyboardInterrupt
                result = companion.run()
                self.assertEqual(result, 0)

        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

    def test_tk_callback_exception_propagates_nonzero(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=False)
        mock_tk, mock_root, _ = _make_mock_tk()
        mock_capture = MagicMock()
        mock_capture.error.return_value = None

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with patch("lavatune.window.AudioCapture", return_value=mock_capture):
                def fake_mainloop():
                    callback = mock_root.after.call_args[0][1]
                    with patch.object(companion, "_draw", side_effect=ValueError("draw failure")):
                        callback()

                mock_root.mainloop.side_effect = fake_mainloop
                with self.assertRaises(ValueError) as ctx:
                    companion.run()
                self.assertIn("draw failure", str(ctx.exception))

        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

    def test_runtime_audio_error_propagates(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=False)
        mock_tk, mock_root, _ = _make_mock_tk()
        mock_capture = MagicMock()
        mock_capture.error.return_value = "pw-cat disconnected unexpectedly"
        mock_capture.drain_after.return_value = []

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with patch("lavatune.window.AudioCapture", return_value=mock_capture):
                def fake_mainloop():
                    callback = mock_root.after.call_args[0][1]
                    callback()

                mock_root.mainloop.side_effect = fake_mainloop
                with self.assertRaises(RuntimeError) as ctx:
                    companion.run()
                self.assertIn("pw-cat disconnected unexpectedly", str(ctx.exception))

        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

    def test_partial_setup_initialization_failure_cleans_up(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=False)
        mock_tk, mock_root, _ = _make_mock_tk()
        mock_capture = MagicMock()

        mock_root.geometry.side_effect = RuntimeError("Geometry error")

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            with patch("lavatune.window.AudioCapture", return_value=mock_capture):
                with self.assertRaises(RuntimeError) as ctx:
                    companion.run()
                self.assertIn("Geometry error", str(ctx.exception))

        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

    def test_resize_events_clamp_dimensions(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=True)
        mock_tk, mock_root, mock_canvas = _make_mock_tk()
        mock_canvas.winfo_width.return_value = 0
        mock_canvas.winfo_height.return_value = 0

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            def fake_mainloop():
                callback = mock_root.after.call_args[0][1]
                callback()
                companion.close()

            mock_root.mainloop.side_effect = fake_mainloop
            result = companion.run()
            self.assertEqual(result, 0)
            self.assertEqual(companion.field.w, 10)
            self.assertEqual(companion.field.h, 6)

    def test_demo_mode_lifecycle(self) -> None:
        config = AppConfig()
        companion = WindowCompanion(config, demo=True)
        mock_tk, mock_root, _ = _make_mock_tk()

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            def fake_mainloop():
                callback = mock_root.after.call_args[0][1]
                callback()
                companion.close()

            mock_root.mainloop.side_effect = fake_mainloop
            result = companion.run()
            self.assertEqual(result, 0)
            self.assertTrue(companion._closed)

    def test_config_propagation(self) -> None:
        config = AppConfig()
        config.listening_context = "podcast"
        config.profile = "responsive"
        config.fps = 45

        companion = WindowCompanion(config, demo=True)
        mock_tk, mock_root, _ = _make_mock_tk()

        with patch.dict("sys.modules", {"tkinter": mock_tk}):
            def fake_mainloop():
                callback = mock_root.after.call_args[0][1]
                with patch.object(companion.field, "step") as mock_step:
                    callback()
                    mock_step.assert_called_once()
                    args, _ = mock_step.call_args
                    self.assertEqual(args[1], "podcast")
                    self.assertEqual(args[2], "responsive")
                companion.close()

            mock_root.mainloop.side_effect = fake_mainloop
            companion.run()
            after_calls = mock_root.after.call_args_list
            self.assertEqual(after_calls[1][0][0], 22)


def _make_mock_tk():
    import tkinter
    mock_tk = MagicMock()
    mock_tk.TclError = tkinter.TclError
    mock_root = MagicMock()
    mock_canvas = MagicMock()
    mock_canvas.winfo_width.return_value = 600
    mock_canvas.winfo_height.return_value = 420
    mock_tk.Tk.return_value = mock_root
    mock_tk.Canvas.return_value = mock_canvas
    mock_tk.BOTH = "both"
    return mock_tk, mock_root, mock_canvas


if __name__ == "__main__":
    unittest.main()
