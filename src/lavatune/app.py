"""Curses interface joining audio capture, organism physics, and terminal drawing."""

from __future__ import annotations

import curses
import select
import sys
import time
from dataclasses import dataclass
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
    normalize_glyph_ramp,
)
from .media import MediaInfo, MediaWatcher
from .organism import behavior_for_context
from .runtime import LavaField, ReactionLatch, RuntimeMetrics
from .signals import AffectiveState, AudioForces
from .tui import (
    Button,
    COMPACT_TARGET_CELLS,
    Control,
    DAILY_PALETTES,
    Layout,
    PALETTE_FALLBACKS,
    PALETTES,
    TAB_NAMES,
    UiState,
    VisualCache,
    changed_cell_runs as _changed_cell_runs,
    changed_sparse_runs as _changed_sparse_runs,
    clamp_visual_size as _clamp_visual_size,
    compact_layout as _compact_layout,
    compute_layout as _compute_layout,
    draw_dock,
    draw_status,
    draw_visual,
    effective_cell_width as _effective_cell_width,
    init_colors as _init_colors,
    interpolated_row_value as _interpolated_row_value,
    palette_attr as _palette_attr,
    palette_name as _palette_name,
    safe_add as _safe_add,
    semantic_color_bucket as _semantic_color_bucket,
    unicode_output_supported as _unicode_output_supported,
    visual_shade as _visual_shade,
    visual_limits as _visual_limits,
)

# Keep the original module-level imports available to integrations while the
# implementations themselves now live behind focused runtime and TUI modules.
__all__ = [
    "AFTERGLOW_NAMES",
    "Button",
    "COMPACT_TARGET_CELLS",
    "CONTENT_MODES",
    "Control",
    "DAILY_PALETTES",
    "EDGE_NAMES",
    "Layout",
    "LavaField",
    "MATERIAL_NAMES",
    "PALETTE_FALLBACKS",
    "PALETTES",
    "PROFILE_NAMES",
    "ReactionLatch",
    "RuntimeMetrics",
    "TAB_NAMES",
    "UiState",
    "VisualCache",
    "WEIGHT_NAMES",
    "_changed_cell_runs",
    "_changed_sparse_runs",
    "_clamp_visual_size",
    "_compact_layout",
    "_compute_layout",
    "_draw_dock",
    "_draw_status",
    "_draw_visual",
    "_effective_cell_width",
    "_init_colors",
    "_interpolated_row_value",
    "_palette_attr",
    "_palette_name",
    "_safe_add",
    "_semantic_color_bucket",
    "_unicode_output_supported",
    "_visual_limits",
    "_visual_shade",
]

ANALYSIS_MODES = ("atlas", "bands")
BACKEND_MODES = ("auto", "pipewire", "pulse", "ffmpeg", "sox")
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


def _glyph_text(value) -> str:
    return normalize_glyph_ramp(value)


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


# Compatibility exports for integrations which imported the original private
# drawing helpers.  The implementations live in tui.py.
_draw_visual = draw_visual
_draw_dock = draw_dock


def _draw_status(
    stdscr: curses.window,
    config: AppConfig,
    ui: UiState,
    _frame: AudioFrame,
    field: LavaField,
) -> None:
    draw_status(
        stdscr,
        config,
        ui,
        field,
        _product_preset_name_for_config(config),
        _reactivity_name(float(getattr(config.lava, "reactivity", 1.0))),
    )


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


PRESETS: dict[str, dict[str, object]] = {
    "calm": {"fps": 20, "reactivity": 0.6, "drift": 0.15, "viscosity": 0.96, "blobs": 3},
    "balanced": {"fps": 30, "reactivity": 1.0, "drift": 0.30, "viscosity": 0.92, "blobs": 4},
    "reactive": {"fps": 30, "reactivity": 1.5, "drift": 0.45, "viscosity": 0.85, "blobs": 6},
    "chaos": {"fps": 45, "reactivity": 2.0, "drift": 0.65, "viscosity": 0.75, "blobs": 8},
}


def _apply_named_preset(config: AppConfig, name: str) -> None:
    if name not in PRESETS:
        return
    p = PRESETS[name]
    config.fps = int(p["fps"])
    config.lava.reactivity = float(p["reactivity"])
    config.lava.drift = float(p["drift"])
    config.lava.viscosity = float(p["viscosity"])
    config.lava.blobs = int(p["blobs"])


def _handle_key(key: int, config: AppConfig, ui: UiState, controls: dict[str, list[Control]]) -> None:
    if key in (ord("q"), ord("Q")):
        ui.quit_requested = True
        return
    if key == ord("?"):
        ui.help_overlay = not ui.help_overlay
        ui.set_status("help overlay " + ("shown" if ui.help_overlay else "hidden"))
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

    # Presets 1-4
    if key in (ord("1"), ord("2"), ord("3"), ord("4")):
        preset_names = ("calm", "balanced", "reactive", "chaos")
        idx = key - ord("1")
        name = preset_names[idx]
        _apply_named_preset(config, name)
        ui.set_status(f"preset: {name}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # Sensitivity / gain or reactivity (g/G, r/R)
    if key in (ord("g"), ord("G"), ord("r"), ord("R")):
        delta = 0.15 if key in (ord("g"), ord("r")) else -0.15
        config.lava.reactivity = _clamp(config.lava.reactivity + delta, 0.3, 3.0)
        ui.set_status(f"reactivity: {config.lava.reactivity:.2f}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # Smoothing / viscosity (s/S)
    if key in (ord("s"), ord("S")):
        delta = 0.02 if key == ord("s") else -0.02
        config.lava.viscosity = _clamp(config.lava.viscosity + delta, 0.70, 0.98)
        ui.set_status(f"smoothing: {config.lava.viscosity:.2f}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # Autonomous motion speed / drift (m/M)
    if key in (ord("m"), ord("M")):
        delta = 0.05 if key == ord("m") else -0.05
        config.lava.drift = _clamp(config.lava.drift + delta, 0.05, 0.85)
        ui.set_status(f"motion speed: {config.lava.drift:.2f}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # Visual density / complexity / blobs (d/D)
    if key in (ord("d"), ord("D")):
        delta = 1 if key == ord("d") else -1
        config.lava.blobs = max(1, min(10, config.lava.blobs + delta))
        ui.set_status(f"density: {config.lava.blobs}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # FPS cap (f/F)
    if key in (ord("f"), ord("F")):
        fps_choices = (12, 20, 30, 45, 60)
        curr = config.fps
        idx = min(range(len(fps_choices)), key=lambda i: abs(fps_choices[i] - curr))
        delta = 1 if key == ord("f") else -1
        config.fps = fps_choices[(idx + delta) % len(fps_choices)]
        ui.set_status(f"fps cap: {config.fps}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
        return

    # Palette cycle (p/P)
    if key in (ord("p"), ord("P")):
        palettes = list(PALETTES.keys())
        curr = _palette_name(config.render.palette)
        idx = palettes.index(curr) if curr in palettes else 0
        delta = 1 if key == ord("p") else -1
        config.render.palette = palettes[(idx + delta) % len(palettes)]
        ui.set_status(f"palette: {config.render.palette}")
        ui.preferences_dirty = True
        ui.preferences_due_at = time.monotonic() + 0.35
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
