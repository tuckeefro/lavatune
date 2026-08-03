"""Curses interface joining audio capture, organism physics, and terminal drawing."""

from __future__ import annotations

import curses
import math
import os
import select
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .audio import AudioCapture, AudioFrame, DemoAudioCapture
from .config import (
    CONTENT_MODES,
    PROFILE_NAMES,
    AppConfig,
    apply_profile,
    save_preferences,
)
from .materials import (
    AFTERGLOW_NAMES,
    EDGE_NAMES,
    MATERIAL_NAMES,
    WEIGHT_NAMES,
    MaterialStyle,
    material_for,
    normalize_glyph_ramp,
    visual_shade,
)
from .media import MediaInfo, MediaWatcher
from .organism import (
    AffectiveState,
    AudioForces,
    behavior_for_context,
    clamp,
)
from .runtime import LavaField, ReactionLatch, RuntimeMetrics
from .text import sanitize_display_text

TAB_NAMES = ("Listening",)
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
        "analysis": "bands",
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
    return normalize_glyph_ramp(value)


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


def _effective_fps(
    config: AppConfig,
    frame: AudioFrame,
    forces: AudioForces | None = None,
) -> float:
    configured = max(1, int(getattr(config, "fps", 22)))
    profile = getattr(config, "profile", "atlas")
    profile_cap = 6 if profile == "power-save" else 14 if profile == "atlas" else 16
    band_peak = max(frame.bands) if frame.bands else 0.0
    mapped = forces or AudioForces()
    mapped_peak = max(mapped.bass, mapped.voice, mapped.detail, mapped.energy)
    if (
        frame.attack >= 0.08
        or mapped.transient >= 0.16
        or mapped.pulse >= 0.18
        or mapped.rhythm_density >= 0.28
        or mapped.rhythm_impulse >= 0.18
    ):
        activity_target = 14
    elif frame.rms >= 0.10 or band_peak >= 0.20 or mapped_peak >= 0.28:
        activity_target = 8
    elif (
        frame.rms >= 0.030
        or band_peak >= 0.070
        or frame.attack >= 0.025
        or mapped_peak >= 0.10
    ):
        activity_target = 4
    else:
        activity_target = 2
    return float(min(configured, profile_cap, activity_target))


def _should_draw_early(next_draw: float, now: float, target_fps: float) -> bool:
    """Wake a quiet cadence when new audio needs a faster visual response."""

    return next_draw - now > 1.0 / max(1.0, target_fps)


@dataclass
class FrameScheduler:
    state: str = "resting"
    burst_until: float = 0.0
    engaged_until: float = 0.0
    breathing_until: float = 0.0
    immediate: bool = True
    last_release: float = 0.0
    last_snap: float = 0.0

    def observe(
        self,
        frame: AudioFrame,
        forces: AudioForces,
        affect: AffectiveState,
        reaction_level: float,
        now: float,
    ) -> None:
        band_peak = max(frame.bands, default=0.0)
        mapped_peak = max(forces.bass, forces.voice, forces.detail, forces.energy)
        release_started = affect.release >= 0.16 and self.last_release < 0.16
        snap_started = affect.snap >= 0.16 and self.last_snap < 0.16
        self.last_release = affect.release
        self.last_snap = affect.snap
        burst = (
            reaction_level >= 0.14
            or frame.attack >= 0.08
            or affect.novelty >= 0.16
            or forces.rhythm_density >= 0.28
            or forces.rhythm_impulse >= 0.18
            or release_started
            or snap_started
        )
        engaged = frame.rms >= 0.10 or band_peak >= 0.20 or mapped_peak >= 0.28
        breathing = frame.rms >= 0.025 or band_peak >= 0.065 or mapped_peak >= 0.09
        if burst:
            self.burst_until = max(self.burst_until, now + 0.22)
            self.engaged_until = max(self.engaged_until, now + 0.72)
            self.immediate = True
        elif engaged:
            self.engaged_until = max(self.engaged_until, now + 0.62)
        elif breathing:
            self.breathing_until = max(self.breathing_until, now + 0.80)
        self.refresh(now)

    def refresh(self, now: float) -> str:
        if now < self.burst_until:
            self.state = "burst"
        elif now < self.engaged_until:
            self.state = "engaged"
        elif now < self.breathing_until:
            self.state = "breathing"
        else:
            self.state = "resting"
        return self.state

    def target_fps(self, config: AppConfig, now: float) -> float:
        state = self.refresh(now)
        desired = {"resting": 2, "breathing": 4, "engaged": 8, "burst": 14}[state]
        profile = getattr(config, "profile", "atlas")
        cap = 6 if profile == "power-save" else 14 if profile == "atlas" else 16
        return float(min(max(1, int(getattr(config, "fps", 22))), cap, desired))

    def physics_fps(self, now: float) -> float:
        state = self.refresh(now)
        return float({"resting": 2, "breathing": 4, "engaged": 6, "burst": 8}[state])

    def consume_immediate(self) -> bool:
        immediate = self.immediate
        self.immediate = False
        return immediate


