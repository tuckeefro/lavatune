"""Curses interface joining audio capture, organism physics, and terminal drawing."""

from __future__ import annotations

import curses
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .audio import AudioCapture, AudioFrame, DemoAudioCapture
from .config import CONTENT_MODES, PROFILE_NAMES, AppConfig, LavaConfig, apply_profile
from .media import MediaInfo, MediaWatcher
from .organism import (
    AcousticOrganism,
    AudioForceMapper,
    AudioForces,
    Body,
    OrganismFieldRenderer,
    TileComposition,
)
from .text import sanitize_display_text

TAB_NAMES = ("Modes", "Look", "System")
ANALYSIS_MODES = ("atlas", "bands")
BACKEND_MODES = ("auto", "pipewire", "pulse", "ffmpeg")
COMPACT_TARGET_CELLS = 900
REACTIVITY_MODES: dict[str, float] = {
    "whisper": 0.65,
    "conversational": 1.0,
    "electric": 1.45,
}
DENSITY_MODES: dict[str, int] = {
    "sparse": 3,
    "medium": 4,
    "rich": 8,
}
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
STYLE_PRESETS: dict[str, str] = {
    "liquid": " .,:;~oO@",
    "soft": " .:-=+*#%@",
    "bubbles": " .oO0@",
    "dense": " `.^,:;Il!i~+_-?][}{1)(|\\/*tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "blocks": " ░▒▓█",
    "matrix": " .,:;|/tfLCG08@",
    "bars": " .-:=|#",
    "embers": " .,:=xX$&",
}
GLYPH_PRESETS = tuple(STYLE_PRESETS.values())
SCENES: dict[str, dict[str, object]] = {
    "soft-afterglow": {
        "palette": "soft-afterglow",
        "style": "liquid",
        "scale": 3,
        "colors": 4,
        "profile": "atlas",
        "content": "speech",
    },
    "embers": {
        "palette": "sunset",
        "style": "embers",
        "scale": 1,
        "colors": 4,
        "profile": "atlas",
        "content": "auto",
    },
    "matrix": {
        "palette": "matrix",
        "style": "matrix",
        "scale": 1,
        "colors": 3,
        "profile": "power-save",
        "content": "speech",
    },
    "glacier": {
        "palette": "ice",
        "style": "soft",
        "scale": 1,
        "colors": 4,
        "profile": "atlas",
        "content": "book",
    },
    "paper": {
        "palette": "paper",
        "style": "bars",
        "scale": 2,
        "colors": 2,
        "profile": "power-save",
        "content": "book",
    },
    "braille": {
        "palette": "rose",
        "style": "blocks",
        "scale": 1,
        "colors": 4,
        "profile": "responsive",
        "content": "music",
    },
    "mint": {
        "palette": "mint",
        "style": "bubbles",
        "scale": 2,
        "colors": 3,
        "profile": "atlas",
        "content": "speech",
    },
}
PRODUCT_PRESETS: dict[str, dict[str, object]] = {
    "listen": {
        "scene": "soft-afterglow",
        "profile": "atlas",
        "content": "auto",
        "fps": 22,
        "analysis": "atlas",
        "reactivity": "conversational",
        "density": "medium",
    },
    "music": {
        "scene": "soft-afterglow",
        "profile": "responsive",
        "content": "music",
        "fps": 28,
        "analysis": "bands",
        "reactivity": "conversational",
        "density": "medium",
    },
    "speech": {
        "scene": "soft-afterglow",
        "profile": "atlas",
        "content": "speech",
        "fps": 22,
        "analysis": "bands",
        "reactivity": "conversational",
        "density": "medium",
    },
    "low-power": {
        "scene": "soft-afterglow",
        "profile": "power-save",
        "content": "speech",
        "fps": 12,
        "analysis": "atlas",
        "reactivity": "whisper",
        "density": "sparse",
    },
}


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

    def set_status(self, message: str, *, ttl: float = 1.8) -> None:
        self.status = sanitize_display_text(message, max_chars=500)
        self.status_until = time.monotonic() + ttl

    def active_status(self) -> str:
        return self.status if time.monotonic() < self.status_until else ""


