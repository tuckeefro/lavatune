"""Opt-in pixel-canvas companion view for Lavatune's existing organisms."""

from __future__ import annotations

import colorsys
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .audio import AudioCapture, AudioFrame, DemoAudioCapture
from .config import AppConfig
from .organism import AudioForces, Body, behavior_for_context, clamp
from .presentation import PresentationFrame

if TYPE_CHECKING:
    from .app import LavaField


CANVAS_WIDTH = 960
CANVAS_HEIGHT = 640
CORE_POINTS = 24
LOBE_POINTS = 16


@dataclass(slots=True, frozen=True)
class CanvasOrganism:
    """Two local, fixed-size surfaces for one persistent organism."""

    depth: float
    core: tuple[tuple[float, float], ...]
    lobe: tuple[tuple[float, float], ...]
    core_color: tuple[float, float, float]
    lobe_color: tuple[float, float, float]
    edge_color: tuple[float, float, float]
    attention: float


def _ring(
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
    rotation: float,
    phase: float,
    count: int,
    *,
    forward_taper: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Create a soft, bounded asymmetric contour without a field pass."""

    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    points = []
    for index in range(count):
        angle = math.tau * index / count
        local_x = math.cos(angle)
        local_y = math.sin(angle)
        organic = 1.0 + math.sin(angle * 2.0 + phase) * 0.065
        organic += math.cos(angle * 3.0 - phase * 0.73) * 0.035
        organic += max(0.0, local_x) * forward_taper
        x = local_x * radius_x * organic
        y = local_y * radius_y * organic
        points.append((center_x + cosine * x - sine * y, center_y + sine * x + cosine * y))
    return tuple(points)


def _color(body: Body, attention: float) -> tuple[tuple[float, float, float], ...]:
    """Use depth and surface direction as color, with a restrained role tint."""

    role_hue = {
        "ballast": 0.60,
        "listener": 0.55,
        "glint": 0.51,
        "drifter": 0.57,
    }.get(body.character.name, 0.56)
    facing = clamp(0.50 + math.sin(body.yaw) * 0.22 + math.cos(body.pitch) * 0.10)
    depth = clamp(body.z)
    core = colorsys.hsv_to_rgb(role_hue, 0.48 - depth * 0.12, 0.46 + depth * 0.28)
    lobe = colorsys.hsv_to_rgb(
        role_hue + 0.025,
        0.40 + attention * 0.20,
        0.52 + facing * 0.25 + attention * 0.12,
    )
    edge = colorsys.hsv_to_rgb(role_hue - 0.018, 0.32, 0.68 + depth * 0.24)
    return core, lobe, edge


def project_organism(
    body: Body,
    forces: AudioForces,
    width: int,
    height: int,
) -> CanvasOrganism:
    """Project one soft body into fixed polygon work suitable for Cairo."""

    width = max(1, width)
    height = max(1, height)
    depth = clamp(body.z)
    base = max(10.0, min(width, height) * body.radius * (0.70 + depth * 0.45))
    core_x = base * body.character.volume_width * clamp(body.stretch_x, 0.92, 1.08)
    core_y = base * body.character.volume_height * clamp(body.stretch_y, 0.92, 1.08)
    center_x = body.x * width
    center_y = body.y * height
    core = _ring(
        center_x,
        center_y,
        core_x,
        core_y,
        body.roll,
        body.phase,
        CORE_POINTS,
    )

    spike = clamp(body.spike + forces.transient * 0.65 + forces.pulse * 0.25)
    heading = body.yaw + math.sin(body.impact_angle - body.yaw) * spike
    distance = base * (body.character.volume_lobe_offset + spike * 0.82)
    lobe_x = center_x + math.cos(heading) * distance
    lobe_y = center_y + math.sin(heading) * distance
    lobe = _ring(
        lobe_x,
        lobe_y,
        base * body.character.volume_lobe_size * (0.72 + spike * 0.34),
        base * body.character.volume_lobe_size * (0.58 + spike * 0.18),
        heading,
        body.phase + 0.82,
        LOBE_POINTS,
        forward_taper=spike * 0.80,
    )
    attention = clamp(max(body.afterglow, body.spike * 0.72))
    core_color, lobe_color, edge_color = _color(body, attention)
    return CanvasOrganism(
        depth=depth,
        core=core,
        lobe=lobe,
        core_color=core_color,
        lobe_color=lobe_color,
        edge_color=edge_color,
        attention=attention,
    )


def project_organisms(
    bodies: list[Body],
    forces: AudioForces,
    width: int,
    height: int,
) -> tuple[CanvasOrganism, ...]:
    """Bound canvas work to four organisms with two fixed local surfaces each."""

    visible = [
        project_organism(body, forces, width, height)
        for body in bodies[:4]
        if body.presence >= 0.01
    ]
    return tuple(sorted(visible, key=lambda organism: organism.depth))


def project_presentation(
    presentation: PresentationFrame,
    width: int,
    height: int,
) -> tuple[CanvasOrganism, ...]:
    """Project the same renderer-neutral frame consumed by the terminal UI."""

    return project_organisms(presentation.bodies, presentation.forces, width, height)


def _path(context, points: tuple[tuple[float, float], ...]) -> None:
    first_x, first_y = points[0]
    context.move_to(first_x, first_y)
    for x, y in points[1:]:
        context.line_to(x, y)
    context.close_path()


class CanvasCompanion:
    """GTK/Cairo window that reuses live capture and Lavatune's physics."""

    def __init__(self, config: AppConfig, demo: bool = False) -> None:
        self.config = config
        self.demo = demo
        self.field: LavaField | None = None
        self.capture: AudioCapture | DemoAudioCapture | None = None
        self.sequence = 0
        self.last_frame = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, time.monotonic())
        self.error: str | None = None

    def run(self) -> int:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib, Gtk
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "--canvas requires GTK 3 with PyGObject (python3-gi)."
            ) from exc

        from .app import LavaField

        self.field = LavaField()
        self.field.resize(96, 54)
        self.capture = DemoAudioCapture() if self.demo else AudioCapture(self.config.audio)
        self.capture.start()

        window = Gtk.Window(title="Lavatune companion")
        window.set_default_size(CANVAS_WIDTH, CANVAS_HEIGHT)
        window.set_size_request(480, 320)
        area = Gtk.DrawingArea()
        window.add(area)
        window.connect("destroy", self._close, Gtk)
        area.connect("draw", self._draw)
        interval = max(12, min(60, self.config.fps))
        GLib.timeout_add(max(1, round(1000 / interval)), self._tick, area)
        window.show_all()
        Gtk.main()
        return 0

    def _close(self, _window, gtk) -> None:
        if self.capture is not None:
            self.capture.stop()
        gtk.main_quit()

    def _tick(self, area) -> bool:
        if self.capture is None or self.field is None:
            return False
        for captured in self.capture.drain_after(self.sequence):
            self.sequence = captured.sequence
            self.last_frame = captured.frame
        if self.capture.error():
            self.error = self.capture.error()
        allocation = area.get_allocation()
        self.field.resize(max(60, allocation.width // 10), max(30, allocation.height // 12))
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
        area.queue_draw()
        return self.error is None

    def _draw(self, area, context) -> bool:
        allocation = area.get_allocation()
        width = max(1, allocation.width)
        height = max(1, allocation.height)
        context.set_source_rgb(0.012, 0.018, 0.031)
        context.paint()
        if self.field is None:
            return False
        presentation = self.field.presentation_frame()
        for organism in project_presentation(presentation, width, height):
            _path(context, organism.core)
            context.set_source_rgb(*organism.core_color)
            context.fill_preserve()
            context.set_source_rgb(*organism.edge_color)
            context.set_line_width(1.4 + organism.attention * 1.2)
            context.stroke()
            _path(context, organism.lobe)
            context.set_source_rgb(*organism.lobe_color)
            context.fill_preserve()
            context.set_source_rgb(*organism.edge_color)
            context.set_line_width(1.0 + organism.attention)
            context.stroke()
        return False


def run_canvas(config: AppConfig, demo: bool = False) -> int:
    """Run the opt-in companion window without touching terminal mode."""

    return CanvasCompanion(config, demo).run()
