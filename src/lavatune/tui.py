"""Terminal UI state and geometry shared by the curses application.

This module deliberately stops at presentation boundaries: it knows how a
terminal tile is arranged and stores short-lived UI state, but it does not
know about audio capture, organism physics, or control policy.
"""

from __future__ import annotations

import curses
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .audio import AudioFrame
from .config import AppConfig
from .materials import MaterialStyle, material_for, normalize_glyph_ramp, visual_shade
from .media import MediaInfo
from .runtime import LavaField
from .signals import clamp
from .text import sanitize_display_text


COMPACT_TARGET_CELLS = 900
TAB_NAMES = ("Listening",)
DAILY_PALETTES = ("soft-afterglow", "mono", "ice", "oxide")
PALETTES: dict[str, tuple[int, ...]] = {
    "soft-afterglow": (236, 60, 139, 187),
    "amber": (curses.COLOR_BLACK, curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_WHITE),
    "matrix": (curses.COLOR_BLACK, curses.COLOR_GREEN, curses.COLOR_GREEN, curses.COLOR_WHITE),
    "ice": (curses.COLOR_BLACK, curses.COLOR_BLUE, curses.COLOR_CYAN, curses.COLOR_WHITE),
    "oxide": (curses.COLOR_BLACK, curses.COLOR_MAGENTA, curses.COLOR_RED, curses.COLOR_YELLOW),
    "mono": (curses.COLOR_BLACK, curses.COLOR_WHITE, curses.COLOR_WHITE, curses.COLOR_WHITE),
    "mint": (curses.COLOR_BLACK, curses.COLOR_GREEN, curses.COLOR_CYAN, curses.COLOR_WHITE),
    "sunset": (curses.COLOR_BLACK, curses.COLOR_MAGENTA, curses.COLOR_RED, curses.COLOR_YELLOW),
    "paper": (curses.COLOR_BLACK, curses.COLOR_WHITE, curses.COLOR_YELLOW, curses.COLOR_CYAN),
    "rose": (curses.COLOR_BLACK, curses.COLOR_MAGENTA, curses.COLOR_RED, curses.COLOR_WHITE),
}
PALETTE_FALLBACKS: dict[str, tuple[int, ...]] = {
    "soft-afterglow": (
        curses.COLOR_BLACK,
        curses.COLOR_MAGENTA,
        curses.COLOR_WHITE,
        curses.COLOR_YELLOW,
    ),
}
_PALETTE_PAIR_IDS: dict[str, tuple[int, ...]] = {}
DEFAULT_GLYPHS = " .,:;~oO@"

# ``visual_shade`` remains part of the historical app-level presentation API.
# Re-export it here with the terminal presentation helpers that use its scale.
__all__ = ["visual_shade"]


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
    help_overlay: bool = False

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


def palette_name(value: object) -> str:
    return value if isinstance(value, str) and value in PALETTES else "soft-afterglow"


def init_colors() -> None:
    _PALETTE_PAIR_IDS.clear()
    try:
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        _PALETTE_PAIR_IDS.update(
            {name: (0,) * len(palette) for name, palette in PALETTES.items()}
        )
        return
    pair_index = 1
    available_colors = max(0, getattr(curses, "COLORS", 0))
    pair_limit = max(1, getattr(curses, "COLOR_PAIRS", 0))
    if available_colors <= 0 or pair_limit <= 1:
        _PALETTE_PAIR_IDS.update(
            {name: (0,) * len(palette) for name, palette in PALETTES.items()}
        )
        return
    for name, palette in PALETTES.items():
        if pair_index + len(palette) > pair_limit:
            _PALETTE_PAIR_IDS[name] = _PALETTE_PAIR_IDS.get(
                "soft-afterglow", (0,) * len(palette)
            )
            continue
        fallback = PALETTE_FALLBACKS.get(name, palette)
        pair_ids = []
        for bucket, fg in enumerate(palette):
            resolved = fg if 0 <= fg < available_colors else fallback[bucket]
            if not 0 <= resolved < available_colors:
                resolved = min(curses.COLOR_WHITE, available_colors - 1)
            try:
                curses.init_pair(pair_index, resolved, -1)
            except curses.error:
                pair_ids.append(0)
            else:
                pair_ids.append(pair_index)
            pair_index += 1
        _PALETTE_PAIR_IDS[name] = tuple(pair_ids)