class LavaField:
    """Own one renderable organism and translate audio frames into its forces."""

    def __init__(self, motion_profile: str = "buoyant") -> None:
        self.w = 0
        self.h = 0
        self.motion_profile = motion_profile
        self.mapper = AudioForceMapper()
        self.organism = AcousticOrganism()
        self.renderer = OrganismFieldRenderer()
        self.forces = AudioForces()
        self.buffers: list[list[float]] = []
        self.attention_buffers: list[list[float]] = []
        self._last_step_at: float | None = None
        self.phase = 0.0
        self.reactivity = 1.0
        self.frames_seen = 0

    @property
    def bodies(self) -> list[Body]:
        return self.organism.bodies

    @property
    def composition(self) -> TileComposition:
        return self.organism.composition

    # These names match the terse status display. Properties keep that UI from
    # maintaining a second, easily stale copy of the mapped audio forces.
    @property
    def response_gain(self) -> float:
        return self.reactivity

    @property
    def calibration_frames(self) -> int:
        return self.frames_seen

    @property
    def last_low(self) -> float:
        return self.forces.bass

    @property
    def last_mid(self) -> float:
        return self.forces.voice

    @property
    def last_high(self) -> float:
        return self.forces.detail

    @property
    def last_kick(self) -> float:
        return self.forces.transient

    @property
    def last_voice(self) -> float:
        return self.forces.voice

    @property
    def impact(self) -> float:
        return self.forces.transient

    @property
    def spectral_bands(self) -> tuple[float, ...]:
        return self.forces.bands

    @property
    def spectral_hits(self) -> tuple[float, ...]:
        return self.forces.hits

    def resize(self, width: int, height: int) -> None:
        width = max(10, width)
        height = max(6, height)
        if width == self.w and height == self.h:
            return
        self.w = width
        self.h = height
        self.buffers = [[0.0] * width for _ in range(height)]
        self.attention_buffers = [[0.0] * width for _ in range(height)]

    def clear(self) -> None:
        capacity = max(1, len(self.organism.bodies))
        self.mapper.reset()
        self.organism.reset(capacity)
        self.forces = AudioForces()
        self._last_step_at = None
        self.phase = 0.0
        self.reactivity = 1.0
        self.frames_seen = 0
        for row in self.buffers:
            row[:] = [0.0] * self.w
        for row in self.attention_buffers:
            row[:] = [0.0] * self.w

    def step(
        self,
        frame: AudioFrame,
        mode: str,
        profile: str,
        reactivity: float,
        lava_config: LavaConfig,
    ) -> None:
        if not self.buffers:
            return
        now = time.monotonic()
        nominal_fps = 22.0 if profile == "atlas" else 12.0 if profile == "power-save" else 28.0
        dt = 1.0 / nominal_fps if self._last_step_at is None else now - self._last_step_at
        self._last_step_at = now

        self.forces = self.mapper.map(frame, mode, reactivity)
        self.organism.update(
            dt,
            self.forces,
            self.w,
            self.h,
            lava_config,
            self.motion_profile,
        )
        self.buffers, self.attention_buffers = self.renderer.render(
            self.organism.bodies,
            self.forces,
            self.w,
            self.h,
            self.organism.phase,
            self.motion_profile,
        )

        self.phase = self.organism.phase
        self.reactivity = reactivity
        self.frames_seen += 1


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _cycle(current: str, choices: Sequence[str], delta: int) -> str:
    try:
        index = choices.index(current)
    except ValueError:
        index = 0
    return choices[(index + delta) % len(choices)]


def _reactivity_name(value: float) -> str:
    return min(REACTIVITY_MODES, key=lambda name: abs(REACTIVITY_MODES[name] - value))


def _set_reactivity(config: AppConfig, name: str) -> None:
    config.lava.reactivity = REACTIVITY_MODES.get(name, REACTIVITY_MODES["conversational"])


def _density_name(value: int) -> str:
    return min(DENSITY_MODES, key=lambda name: abs(DENSITY_MODES[name] - value))


def _set_density(config: AppConfig, name: str) -> None:
    config.lava.blobs = DENSITY_MODES.get(name, DENSITY_MODES["medium"])


def _palette_name(value) -> str:
    if isinstance(value, str) and value in PALETTES:
        return value
    return "soft-afterglow"


def _display_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    return str(value)


def _glyph_text(value) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = "".join(str(part) for part in value)
    else:
        text = str(value)
    if not text.strip():
        return GLYPH_PRESETS[0]
    if len(set(text)) < 2:
        return GLYPH_PRESETS[0]
    return text


