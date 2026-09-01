"""Standalone floating window renderer for Lavatune on macOS and desktop environments."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .audio import AudioCapture, AudioFrame, DemoAudioCapture
from .canvas import project_presentation
from .config import AppConfig
from .organism import behavior_for_context

if TYPE_CHECKING:
    from .runtime import LavaField

WINDOW_WIDTH = 600
WINDOW_HEIGHT = 420


class WindowCompanion:
    """Standalone resizable window reusing LavaField physics and presentation."""

    def __init__(self, config: AppConfig, demo: bool = False) -> None:
        self.config = config
        self.demo = demo
        self.field: LavaField | None = None
        self.capture: AudioCapture | DemoAudioCapture | None = None
        self.sequence = 0
        self.last_frame = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, time.monotonic())
        self.running = False

    def run(self) -> int:
        try:
            import tkinter as tk
        except ImportError as exc:
            raise RuntimeError(
                "--window requires Python Tkinter support (tkinter module)."
            ) from exc

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise RuntimeError(
                f"--window failed to initialize GUI display: {exc}"
            ) from exc

        from .runtime import LavaField

        self.field = LavaField()
        self.field.resize(96, 54)
        self.capture = DemoAudioCapture() if self.demo else AudioCapture(self.config.audio)
        self.capture.start()

        root.title("Lavatune")
        root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        root.minsize(320, 220)
        root.resizable(True, True)

        bg_color = "#0c1017"
        root.configure(bg=bg_color)

        try:
            root.attributes("-alpha", 0.88)
        except tk.TclError:
            pass

        try:
            root.attributes("-topmost", False)
        except tk.TclError:
            pass

        canvas = tk.Canvas(
            root,
            bg=bg_color,
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        self.running = True

        def close_window(event=None) -> None:
            if not self.running:
                return
            self.running = False
            if self.capture is not None:
                self.capture.stop()
                self.capture = None
            try:
                root.destroy()
            except tk.TclError:
                pass

        root.protocol("WM_DELETE_WINDOW", close_window)

        root.bind("<Command-w>", close_window)
        root.bind("<Command-W>", close_window)
        root.bind("<Control-w>", close_window)
        root.bind("<Control-W>", close_window)
        root.bind("<Escape>", close_window)
        root.bind("<q>", close_window)
        root.bind("<Q>", close_window)

        interval_ms = max(16, min(100, round(1000 / max(1, self.config.fps))))

        def tick() -> None:
            if not self.running:
                return
            if self.capture is None or self.field is None:
                return

            for captured in self.capture.drain_after(self.sequence):
                self.sequence = captured.sequence
                self.last_frame = captured.frame

            if self.capture.error():
                err = self.capture.error()
                close_window()
                raise RuntimeError(f"Audio capture error: {err}")

            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())

            self.field.resize(max(60, width // 10), max(30, height // 12))
            self.field.step(
                self.last_frame,
                "music",
                self.config.profile,
                self.config.lava.reactivity,
                self.config.lava,
                rasterize=False,
                behavior=behavior_for_context(self.config.listening_context),
                embody_posture=True,
            )

            self._draw(canvas, width, height)

            if self.running:
                root.after(interval_ms, tick)

        root.after(0, tick)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            close_window()

        return 0

    def _draw(self, canvas, width: int, height: int) -> None:
        canvas.delete("all")
        if self.field is None:
            return

        presentation = self.field.presentation_frame()
        organisms = project_presentation(presentation, width, height)

        for organism in organisms:
            core_hex = _rgb_to_hex(organism.core_color)
            edge_hex = _rgb_to_hex(organism.edge_color)
            line_width = max(1, int(round(1.4 + organism.attention * 1.2)))

            core_pts = _flatten_points(organism.core)
            if len(core_pts) >= 6:
                canvas.create_polygon(
                    core_pts,
                    fill=core_hex,
                    outline=edge_hex,
                    width=line_width,
                    smooth=True,
                )

            lobe_hex = _rgb_to_hex(organism.lobe_color)
            lobe_width = max(1, int(round(1.0 + organism.attention)))

            lobe_pts = _flatten_points(organism.lobe)
            if len(lobe_pts) >= 6:
                canvas.create_polygon(
                    lobe_pts,
                    fill=lobe_hex,
                    outline=edge_hex,
                    width=lobe_width,
                    smooth=True,
                )


def _rgb_to_hex(color: tuple[float, float, float]) -> str:
    r = max(0, min(255, int(round(color[0] * 255))))
    g = max(0, min(255, int(round(color[1] * 255))))
    b = max(0, min(255, int(round(color[2] * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _flatten_points(points: tuple[tuple[float, float], ...]) -> list[float]:
    flat = []
    for x, y in points:
        flat.extend((x, y))
    return flat


def run_window(config: AppConfig, demo: bool = False) -> int:
    """Run the standalone window renderer without touching terminal mode."""
    return WindowCompanion(config, demo).run()