def palette_attr(name: str, bucket: int) -> int:
    bucket = max(0, min(bucket, 3))
    pair_ids = _PALETTE_PAIR_IDS.get(name) or _PALETTE_PAIR_IDS.get("soft-afterglow")
    pair_id = pair_ids[bucket] if pair_ids and bucket < len(pair_ids) else 0
    return curses.color_pair(pair_id)


def interpolated_row_value(source: Sequence[float], screen_x: int, screen_width: int) -> float:
    if not source:
        return 0.0
    grid_position = screen_x * max(0, len(source) - 1) / max(1, screen_width - 1)
    left = int(grid_position)
    right = min(len(source) - 1, left + 1)
    mix = grid_position - left
    return source[left] * (1.0 - mix) + source[right] * mix


def semantic_color_bucket(
    shade: float,
    attention: float,
    color_steps: int,
    face: float | None = None,
) -> int:
    """Reserve the final palette color for a local acoustic event."""

    color_steps = max(2, min(4, color_steps))
    if shade <= 0.0:
        return 0
    if color_steps == 2 or attention >= 0.08:
        return color_steps - 1
    if face is not None:
        return max(1, min(color_steps - 2, 1 + int(clamp(face) * (color_steps - 2))))
    return max(1, min(color_steps - 2, int(shade * (color_steps - 1))))


def unicode_output_supported(encoding: str | None = None) -> bool:
    resolved = (encoding or sys.stdout.encoding or "").replace("-", "").lower()
    return "utf8" in resolved


def changed_cell_runs(
    previous: tuple[tuple[str, int], ...] | None,
    current: tuple[tuple[str, int], ...],
) -> list[tuple[int, str, int]]:
    """Group only changed adjacent cells that share a terminal attribute."""

    runs: list[tuple[int, str, int]] = []
    x = 0
    while x < len(current):
        if previous is not None and x < len(previous) and previous[x] == current[x]:
            x += 1
            continue
        start = x
        attr = current[x][1]
        chars = []
        while x < len(current) and current[x][1] == attr:
            if previous is not None and x < len(previous) and previous[x] == current[x]:
                break
            chars.append(current[x][0])
            x += 1
        runs.append((start, "".join(chars), attr))
    return runs


def changed_sparse_runs(
    previous: dict[tuple[int, int], tuple[str, int]],
    current: dict[tuple[int, int], tuple[str, int]],
    blank_attr: int,
) -> list[tuple[int, int, str, int]]:
    """Return terminal runs for the sparse union of old and new contours."""

    changed = sorted(
        position
        for position in previous.keys() | current.keys()
        if previous.get(position) != current.get(position)
    )
    runs: list[tuple[int, int, str, int]] = []
    index = 0
    while index < len(changed):
        y, x = changed[index]
        char, attr = current.get((y, x), (" ", blank_attr))
        start = x
        text = [char]
        index += 1
        while index < len(changed):
            next_y, next_x = changed[index]
            next_char, next_attr = current.get((next_y, next_x), (" ", blank_attr))
            if next_y != y or next_x != x + 1 or next_attr != attr:
                break
            text.append(next_char)
            x = next_x
            index += 1
        runs.append((y, start, "".join(text), attr))
    return runs