def _safe_add(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
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


def _set_focus_reporting(enabled: bool) -> None:
    # DECSET 1004 asks compatible terminals to report focus in/out. It is not
    # part of curses, so always disable it again in the outer finally block.
    try:
        sys.stdout.write("\x1b[?1004h" if enabled else "\x1b[?1004l")
        sys.stdout.flush()
    except OSError:
        pass


def _build_capture(config: AppConfig, demo: bool) -> AudioCapture | DemoAudioCapture:
    capture = DemoAudioCapture() if demo else AudioCapture(config.audio)
    capture.start()
    return capture


def _silent_frame() -> AudioFrame:
    return AudioFrame(rms=0.0, bands=[0.0] * 8, attack=0.0, zcr=0.0, timestamp=time.time())


def _resolve_mode(requested: str, frame: AudioFrame) -> str:
    if requested != "auto":
        return requested
    bands = list(frame.bands or [])
    band_peak = max(bands) if bands else 0.0
    band_floor = min(bands) if bands else 0.0
    band_spread = band_peak - band_floor
    if frame.rms > 0.14 or frame.attack > 0.1 or band_peak > 0.18 or band_spread > 0.08:
        return "music"
    if frame.rms < 0.055 and frame.attack < 0.045:
        return "book"
    if frame.zcr < 0.11 and frame.attack < 0.085:
        return "speech"
    if frame.rms < 0.11 and band_peak < 0.14:
        return "book"
    return "speech"


def _effective_fps(config: AppConfig, frame: AudioFrame) -> float:
    target = max(4, int(getattr(config, "fps", 24)))
    if getattr(config, "profile", "atlas") == "power-save":
        target = min(target, 18)
    elif getattr(config, "profile", "atlas") == "atlas":
        target = min(target, 30)
    if frame.rms < 0.028 and frame.attack < 0.02:
        target = min(target, 8)
    return float(target)


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    pair_index = 1
    available_colors = max(0, getattr(curses, "COLORS", 0))
    for name, palette in PALETTES.items():
        fallback = PALETTE_FALLBACKS.get(name, palette)
        for bucket, fg in enumerate(palette):
            resolved = fg if fg < available_colors else fallback[bucket]
            curses.init_pair(pair_index, resolved, -1)
            pair_index += 1


def _palette_attr(name: str, bucket: int) -> int:
    names = tuple(PALETTES.keys())
    try:
        palette_index = names.index(name)
    except ValueError:
        palette_index = names.index("amber")
    bucket = max(0, min(bucket, 3))
    return curses.color_pair(1 + palette_index * 4 + bucket)


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


def _compact_layout(config: AppConfig | None) -> bool:
    render = getattr(config, "render", None)
    return _env_flag("COMPACT") or bool(getattr(render, "compact", False))


def _visual_limits(config: AppConfig | None) -> tuple[int | None, int | None]:
    render = getattr(config, "render", None)
    width = _positive_env_int("MAX_WIDTH") or getattr(render, "max_width", None)
    height = _positive_env_int("MAX_HEIGHT") or getattr(render, "max_height", None)
    return width, height


def _clamp_visual_size(width: int, height: int, config: AppConfig | None) -> tuple[int, int]:
    max_width, max_height = _visual_limits(config)
    if max_width:
        width = min(width, max_width)
    if max_height:
        height = min(height, max_height)
    return max(1, width), max(1, height)


def _compute_layout(rows: int, cols: int, dock_open: bool, config: AppConfig | None = None) -> Layout:
    # Controls are backstage: a closed dock consumes no tile area. When opened,
    # wide terminals place it beside the organism and short terminals below it.
    if not dock_open:
        vis_w, vis_h = _clamp_visual_size(cols, max(1, rows - 1), config)
        return Layout(0, 0, vis_h, vis_w, vis_h, vis_w, 0, 0, "hidden")

    side_layout = cols >= 96
    if side_layout:
        dock_w = min(38, max(1, cols - 1))
        vis_h = max(1, rows - 1)
        vis_w = max(1, cols - dock_w)
        vis_w, vis_h = _clamp_visual_size(vis_w, vis_h, config)
        return Layout(0, 0, vis_h, vis_w, 0, vis_w, vis_h, dock_w, "right")
    requested_dock_h = 12 if rows >= 16 else 1
    dock_h = min(requested_dock_h, max(1, rows - 2))
    vis_h = max(1, rows - dock_h - 1)
    vis_w, vis_h = _clamp_visual_size(cols, vis_h, config)
    return Layout(0, 0, vis_h, vis_w, vis_h, 0, dock_h, vis_w, "bottom")


def _effective_cell_width(config: AppConfig, width: int, height: int) -> int:
    configured = max(1, int(getattr(config.render, "scale", 1)))
    if not _compact_layout(config):
        return configured

    # Compact mode budgets simulated cells by area. A tiny i3 tile therefore
    # gains detail while a large tile avoids an unnecessary CPU/output spike.
    target_cells = _positive_env_int("TARGET_CELLS") or COMPACT_TARGET_CELLS
    target_cells = max(180, min(1400, target_cells))
    adaptive = max(1, math.ceil((max(1, width) * max(1, height)) / target_cells))
    return max(1, min(5, adaptive))


def _style_name(value) -> str:
    glyphs = _glyph_text(value)
    for name, preset in STYLE_PRESETS.items():
        if glyphs == preset:
            return name
    return "custom"


def _scene_name_for_config(config: AppConfig) -> str:
    palette = _palette_name(getattr(config.render, "palette", "amber"))
    style = _style_name(getattr(config.render, "glyphs", GLYPH_PRESETS[0]))
    scale = int(getattr(config.render, "scale", 1))
    colors = int(getattr(config.render, "color_steps", 4))
    for name, scene in SCENES.items():
        if (
            scene["palette"] == palette
            and scene["style"] == style
            and scene["scale"] == scale
            and scene["colors"] == colors
        ):
            return name
    return "custom"


def _apply_scene(config: AppConfig, scene_name: str) -> None:
    scene = SCENES[scene_name]
    setattr(config.render, "palette", scene["palette"])
    setattr(config.render, "glyphs", STYLE_PRESETS[str(scene["style"])])
    setattr(config.render, "scale", int(scene["scale"]))
    setattr(config.render, "color_steps", int(scene["colors"]))


def _apply_profile_in_place(config: AppConfig, profile_name: str) -> None:
    updated = apply_profile(config, profile_name)
    config.fps = updated.fps
    config.theme = updated.theme
    config.profile = updated.profile
    config.content_mode = updated.content_mode
    config.audio = updated.audio
    config.render = updated.render
    config.lava = updated.lava


def _product_preset_name_for_config(config: AppConfig) -> str:
    scene = _scene_name_for_config(config)
    profile = getattr(config, "profile", "atlas")
    content = getattr(config, "content_mode", "auto")
    fps = int(getattr(config, "fps", 24))
    analysis = getattr(config.audio, "analysis", "atlas")
    reactivity = _reactivity_name(float(getattr(config.lava, "reactivity", 1.0)))
    density = _density_name(int(getattr(config.lava, "blobs", 5)))
    for name, preset in PRODUCT_PRESETS.items():
        if (
            preset["scene"] == scene
            and preset["profile"] == profile
            and preset["content"] == content
            and int(preset["fps"]) == fps
            and preset["analysis"] == analysis
            and preset["reactivity"] == reactivity
            and preset["density"] == density
        ):
            return name
    return "custom"


def _apply_product_preset(config: AppConfig, preset_name: str) -> None:
    preset = PRODUCT_PRESETS[preset_name]
    _apply_profile_in_place(config, str(preset["profile"]))
    _apply_scene(config, str(preset["scene"]))
    setattr(config, "content_mode", str(preset["content"]))
    setattr(config, "fps", int(preset["fps"]))
    setattr(config.audio, "analysis", str(preset["analysis"]))
    if preset["analysis"] == "bands":
        setattr(config.audio, "sample_rate", max(config.audio.sample_rate, 22050))
        setattr(config.audio, "frame_size", min(config.audio.frame_size, 1024))
    _set_reactivity(config, str(preset["reactivity"]))
    _set_density(config, str(preset["density"]))


def _make_controls(config: AppConfig) -> dict[str, list[Control]]:
    scene_state = {"name": _scene_name_for_config(config)}
    preset_state = {"name": _product_preset_name_for_config(config)}

    def refresh_states(config: AppConfig) -> None:
        scene_state["name"] = _scene_name_for_config(config)
        preset_state["name"] = _product_preset_name_for_config(config)

    def choice_control(
        label: str,
        getter: Callable[[AppConfig], str],
        setter: Callable[[AppConfig, str], None],
        choices: Sequence[str],
        *,
        restart_audio: bool = False,
        reset_lava: bool = False,
        on_change: Callable[[AppConfig, str], None] | None = None,
    ) -> Control:
        def adjust(config: AppConfig, delta: int, ui: UiState) -> str:
            new_value = _cycle(getter(config), choices, delta)
            setter(config, new_value)
            if on_change:
                on_change(config, new_value)
            if restart_audio:
                ui.restart_audio = True
            if reset_lava:
                ui.reset_lava = True
            return f"{label}: {new_value}"

        return Control(label=label, value=lambda config: getter(config), adjust=adjust)

    def int_control(
        label: str,
        getter: Callable[[AppConfig], int],
        setter: Callable[[AppConfig, int], None],
        *,
        low: int,
        high: int,
        step: int,
        restart_audio: bool = False,
        reset_lava: bool = False,
        on_change: Callable[[AppConfig, int], None] | None = None,
    ) -> Control:
        def adjust(config: AppConfig, delta: int, ui: UiState) -> str:
            current = getter(config)
            new_value = max(low, min(high, current + delta * step))
            setter(config, new_value)
            if on_change:
                on_change(config, new_value)
            if restart_audio:
                ui.restart_audio = True
            if reset_lava:
                ui.reset_lava = True
            return f"{label}: {new_value}"

        return Control(label=label, value=lambda config: str(getter(config)), adjust=adjust)

    def bool_control(label: str, getter: Callable[[AppConfig], bool], setter: Callable[[AppConfig, bool], None]) -> Control:
        def adjust(config: AppConfig, delta: int, ui: UiState) -> str:
            value = not getter(config)
            setter(config, value)
            return f"{label}: {'on' if value else 'off'}"

        return Control(label=label, value=lambda config: "on" if getter(config) else "off", adjust=adjust)

    def set_preset(config: AppConfig, preset_name: str) -> None:
        _apply_product_preset(config, preset_name)
        refresh_states(config)

    def mark_state(config: AppConfig, _value) -> None:
        refresh_states(config)

    return {
        "Modes": [
            choice_control(
                "mode",
                lambda c: preset_state["name"],
                set_preset,
                tuple(PRODUCT_PRESETS.keys()),
                restart_audio=True,
                reset_lava=True,
            ),
            choice_control(
                "react",
                lambda c: _reactivity_name(float(getattr(c.lava, "reactivity", 1.0))),
                _set_reactivity,
                tuple(REACTIVITY_MODES.keys()),
                reset_lava=True,
                on_change=mark_state,
            ),
            choice_control(
                "source",
                lambda c: getattr(c, "content_mode", "auto"),
                lambda c, v: setattr(c, "content_mode", v),
                CONTENT_MODES,
                reset_lava=True,
                on_change=mark_state,
            ),
        ],
        "Look": [
            choice_control(
                "palette",
                lambda c: _palette_name(getattr(c.render, "palette", "amber")),
                lambda c, v: setattr(c.render, "palette", _palette_name(v)),
                tuple(PALETTES.keys()),
                on_change=mark_state,
            ),
            choice_control(
                "style",
                lambda c: _style_name(getattr(c.render, "glyphs", GLYPH_PRESETS[0])),
                lambda c, v: setattr(c.render, "glyphs", STYLE_PRESETS.get(v, STYLE_PRESETS["soft"])),
                tuple(STYLE_PRESETS.keys()),
                reset_lava=True,
                on_change=mark_state,
            ),
            choice_control(
                "density",
                lambda c: _density_name(int(getattr(c.lava, "blobs", 5))),
                _set_density,
                tuple(DENSITY_MODES.keys()),
                reset_lava=True,
                on_change=mark_state,
            ),
            int_control(
                "detail",
                lambda c: int(getattr(c.render, "scale", 1)),
                lambda c, v: setattr(c.render, "scale", v),
                low=1,
                high=4,
                step=1,
                reset_lava=True,
                on_change=mark_state,
            ),
            int_control(
                "colors",
                lambda c: int(getattr(c.render, "color_steps", 4)),
                lambda c, v: setattr(c.render, "color_steps", v),
                low=2,
                high=4,
                step=1,
                on_change=mark_state,
            ),
            bool_control(
                "stats",
                lambda c: bool(getattr(c.render, "show_stats", True)),
                lambda c, v: setattr(c.render, "show_stats", v),
            ),
        ],
        "System": [
            choice_control(
                "profile",
                lambda c: getattr(c, "profile", "atlas"),
                lambda c, v: setattr(c, "profile", v),
                PROFILE_NAMES,
                restart_audio=True,
                reset_lava=True,
                on_change=lambda c, v: (_apply_profile_in_place(c, v), mark_state(c, v)),
            ),
            int_control(
                "frame",
                lambda c: int(getattr(c.audio, "frame_size", 1024)),
                lambda c, v: setattr(c.audio, "frame_size", v),
                low=256,
                high=4096,
                step=256,
                restart_audio=True,
            ),
            int_control(
                "fps",
                lambda c: int(getattr(c, "fps", 24)),
                lambda c, v: setattr(c, "fps", v),
                low=8,
                high=60,
                step=2,
                on_change=mark_state,
            ),
            choice_control(
                "analysis",
                lambda c: getattr(c.audio, "analysis", "atlas"),
                lambda c, v: setattr(c.audio, "analysis", v),
                ANALYSIS_MODES,
                restart_audio=True,
                on_change=mark_state,
            ),
            choice_control(
                "backend",
                lambda c: getattr(c.audio, "backend", "auto"),
                lambda c, v: setattr(c.audio, "backend", v),
                BACKEND_MODES,
                restart_audio=True,
            ),
        ],
    }


def _interpolated_row_value(source: Sequence[float], screen_x: int, screen_width: int) -> float:
    if not source:
        return 0.0
    grid_position = screen_x * max(0, len(source) - 1) / max(1, screen_width - 1)
    left = int(grid_position)
    right = min(len(source) - 1, left + 1)
    mix = grid_position - left
    return source[left] * (1.0 - mix) + source[right] * mix


def _visual_shade(value: float, texture: float = 0.0) -> float:
    visible_cutoff = 0.055
    if value <= visible_cutoff:
        return 0.0
    shade = _clamp(((value - visible_cutoff) / (1.0 - visible_cutoff)) ** 0.82)
    return _clamp(shade + texture * shade * (1.0 - shade))


def _semantic_color_bucket(shade: float, attention: float, color_steps: int) -> int:
    """Reserve the final palette color for a local acoustic event."""

    color_steps = max(2, min(4, color_steps))
    if shade <= 0.0:
        return 0
    if color_steps == 2 or attention >= 0.08:
        return color_steps - 1
    return max(1, min(color_steps - 2, int(shade * (color_steps - 1))))


def _draw_visual(
    win: curses.window,
    field: LavaField,
    config: AppConfig,
    frame: AudioFrame,
    ui: UiState,
) -> None:
    height, width = win.getmaxyx()
    palette = _palette_name(getattr(config.render, "palette", "amber"))
    glyphs = _glyph_text(getattr(config.render, "glyphs", GLYPH_PRESETS[0]))
    color_steps = max(2, min(4, int(getattr(config.render, "color_steps", 4))))
    cell_w = _effective_cell_width(config, width, height)
    grid_w = max(10, width // cell_w)
    grid_h = max(6, height)
    field.resize(grid_w, grid_h)

    # Group adjacent cells with the same color attribute. Fewer addnstr calls
    # matter more than the arithmetic when a terminal redraws thirty times/sec.
    for y in range(min(height, field.h)):
        source = field.buffers[y]
        attention_source = field.attention_buffers[y]
        screen_y = y
        run_text = ""
        run_attr = -1
        run_start = 0
        for screen_x in range(width):
            value = _interpolated_row_value(source, screen_x, width)
            attention = _interpolated_row_value(attention_source, screen_x, width)
            texture = math.sin(screen_x * 1.73 + y * 2.31 + field.phase * 3.2) * 0.035
            shade = _clamp(_visual_shade(value, texture) + attention * 0.10)
            level = int(shade * (len(glyphs) - 1)) if glyphs else 0
            if shade > 0.0:
                level = max(1, level)
            char = glyphs[level] if level > 0 else " "
            bucket = _semantic_color_bucket(shade, attention, color_steps)
            attr = _palette_attr(palette, bucket)
            if char != " " and shade < 0.30:
                attr |= curses.A_DIM
            elif attention > 0.58:
                attr |= curses.A_BOLD
            if attr != run_attr and run_text:
                _safe_add(win, screen_y, run_start, run_text, run_attr)
                run_text = ""
                run_start = screen_x
            run_attr = attr
            run_text += char
        if run_text:
            _safe_add(win, screen_y, run_start, run_text, run_attr)

    if getattr(config.render, "show_stats", True):
        stats = [
            f"mode {ui.resolved_mode}",
            f"rms {frame.rms:0.2f}",
            f"attack {frame.attack:0.2f}",
            f"gain x{field.response_gain:0.2f}",
            f"l/m/h {field.last_low:0.1f}/{field.last_mid:0.1f}/{field.last_high:0.1f}",
            f"kick {field.last_kick:0.1f}",
            f"voice {field.last_voice:0.1f}",
            f"spec {max(field.spectral_bands) if field.spectral_bands else 0.0:0.1f}",
            f"hit {max(field.spectral_hits) if field.spectral_hits else 0.0:0.1f}",
            f"impact {field.impact:0.1f}",
            f"zcr {frame.zcr:0.2f}",
        ]
        for idx, line in enumerate(stats):
            if idx >= height:
                break
            _safe_add(win, idx, 1, line, curses.A_DIM)


def _draw_dock(
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
            for idx, ch in enumerate(label):
                _safe_add(win, min(idx + 1, height - 1), 0, ch, curses.A_BOLD)
            ui.buttons.append(Button(0, 0, min(height - 1, len(label) + 1), min(width - 1, 2), "toggle_dock"))
        else:
            _safe_add(win, 0, 1, label, curses.A_BOLD)
            ui.buttons.append(Button(0, 0, 0, min(width - 1, len(label) + 2), "toggle_dock"))
        win.noutrefresh()
        return

    title = " lavatune companion "
    _safe_add(win, 0, 1, title, curses.A_BOLD)
    close_x = max(1, width - 5)
    _safe_add(win, 0, close_x, "[x]", curses.A_BOLD)
    ui.buttons.append(Button(0, close_x, 0, min(width - 1, close_x + 2), "toggle_dock"))

    tab_x = 1
    for index, name in enumerate(TAB_NAMES):
        text = f" {name} "
        attr = curses.A_REVERSE if index == ui.tab_index else curses.A_NORMAL
        _safe_add(win, 2, tab_x, text, attr)
        ui.buttons.append(Button(2, tab_x, 2, min(width - 1, tab_x + len(text) - 1), f"tab:{index}"))
        tab_x += len(text) + 1

    rows = controls[TAB_NAMES[ui.tab_index]]
    ui.selected_row = max(0, min(ui.selected_row, len(rows) - 1))

    y = 4
    for index, control in enumerate(rows):
        selected = index == ui.selected_row
        attr = curses.A_BOLD if selected else curses.A_NORMAL
        value = _display_text(control.value(config))
        _safe_add(win, y, 2, control.label.ljust(10), attr)

        left_x = max(14, width - 21)
        value_x = left_x + 4
        right_x = max(value_x + len(value) + 2, width - 5)

        _safe_add(win, y, left_x, "[-]", curses.A_REVERSE if selected else curses.A_DIM)
        _safe_add(win, y, value_x, value[: max(6, width - value_x - 6)], attr)
        _safe_add(win, y, right_x, "[+]", curses.A_REVERSE if selected else curses.A_DIM)

        ui.buttons.append(Button(y, 2, y, min(width - 1, width - 2), f"select:{index}"))
        ui.buttons.append(Button(y, left_x, y, min(width - 1, left_x + 2), f"adjust:{index}", -1))
        ui.buttons.append(Button(y, right_x, y, min(width - 1, right_x + 2), f"adjust:{index}", 1))
        y += 2
        if y >= height - 4:
            break

    win.noutrefresh()


def _draw_status(stdscr: curses.window, config: AppConfig, ui: UiState, frame: AudioFrame, field: LavaField) -> None:
    rows, cols = stdscr.getmaxyx()
    preset = _product_preset_name_for_config(config)
    react = _reactivity_name(float(getattr(config.lava, "reactivity", 1.0)))
    state = f"calibrating {min(field.calibration_frames, 72)}/72" if field.calibration_frames < 72 else f"tracking x{field.response_gain:0.2f}"
    active_status = ui.active_status()
    media_status = ui.media.display()
    if active_status:
        status = active_status
    elif media_status:
        status = media_status
    elif getattr(config.render, "show_stats", True):
        status = (
            f"{preset} | {react} | {ui.resolved_mode} | {state} | "
            f"tone {field.forces.tone:0.2f} | tempo {field.forces.tempo:0.2f} | "
            f"pulse {field.forces.pulse:0.2f} | "
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


def _handle_action(
    action: str,
    delta: int,
    config: AppConfig,
    ui: UiState,
    controls: dict[str, list[Control]],
) -> None:
    if action == "toggle_dock":
        ui.dock_open = not ui.dock_open
        ui.set_status("dock open" if ui.dock_open else "dock hidden")
        return
    if action.startswith("tab:"):
        ui.tab_index = int(action.split(":", 1)[1]) % len(TAB_NAMES)
        ui.selected_row = 0
        ui.set_status(f"tab {TAB_NAMES[ui.tab_index].lower()}")
        return
    if action.startswith("select:"):
        ui.selected_row = int(action.split(":", 1)[1])
        label = controls[TAB_NAMES[ui.tab_index]][ui.selected_row].label
        ui.set_status(f"selected {label}")
        return
    if action.startswith("adjust:"):
        index = int(action.split(":", 1)[1])
        ui.selected_row = index
        message = controls[TAB_NAMES[ui.tab_index]][index].adjust(config, delta, ui)
        ui.set_status(message)


def _handle_mouse(
    event: tuple[int, int, int, int, int],
    layout: Layout,
    ui: UiState,
    config: AppConfig,
    controls: dict[str, list[Control]],
) -> None:
    _, mx, my, _, bstate = event
    ui.last_mouse = (my, mx)
    local_y = my - layout.dock_y
    local_x = mx - layout.dock_x
    inside_dock = ui.dock_open or (layout.side == "right" and mx >= layout.dock_x) or (layout.side == "bottom" and my >= layout.dock_y)

    if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
        if not inside_dock:
            return
        for button in reversed(ui.buttons):
            if button.contains(local_y, local_x) and button.action.startswith(("adjust:", "select:")):
                ui.selected_row = int(button.action.split(":", 1)[1])
                break
        _handle_action(f"adjust:{ui.selected_row}", -1, config, ui, controls)
        return
    if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
        if not inside_dock:
            return
        for button in reversed(ui.buttons):
            if button.contains(local_y, local_x) and button.action.startswith(("adjust:", "select:")):
                ui.selected_row = int(button.action.split(":", 1)[1])
                break
        _handle_action(f"adjust:{ui.selected_row}", 1, config, ui, controls)
        return

    primary_mask = curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED
    if not (bstate & primary_mask):
        return
    sig = (mx, my, bstate & primary_mask)
    now = time.monotonic()
    if ui.last_mouse_sig == sig and now - ui.last_mouse_at < 0.2:
        return
    ui.last_mouse_sig = sig
    ui.last_mouse_at = now

    if inside_dock:
        for button in reversed(ui.buttons):
            if button.contains(local_y, local_x):
                _handle_action(button.action, button.delta, config, ui, controls)
                return


def _handle_key(key: int, config: AppConfig, ui: UiState, controls: dict[str, list[Control]]) -> None:
    if key in (ord("q"), ord("Q")):
        ui.quit_requested = True
        return
    if key == ord("\t"):
        ui.dock_open = not ui.dock_open
        ui.set_status("dock open" if ui.dock_open else "dock hidden")
        return
    if key == curses.KEY_BTAB:
        ui.tab_index = (ui.tab_index - 1) % len(TAB_NAMES)
        ui.selected_row = 0
        ui.set_status(f"tab {TAB_NAMES[ui.tab_index].lower()}")
        return
    if key == curses.KEY_RIGHT:
        if ui.dock_open:
            _handle_action(f"adjust:{ui.selected_row}", 1, config, ui, controls)
        else:
            ui.dock_open = True
            ui.set_status("dock open")
        return
    if key == curses.KEY_LEFT:
        if ui.dock_open:
            _handle_action(f"adjust:{ui.selected_row}", -1, config, ui, controls)
        return
    if key == curses.KEY_UP:
        ui.selected_row = max(0, ui.selected_row - 1)
        return
    if key == curses.KEY_DOWN:
        rows = controls[TAB_NAMES[ui.tab_index]]
        ui.selected_row = min(len(rows) - 1, ui.selected_row + 1)
        return
    if key in (curses.KEY_ENTER, 10, 13, ord(" ")):
        _handle_action(f"adjust:{ui.selected_row}", 1, config, ui, controls)
        return
    if key in (ord("["),):
        ui.tab_index = (ui.tab_index - 1) % len(TAB_NAMES)
        ui.selected_row = 0
        ui.set_status(f"tab {TAB_NAMES[ui.tab_index].lower()}")
        return
    if key in (ord("]"),):
        ui.tab_index = (ui.tab_index + 1) % len(TAB_NAMES)
        ui.selected_row = 0
        ui.set_status(f"tab {TAB_NAMES[ui.tab_index].lower()}")
        return


def _handle_terminal_sequence(key: int, ui: UiState) -> bool:
    if not ui.escape_buffer and key != 27:
        return False

    now = time.monotonic()
    if ui.escape_buffer and now - ui.escape_started_at > 0.2:
        ui.escape_buffer = ""

    if not ui.escape_buffer:
        ui.escape_buffer = "\x1b"
        ui.escape_started_at = now
        return True

    if key < 0 or key > 255:
        ui.escape_buffer = ""
        return False

    ui.escape_buffer += chr(key)
    ui.escape_started_at = now

    if ui.escape_buffer == "\x1b[I":
        ui.escape_buffer = ""
        return True
    if ui.escape_buffer == "\x1b[O":
        ui.escape_buffer = ""
        ui.quit_requested = True
        return True
    if "\x1b[I".startswith(ui.escape_buffer) or "\x1b[O".startswith(ui.escape_buffer):
        return True

    ui.escape_buffer = ""
    return True


def _run_curses(stdscr: curses.window, config: AppConfig, demo: bool) -> int:
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.nodelay(True)
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    curses.mouseinterval(120)
    _init_colors()
    _set_focus_reporting(True)

    ui = UiState()
    controls = _make_controls(config)
    field = LavaField()
    last_frame = _silent_frame()
    capture = _build_capture(config, demo)
    media = MediaWatcher()
    media.start()
    ui.audio_status = capture.status()
    ui.set_status(ui.audio_status, ttl=2.5)

    next_draw = 0.0
    try:
        while not ui.quit_requested:
            # Input stays non-blocking so audio can continue to move the field
            # when there are no keyboard or mouse events.
            while True:
                key = stdscr.getch()
                if key == -1:
                    break
                if key == curses.KEY_MOUSE:
                    try:
                        event = curses.getmouse()
                    except curses.error:
                        event = None
                    if event:
                        rows, cols = stdscr.getmaxyx()
                        layout = _compute_layout(rows, cols, ui.dock_open, config)
                        _handle_mouse(event, layout, ui, config, controls)
                elif _handle_terminal_sequence(key, ui):
                    continue
                elif key == curses.KEY_RESIZE:
                    # Body coordinates are normalized, so resizing only recomposes the field.
                    pass
                else:
                    _handle_key(key, config, ui, controls)

            if ui.restart_audio:
                capture.stop()
                capture = _build_capture(config, demo)
                ui.audio_status = capture.status()
                ui.restart_audio = False
                ui.set_status(ui.audio_status)

            if ui.reset_lava:
                field.clear()
                ui.reset_lava = False

            last_frame = capture.latest()

            ui.resolved_mode = _resolve_mode(getattr(config, "content_mode", "auto"), last_frame)
            ui.media = media.latest()
            now = time.monotonic()
            if now < next_draw:
                time.sleep(min(0.01, next_draw - now))
                continue

            rows, cols = stdscr.getmaxyx()
            if rows < 3 or cols < 4:
                stdscr.erase()
                _safe_add(stdscr, 0, 0, "resizing...", curses.A_DIM)
                stdscr.noutrefresh()
                curses.doupdate()
                next_draw = now + 0.05
                continue

            layout = _compute_layout(rows, cols, ui.dock_open, config)
            cell_w = _effective_cell_width(config, layout.vis_w, layout.vis_h)
            field.resize(
                max(10, layout.vis_w // cell_w),
                max(6, layout.vis_h),
            )
            field.step(
                last_frame,
                ui.resolved_mode,
                getattr(config, "profile", "atlas"),
                float(getattr(config.lava, "reactivity", 1.0)),
                config.lava,
            )

            try:
                vis = stdscr.derwin(layout.vis_h, layout.vis_w, layout.vis_y, layout.vis_x)
                dock = (
                    stdscr.derwin(layout.dock_h, layout.dock_w, layout.dock_y, layout.dock_x)
                    if layout.dock_h > 0 and layout.dock_w > 0
                    else None
                )
            except curses.error:
                next_draw = now + 0.05
                continue

            stdscr.erase()
            vis.erase()
            _draw_visual(vis, field, config, last_frame, ui)
            vis.noutrefresh()
            if dock is not None:
                _draw_dock(dock, config, ui, controls, layout)
            _draw_status(stdscr, config, ui, last_frame, field)
            curses.doupdate()

            next_draw = now + (1.0 / _effective_fps(config, last_frame))
    finally:
        _set_focus_reporting(False)
        media.stop()
        capture.stop()

    return 0


class LavaTuneApp:
    """Public application wrapper used by the command-line entry point."""

    def __init__(self, config: AppConfig, demo_mode: bool = False) -> None:
        self.config = config
        self.demo_mode = demo_mode

    def run(self) -> int:
        return curses.wrapper(_run_curses, self.config, self.demo_mode)
