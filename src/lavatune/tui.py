"""Terminal UI state and geometry shared by the curses application.

This module deliberately stops at presentation boundaries: it knows how a
terminal tile is arranged and stores short-lived UI state, but it does not
know about audio capture, organism physics, or control policy.
"""

from __future__ import annotations

import curses
import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import AppConfig
from .media import MediaInfo
from .text import sanitize_display_text


COMPACT_TARGET_CELLS = 900


@dataclass
class Button:
    y1: int
    x1: int
    y2: int
    x2: int
    action: str
    delta: int = 0

    def contains(self, y: int, x: int) -> bool:
        return self.y1 <= y <= self.y2 and self.x1 <= x <= self.x2


@dataclass
class Control:
    label: str
    value: Callable[[AppConfig], str]
    adjust: Callable[[AppConfig, int, "UiState"], str]


@dataclass
class Layout:
    vis_y: int
    vis_x: int
    vis_h: int
    vis_w: int
    dock_y: int
    dock_x: int
    dock_h: int
    dock_w: int
    side: str


@dataclass
class UiState:
    dock_open: bool = False
    tab_index: int = 0
    selected_row: int = 0
    status: str = ""
    status_until: float = 0.0
    buttons: list[Button] = field(default_factory=list)
    restart_audio: bool = False
    reset_lava: bool = False
    quit_requested: bool = False
    last_mouse: tuple[int, int] | None = None
    last_mouse_sig: tuple[int, int, int] | None = None
    last_mouse_at: float = 0.0
    escape_buffer: str = ""
    escape_started_at: float = 0.0
    resolved_mode: str = "auto"
    audio_status: str = "booting"
    media: MediaInfo = field(default_factory=MediaInfo)
    preferences_dirty: bool = False
    preferences_due_at: float = 0.0

    def set_status(self, message: str, *, ttl: float = 1.8) -> None:
        self.status = sanitize_display_text(message, max_chars=500)
        self.status_until = time.monotonic() + ttl

    def active_status(self) -> str:
        return self.status if time.monotonic() < self.status_until else ""


@dataclass
class VisualCache:
    key: tuple[object, ...] | None = None
    cells: dict[tuple[int, int], tuple[str, int]] = field(default_factory=dict)

    def clear(self) -> None:
        self.key = None
        self.cells = {}


def safe_add(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """Write a bounded terminal run without letting a small tile raise curses."""

    if y < 0 or x < 0:
        return
    height, width = win.getmaxyx()
    if y >= height or x >= width:
        return
    limit = max(0, width - x)
    if limit <= 0:
        return
    try:
        win.addnstr(y, x, text, limit, attr)
    except curses.error:
        pass


def _env_value(name: str) -> str:
    value = os.environ.get(f"LAVATUNE_{name}")
    if value is not None:
        return value
    return os.environ.get(f"CODEXDECK_LAVATUNE_{name}", "")


def _env_flag(name: str) -> bool:
    value = _env_value(name)
    return value.lower() in {"1", "true", "yes", "on"}


def _positive_env_int(name: str) -> int | None:
    value = _env_value(name)
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def compact_layout(config: AppConfig | None) -> bool:
    render = getattr(config, "render", None)
    return _env_flag("COMPACT") or bool(getattr(render, "compact", False))


def visual_limits(config: AppConfig | None) -> tuple[int | None, int | None]:
    render = getattr(config, "render", None)
    width = _positive_env_int("MAX_WIDTH") or getattr(render, "max_width", None)
    height = _positive_env_int("MAX_HEIGHT") or getattr(render, "max_height", None)
    return width, height


def clamp_visual_size(width: int, height: int, config: AppConfig | None) -> tuple[int, int]:
    max_width, max_height = visual_limits(config)
    if max_width:
        width = min(width, max_width)
    if max_height:
        height = min(height, max_height)
    return max(1, width), max(1, height)


def compute_layout(rows: int, cols: int, dock_open: bool, config: AppConfig | None = None) -> Layout:
    """Return the visual and optional dock rectangles for the current tile."""

    if not dock_open:
        vis_w, vis_h = clamp_visual_size(cols, max(1, rows - 1), config)
        return Layout(0, 0, vis_h, vis_w, vis_h, vis_w, 0, 0, "hidden")

    side_layout = cols >= 96
    if side_layout:
        dock_w = min(38, max(1, cols - 1))
        vis_h = max(1, rows - 1)
        vis_w = max(1, cols - dock_w)
        vis_w, vis_h = clamp_visual_size(vis_w, vis_h, config)
        return Layout(0, 0, vis_h, vis_w, 0, vis_w, vis_h, dock_w, "right")
    requested_dock_h = 12 if rows >= 16 else 1
    dock_h = min(requested_dock_h, max(1, rows - 2))
    vis_h = max(1, rows - dock_h - 1)
    vis_w, vis_h = clamp_visual_size(cols, vis_h, config)
    return Layout(0, 0, vis_h, vis_w, vis_h, 0, dock_h, vis_w, "bottom")


def effective_cell_width(config: AppConfig, width: int, height: int) -> int:
    configured = max(1, int(getattr(config.render, "scale", 1)))
    if not compact_layout(config):
        return configured

    # Compact mode budgets simulated cells by area. A tiny i3 tile therefore
    # gains detail while a large tile avoids an unnecessary CPU/output spike.
    target_cells = _positive_env_int("TARGET_CELLS") or COMPACT_TARGET_CELLS
    target_cells = max(180, min(1400, target_cells))
    adaptive = max(1, math.ceil((max(1, width) * max(1, height)) / target_cells))
    return max(1, min(5, adaptive))