def draw_help_overlay(win: curses.window) -> None:
    height, width = win.getmaxyx()
    lines = [
        "--- Lavatune Controls & Presets ---",
        "  1..4  : Presets (1: Calm, 2: Balanced, 3: Reactive, 4: Chaos)",
        "  g/G   : Adjust gain / reactivity (+/-)",
        "  r/R   : Adjust reactivity (+/-)",
        "  s/S   : Adjust smoothing / decay (+/-)",
        "  m/M   : Adjust autonomous motion speed (+/-)",
        "  d/D   : Adjust visual density / complexity (+/-)",
        "  f/F   : Adjust FPS cap (12, 20, 30, 45, 60)",
        "  p/P   : Cycle color palette",
        "  Tab   : Toggle control dock",
        "  ?     : Toggle this help overlay",
        "  q/Q   : Quit",
    ]
    start_y = max(0, (height - len(lines)) // 2)
    start_x = max(0, (width - 60) // 2)
    for idx, line in enumerate(lines):
        if start_y + idx >= height:
            break
        safe_add(win, start_y + idx, start_x, line[: max(0, width - start_x)], curses.A_BOLD | curses.A_REVERSE)


def draw_visual(
    win: curses.window,
    field: LavaField,
    config: AppConfig,
    frame: AudioFrame,
    ui: UiState,
    cache: VisualCache | None = None,
) -> None:
    """Render one material frame and write only its changed terminal contours."""

    height, width = win.getmaxyx()
    palette = palette_name(getattr(config.render, "palette", "amber"))
    color_steps = max(2, min(4, int(getattr(config.render, "color_steps", 4))))
    material = material_for(
        getattr(config.render, "material", "text"),
        unicode_supported=unicode_output_supported(),
    )
    style = MaterialStyle(
        glyphs=normalize_glyph_ramp(getattr(config.render, "glyphs", DEFAULT_GLYPHS)),
        weight=getattr(config.render, "weight", "balanced"),
        edge=getattr(config.render, "edge", "soft"),
        afterglow=getattr(config.render, "afterglow", "present"),
    )
    material_started = time.perf_counter()
    current_cells: dict[tuple[int, int], tuple[str, int]] = {}
    presentation = field.presentation_frame()

    def add_cell(y: int, x: int, cell: object) -> None:
        glyph = getattr(cell, "glyph")
        if glyph == " ":
            return
        shade = getattr(cell, "shade")
        attention = getattr(cell, "attention")
        bucket = semantic_color_bucket(shade, attention, color_steps, getattr(cell, "face"))
        attr = palette_attr(palette, bucket)
        if shade < 0.30:
            attr |= curses.A_DIM
        elif attention > 0.58:
            attr |= curses.A_BOLD
        current_cells[(y, x)] = (glyph, attr)

    if material.name == "wax":
        span_rows = material.render_spans(
            field.wax, width, height, style, presentation.phase,
            float(getattr(config.render, "cell_aspect", 1.85)),
        )
    elif material.name in {"fluid", "volume"}:
        span_rows = material.render_spans(
            presentation.bodies, presentation.forces, width, height, style,
            presentation.phase, float(getattr(config.render, "cell_aspect", 1.85)),
        )
    else:
        span_rows = None
        cell_rows = material.render(field.field_frame, width, height, style, field.phase)
        for y, cells in enumerate(cell_rows):
            for x, cell in enumerate(cells):
                add_cell(y, x, cell)
    if span_rows is not None:
        for y, spans in span_rows.items():
            for span in spans:
                for offset, cell in enumerate(span.cells):
                    add_cell(y, span.start + offset, cell)
    field.metrics.material_seconds += time.perf_counter() - material_started

    cache_key = (
        width, height, material.name, palette, color_steps, style,
        bool(getattr(config.render, "show_stats", False)),
    )
    previous_cells: dict[tuple[int, int], tuple[str, int]] = {}
    if cache is not None:
        if cache.key != cache_key:
            win.erase()
        else:
            previous_cells = cache.cells

    terminal_started = time.perf_counter()
    changed_cells = 0
    written_runs = 0
    blank_attr = palette_attr(palette, 0)
    for y, start, text, attr in changed_sparse_runs(previous_cells, current_cells, blank_attr):
        safe_add(win, y, start, text, attr)
        changed_cells += len(text)
        written_runs += 1

    if cache is not None:
        cache.key = cache_key
        cache.cells = current_cells
    field.metrics.draws += 1
    field.metrics.changed_cells += changed_cells
    field.metrics.written_runs += written_runs
    field.metrics.terminal_seconds += time.perf_counter() - terminal_started

    if ui.help_overlay:
        draw_help_overlay(win)
        if cache is not None:
            cache.clear()

    if getattr(config.render, "show_stats", True):
        stats = [
            f"mode {ui.resolved_mode}", f"rms {frame.rms:0.2f}",
            f"attack {frame.attack:0.2f}", f"gain x{field.response_gain:0.2f}",
            f"l/m/h {field.last_low:0.1f}/{field.last_mid:0.1f}/{field.last_high:0.1f}",
            f"kick {field.last_kick:0.1f}", f"voice {field.last_voice:0.1f}",
            f"spec {max(field.spectral_bands) if field.spectral_bands else 0.0:0.1f}",
            f"hit {max(field.spectral_hits) if field.spectral_hits else 0.0:0.1f}",
            f"impact {field.impact:0.1f}", f"zcr {frame.zcr:0.2f}",
        ]
        for index, line in enumerate(stats):
            if index >= height:
                break
            safe_add(win, index, 1, line, curses.A_DIM)
        if cache is not None:
            cache.clear()


def _display_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    return str(value)


def draw_dock(
    win: curses.window,
    config: AppConfig,
    ui: UiState,
    controls: dict[str, list[Control]],
    layout: Layout,
) -> None:
    win.erase()
    ui.buttons = []
    height, width = win.getmaxyx()
    if not ui.dock_open:
        label = "[=]" if layout.side == "right" else "[ dock ]"
        if layout.side == "right":
            for index, char in enumerate(label):
                safe_add(win, min(index + 1, height - 1), 0, char, curses.A_BOLD)
            ui.buttons.append(Button(0, 0, min(height - 1, len(label) + 1), min(width - 1, 2), "toggle_dock"))
        else:
            safe_add(win, 0, 1, label, curses.A_BOLD)
            ui.buttons.append(Button(0, 0, 0, min(width - 1, len(label) + 2), "toggle_dock"))
        win.noutrefresh()
        return

    safe_add(win, 0, 1, " lavatune companion ", curses.A_BOLD)
    close_x = max(1, width - 5)
    safe_add(win, 0, close_x, "[x]", curses.A_BOLD)
    ui.buttons.append(Button(0, close_x, 0, min(width - 1, close_x + 2), "toggle_dock"))
    tab_x = 1
    for index, name in enumerate(TAB_NAMES):
        text = f" {name} "
        attr = curses.A_REVERSE if index == ui.tab_index else curses.A_NORMAL
        safe_add(win, 2, tab_x, text, attr)
        ui.buttons.append(Button(2, tab_x, 2, min(width - 1, tab_x + len(text) - 1), f"tab:{index}"))
        tab_x += len(text) + 1

    rows = controls[TAB_NAMES[ui.tab_index]]
    ui.selected_row = max(0, min(ui.selected_row, len(rows) - 1))
    y = 4
    for index, control in enumerate(rows):
        selected = index == ui.selected_row
        attr = curses.A_BOLD if selected else curses.A_NORMAL
        value = _display_text(control.value(config))
        safe_add(win, y, 2, control.label.ljust(10), attr)
        left_x = max(14, width - 21)
        value_x = left_x + 4
        right_x = max(value_x + len(value) + 2, width - 5)
        safe_add(win, y, left_x, "[-]", curses.A_REVERSE if selected else curses.A_DIM)
        safe_add(win, y, value_x, value[: max(6, width - value_x - 6)], attr)
        safe_add(win, y, right_x, "[+]", curses.A_REVERSE if selected else curses.A_DIM)
        ui.buttons.append(Button(y, 2, y, min(width - 1, width - 2), f"select:{index}"))
        ui.buttons.append(Button(y, left_x, y, min(width - 1, left_x + 2), f"adjust:{index}", -1))
        ui.buttons.append(Button(y, right_x, y, min(width - 1, right_x + 2), f"adjust:{index}", 1))
        y += 2
        if y >= height - 4:
            break
    win.noutrefresh()


def draw_status(
    stdscr: curses.window,
    config: AppConfig,
    ui: UiState,
    field: LavaField,
    preset: str,
    reactivity: str,
) -> None:
    rows, cols = stdscr.getmaxyx()
    state = f"calibrating {min(field.calibration_frames, 72)}/72" if field.calibration_frames < 72 else f"tracking x{field.response_gain:0.2f}"
    active_status = ui.active_status()
    media_status = ui.media.display()
    if active_status:
        status = active_status
    elif getattr(config, "listening_context", "music") == "microphone":
        status = "lavatune | mic active"
    elif media_status:
        status = media_status
    elif getattr(config.render, "show_stats", True):
        status = (
            f"{preset} | {reactivity} | {ui.resolved_mode} | {state} | "
            f"tone {field.forces.tone:0.2f} | tempo {field.forces.tempo:0.2f} | "
            f"pulse {field.forces.pulse:0.2f} | density {field.forces.rhythm_density:0.2f} | "
            f"hold/snap {field.affect.restraint:0.2f}/{field.affect.snap:0.2f} | "
            f"story {field.narrative.expectation:0.1f}/{field.narrative.interruption:0.1f}/{field.narrative.resolution:0.1f} | "
            f"l/m/h {field.last_low:0.1f}/{field.last_mid:0.1f}/{field.last_high:0.1f}"
        )
    else:
        status = "lavatune | listening"
    line = status[: max(0, cols - 1)]
    attr = curses.A_REVERSE if active_status else curses.A_DIM
    try:
        stdscr.addnstr(rows - 1, 0, " " * max(0, cols - 1), max(0, cols - 1), attr)
        stdscr.addnstr(rows - 1, 0, line, max(0, cols - 1), attr)
    except curses.error:
        pass