def _wait_for_activity(
    capture: AudioCapture | DemoAudioCapture,
    timeout: float,
) -> None:
    descriptors: list[int] = []
    try:
        descriptors.append(sys.stdin.fileno())
    except (AttributeError, OSError, ValueError):
        pass
    capture_descriptor = capture.fileno()
    if capture_descriptor is not None:
        descriptors.append(capture_descriptor)
    if not descriptors:
        time.sleep(max(0.0, timeout))
        return
    try:
        readable, _, _ = select.select(descriptors, [], [], max(0.0, timeout))
    except (OSError, ValueError):
        time.sleep(min(0.05, max(0.0, timeout)))
        return
    if capture_descriptor is not None and capture_descriptor in readable:
        capture.consume_signal()


def _init_colors() -> None:
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
        _PALETTE_PAIR_IDS.update({name: (0,) * len(palette) for name, palette in PALETTES.items()})
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


def _palette_attr(name: str, bucket: int) -> int:
    bucket = max(0, min(bucket, 3))
    pair_ids = _PALETTE_PAIR_IDS.get(name) or _PALETTE_PAIR_IDS.get("soft-afterglow")
    pair_id = pair_ids[bucket] if pair_ids and bucket < len(pair_ids) else 0
    return curses.color_pair(pair_id)


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
    for name, scene in SCENES.items():
        if scene["palette"] == palette and scene["style"] == style:
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
    profile = getattr(config, "profile", "atlas")
    content = getattr(config, "content_mode", "auto")
    fps = int(getattr(config, "fps", 24))
    analysis = getattr(config.audio, "analysis", "atlas")
    reactivity = _reactivity_name(float(getattr(config.lava, "reactivity", 1.0)))
    density = _density_name(int(getattr(config.lava, "blobs", 5)))
    for name, preset in PRODUCT_PRESETS.items():
        if (
            preset["profile"] == profile
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
    setattr(config, "content_mode", str(preset["content"]))
    setattr(config, "fps", int(preset["fps"]))
    setattr(config.audio, "analysis", str(preset["analysis"]))
    if preset["analysis"] == "bands":
        minimum_rate = 22050 if preset["profile"] == "responsive" else 16000
        setattr(config.audio, "sample_rate", max(config.audio.sample_rate, minimum_rate))
        setattr(config.audio, "frame_size", min(config.audio.frame_size, 1024))
    _set_reactivity(config, str(preset["reactivity"]))
    _set_density(config, str(preset["density"]))


def _set_listening_context(config: AppConfig, context: str) -> None:
    """Apply the only daily choice; analysis remains a shared raw signal."""

    if context not in {"podcast", "radio", "music", "microphone"}:
        context = "music"
    config.listening_context = context
    config.content_mode = "music"
    config.audio.capture_route = "microphone" if context == "microphone" else "system"


def _make_controls(config: AppConfig) -> dict[str, list[Control]]:
    preset_state = {"name": _product_preset_name_for_config(config)}

    def refresh_states(config: AppConfig) -> None:
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
        "Listening": [
            choice_control(
                "listening",
                lambda c: getattr(c, "listening_context", "music"),
                _set_listening_context,
                ("podcast", "radio", "music", "microphone"),
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
    return visual_shade(value, texture)


def _semantic_color_bucket(
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
        # The two ordinary body colors become opposing sides of a rotating
        # surface. The last color remains reserved for acoustic attention.
        return max(1, min(color_steps - 2, 1 + int(clamp(face) * (color_steps - 2))))
    return max(1, min(color_steps - 2, int(shade * (color_steps - 1))))


def _unicode_output_supported(encoding: str | None = None) -> bool:
    resolved = (encoding or sys.stdout.encoding or "").replace("-", "").lower()
    return "utf8" in resolved


def _changed_cell_runs(
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


def _changed_sparse_runs(
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


def _draw_visual(
    win: curses.window,
    field: LavaField,
    config: AppConfig,
    frame: AudioFrame,
    ui: UiState,
    cache: VisualCache | None = None,
) -> None:
    height, width = win.getmaxyx()
    palette = _palette_name(getattr(config.render, "palette", "amber"))
    color_steps = max(2, min(4, int(getattr(config.render, "color_steps", 4))))
    material = material_for(
        getattr(config.render, "material", "text"),
        unicode_supported=_unicode_output_supported(),
    )
    style = MaterialStyle(
        glyphs=_glyph_text(getattr(config.render, "glyphs", GLYPH_PRESETS[0])),
        weight=getattr(config.render, "weight", "balanced"),
        edge=getattr(config.render, "edge", "soft"),
        afterglow=getattr(config.render, "afterglow", "present"),
    )
    material_started = time.perf_counter()
    current_cells: dict[tuple[int, int], tuple[str, int]] = {}
    presentation = field.presentation_frame()

    def add_cell(y: int, x: int, cell) -> None:
        if cell.glyph == " ":
            return
        bucket = _semantic_color_bucket(
            cell.shade, cell.attention, color_steps, cell.face
        )
        attr = _palette_attr(palette, bucket)
        if cell.shade < 0.30:
            attr |= curses.A_DIM
        elif cell.attention > 0.58:
            attr |= curses.A_BOLD
        current_cells[(y, x)] = (cell.glyph, attr)

    if material.name == "wax":
        span_rows = material.render_spans(
            field.wax,
            width,
            height,
            style,
            presentation.phase,
            float(getattr(config.render, "cell_aspect", 1.85)),
        )
        for y, spans in span_rows.items():
            for span in spans:
                for offset, cell in enumerate(span.cells):
                    add_cell(y, span.start + offset, cell)
    elif material.name in {"fluid", "volume"}:
        span_rows = material.render_spans(
            presentation.bodies,
            presentation.forces,
            width,
            height,
            style,
            presentation.phase,
            float(getattr(config.render, "cell_aspect", 1.85)),
        )
        for y, spans in span_rows.items():
            for span in spans:
                for offset, cell in enumerate(span.cells):
                    add_cell(y, span.start + offset, cell)
    else:
        cell_rows = material.render(
            field.field_frame,
            width,
            height,
            style,
            field.phase,
        )
        for y, cells in enumerate(cell_rows):
            for x, cell in enumerate(cells):
                add_cell(y, x, cell)
    field.metrics.material_seconds += time.perf_counter() - material_started

    cache_key = (
        width,
        height,
        material.name,
        palette,
        color_steps,
        style,
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
    blank_attr = _palette_attr(palette, 0)
    for y, start, text, attr in _changed_sparse_runs(
        previous_cells, current_cells, blank_attr
    ):
        _safe_add(win, y, start, text, attr)
        changed_cells += len(text)
        written_runs += 1

    if cache is not None:
        cache.key = cache_key
        cache.cells = current_cells
    field.metrics.draws += 1
    field.metrics.changed_cells += changed_cells
    field.metrics.written_runs += written_runs
    field.metrics.terminal_seconds += time.perf_counter() - terminal_started

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
        if cache is not None:
            cache.clear()


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
    elif getattr(config, "listening_context", "music") == "microphone":
        status = "lavatune | mic active"
    elif media_status:
        status = media_status
    elif getattr(config.render, "show_stats", True):
        status = (
            f"{preset} | {react} | {ui.resolved_mode} | {state} | "
            f"tone {field.forces.tone:0.2f} | tempo {field.forces.tempo:0.2f} | "
            f"pulse {field.forces.pulse:0.2f} | density {field.forces.rhythm_density:0.2f} | "
            f"hold/snap {field.affect.restraint:0.2f}/{field.affect.snap:0.2f} | "
            f"story {field.narrative.expectation:0.1f}/"
            f"{field.narrative.interruption:0.1f}/{field.narrative.resolution:0.1f} | "
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
        tab_name = TAB_NAMES[ui.tab_index % len(TAB_NAMES)]
        label = controls[tab_name][ui.selected_row].label
        ui.set_status(f"selected {label}")
        return
    if action.startswith("adjust:"):
        index = int(action.split(":", 1)[1])
        ui.selected_row = index
        tab_name = TAB_NAMES[ui.tab_index % len(TAB_NAMES)]
        message = controls[tab_name][index].adjust(config, delta, ui)
        ui.set_status(message)
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35


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


def _save_pending_preferences(
    config: AppConfig,
    ui: UiState,
    destination: Path | None,
    *,
    force: bool = False,
) -> None:
    if destination is None or not ui.preferences_dirty:
        return
    if not force and time.monotonic() < ui.preferences_due_at:
        return
    try:
        save_preferences(config, destination)
    except (OSError, TypeError, ValueError) as exc:
        ui.set_status(f"preferences not saved: {exc}", ttl=3.0)
    finally:
        ui.preferences_dirty = False


def _run_curses(
    stdscr: curses.window,
    config: AppConfig,
    demo: bool,
    saved_preferences: Path | None,
) -> int:
    # Cursor visibility is an optional terminal capability.  Some embedded
    # terminals and PTYs reject it even though the rest of curses works.
    try:
        curses.curs_set(0)
    except curses.error:
        pass
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
    media = MediaWatcher() if config.listening_context != "microphone" else None
    if media is not None:
        media.start()
    ui.audio_status = capture.status()
    ui.set_status(ui.audio_status, ttl=2.5)

    next_draw = 0.0
    next_physics = 0.0
    last_audio_sequence = 0
    previous_layout: Layout | None = None
    visual_cache = VisualCache()
    scheduler = FrameScheduler()
    try:
        while not ui.quit_requested:
            field.metrics.wakeups += 1
            interacted = False
            while True:
                key = stdscr.getch()
                if key == -1:
                    break
                interacted = True
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

            if interacted:
                next_draw = 0.0
                scheduler.immediate = True

            _save_pending_preferences(config, ui, saved_preferences)

            if ui.restart_audio:
                capture.stop()
                capture = _build_capture(config, demo)
                if media is not None:
                    media.stop()
                media = (
                    None
                    if config.listening_context == "microphone"
                    else MediaWatcher()
                )
                if media is not None:
                    media.start()
                last_audio_sequence = 0
                ui.audio_status = capture.status()
                ui.restart_audio = False
                ui.set_status(ui.audio_status)

            if ui.reset_lava:
                field.clear()
                next_physics = 0.0
                ui.reset_lava = False

            reactivity = float(getattr(config.lava, "reactivity", 1.0))
            now = time.monotonic()
            pending_audio = capture.drain_after(last_audio_sequence)
            for captured in pending_audio:
                last_audio_sequence = captured.sequence
                last_frame = captured.frame
                ui.resolved_mode = getattr(config, "listening_context", "music")
                field.observe(
                    last_frame,
                    "music",
                    reactivity,
                    behavior_for_context(ui.resolved_mode),
                )
                field.metrics.audio_packets += 1
                scheduler.observe(
                    last_frame,
                    field.forces,
                    field.affect,
                    field.reactions.level,
                    now,
                )
            if not pending_audio:
                scheduler.refresh(now)
            ui.media = media.latest() if media is not None else MediaInfo()
            target_fps = scheduler.target_fps(config, now)
            if scheduler.immediate or _should_draw_early(next_draw, now, target_fps):
                next_draw = now
            if now < next_draw:
                timeout = min(0.25, next_draw - now)
                if isinstance(capture, DemoAudioCapture):
                    timeout = min(timeout, 1.0 / 30.0)
                _wait_for_activity(capture, timeout)
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
            contour_output = (
                getattr(config.render, "material", "text") in {"fluid", "volume", "wax"}
                and _unicode_output_supported()
            )
            embody_posture = (
                getattr(config.render, "material", "text") == "volume"
                and _unicode_output_supported()
            )
            embody_wax = (
                getattr(config.render, "material", "text") == "wax"
                and _unicode_output_supported()
            )
            surface_ripples = (
                getattr(config.render, "material", "text") == "fluid"
                and _unicode_output_supported()
            )
            if contour_output:
                field.resize(max(10, layout.vis_w), max(6, layout.vis_h))
            else:
                cell_w = _effective_cell_width(config, layout.vis_w, layout.vis_h)
                field.resize(
                    max(10, layout.vis_w // cell_w),
                    max(6, layout.vis_h),
                )
            advance_physics = now >= next_physics or scheduler.immediate
            field.step(
                last_frame,
                "music",
                getattr(config, "profile", "atlas"),
                reactivity,
                config.lava,
                float(getattr(config.render, "cell_aspect", 1.85)),
                rasterize=not contour_output,
                advance_physics=advance_physics,
                behavior=behavior_for_context(
                    getattr(config, "listening_context", "music")
                ),
                embody_posture=embody_posture,
                embody_wax=embody_wax,
                surface_ripples=surface_ripples,
            )
            if advance_physics:
                next_physics = now + 1.0 / scheduler.physics_fps(now)

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

            if layout != previous_layout:
                stdscr.erase()
                visual_cache.clear()
                previous_layout = layout
            _draw_visual(vis, field, config, last_frame, ui, visual_cache)
            vis.noutrefresh()
            if dock is not None:
                _draw_dock(dock, config, ui, controls, layout)
            _draw_status(stdscr, config, ui, last_frame, field)
            stdscr.noutrefresh()
            curses.doupdate()

            scheduler.consume_immediate()
            next_draw = time.monotonic() + (1.0 / target_fps)
    finally:
        _save_pending_preferences(config, ui, saved_preferences, force=True)
        _set_focus_reporting(False)
        if media is not None:
            media.stop()
        capture.stop()

    return 0


class LavaTuneApp:
    """Public application wrapper used by the command-line entry point."""

    def __init__(
        self,
        config: AppConfig,
        demo_mode: bool = False,
        saved_preferences: Path | None = None,
    ) -> None:
        self.config = config
        self.demo_mode = demo_mode
        self.saved_preferences = saved_preferences

    def run(self) -> int:
        return curses.wrapper(
            _run_curses,
            self.config,
            self.demo_mode,
            self.saved_preferences,
        )
