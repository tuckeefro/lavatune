"""Configuration data and the few transformations exposed by the CLI."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import tomllib


BACKEND_NAMES = ("auto", "pipewire", "pulse", "ffmpeg")
PROFILE_NAMES = ("power-save", "atlas", "responsive")
CONTENT_MODES = ("auto", "music", "speech", "book")
LISTENING_CONTEXTS = ("podcast", "radio", "music", "microphone")
CAPTURE_ROUTES = ("system", "microphone")
MATERIAL_NAMES = ("text", "fluid", "volume", "wax")
RENDERER_NAMES = ("tui", "canvas")
WEIGHT_NAMES = ("airy", "balanced", "full")
EDGE_NAMES = ("soft", "defined")
AFTERGLOW_NAMES = ("quiet", "present")
DEFAULT_THEME = "soft-afterglow"
THEME_ALIASES = {"warm-braille": DEFAULT_THEME}
PREFERENCE_SCHEMA = 3


@dataclass(slots=True)
class AudioConfig:
    backend: str = "auto"
    source: str | None = None
    capture_route: str = "system"
    analysis: str = "atlas"
    sample_rate: int = 22050
    channels: int = 1
    frame_size: int = 1024


@dataclass(slots=True)
class RenderConfig:
    glyphs: str = " .,:;~oO@"
    palette: list[str] | str | None = "soft-afterglow"
    material: str = "fluid"
    renderer: str = "tui"
    weight: str = "balanced"
    edge: str = "soft"
    afterglow: str = "present"
    cell_aspect: float = 1.85
    show_stats: bool = False
    scale: int = 3
    color_steps: int = 4
    compact: bool = False
    max_width: int | None = None
    max_height: int | None = None


@dataclass(slots=True)
class LavaConfig:
    blobs: int = 4
    drift: float = 0.30
    viscosity: float = 0.92
    reactivity: float = 1.0
    radius_min: float = 0.09
    radius_max: float = 0.22


@dataclass(slots=True)
class AppConfig:
    fps: int = 30
    theme: str = DEFAULT_THEME
    profile: str = "atlas"
    content_mode: str = "auto"
    listening_context: str = "music"
    audio: AudioConfig = field(default_factory=AudioConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    lava: LavaConfig = field(default_factory=LavaConfig)


BUILTIN_THEMES: dict[str, AppConfig] = {
    DEFAULT_THEME: AppConfig(),
    "cool-dense": AppConfig(
        theme="cool-dense",
        render=RenderConfig(
            glyphs=" `.^,:;Il!i~+_-?][}{1)(|\\/*tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
            palette="ice",
        ),
        lava=LavaConfig(blobs=10, reactivity=1.45),
    ),
    "mono-blocks": AppConfig(
        theme="mono-blocks",
        render=RenderConfig(
            glyphs=" ░▒▓█",
            palette="mono",
        ),
        lava=LavaConfig(blobs=7, drift=0.24),
    ),
}

DEFAULT_THEME_NAMES = tuple(BUILTIN_THEMES.keys())


def _merge_dataclass(instance: Any, overrides: dict[str, Any]) -> Any:
    allowed = {field.name for field in fields(instance)}
    data = {}
    for key, value in overrides.items():
        if key not in allowed:
            raise ValueError(f"Unknown config key: {key}")
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__"):
            if not isinstance(value, dict):
                raise ValueError(f"Expected table for '{key}'")
            data[key] = _merge_dataclass(current, value)
        else:
            data[key] = value
    return replace(instance, **data)


def preference_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return base / "lavatune" / "preferences.json"


def _preference_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "schema": PREFERENCE_SCHEMA,
        "fps": config.fps,
        "profile": config.profile,
        "listening_context": config.listening_context,
        "audio": {
            "backend": config.audio.backend,
            "capture_route": config.audio.capture_route,
            "analysis": config.audio.analysis,
            "sample_rate": config.audio.sample_rate,
            "frame_size": config.audio.frame_size,
        },
        "render": {
            "palette": config.render.palette,
            "material": config.render.material,
            "renderer": config.render.renderer,
            "weight": config.render.weight,
            "edge": config.render.edge,
            "afterglow": config.render.afterglow,
            "cell_aspect": config.render.cell_aspect,
            "show_stats": config.render.show_stats,
            "scale": config.render.scale,
            "color_steps": config.render.color_steps,
        },
        "lava": {
            "blobs": config.lava.blobs,
            "drift": config.lava.drift,
            "viscosity": config.lava.viscosity,
            "reactivity": config.lava.reactivity,
            "radius_min": config.lava.radius_min,
            "radius_max": config.lava.radius_max,
        },
    }


def save_preferences(config: AppConfig, path: Path | None = None) -> Path:
    """Atomically save bounded user-facing settings, never an explicit config file."""

    destination = path or preference_path()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".preferences-",
        suffix=".json",
        dir=destination.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_preference_payload(config), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _apply_saved_preferences(config: AppConfig, path: Path) -> AppConfig:
    if not path.exists():
        return config
    if path.stat().st_size > 65536:
        raise ValueError(f"Preferences file is too large: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Unsupported preferences schema in {path}")
    schema = raw.get("schema")
    if schema == 1:
        legacy_content = raw.pop("content_mode", "auto")
        raw["listening_context"] = {
            "music": "music",
            "speech": "podcast",
            "book": "podcast",
            "auto": "radio",
        }.get(legacy_content, "music")
        audio = raw.get("audio")
        if isinstance(audio, dict):
            audio["capture_route"] = "system"
        raw["schema"] = 2
    if raw.get("schema") == 2:
        render = raw.get("render")
        if isinstance(render, dict):
            render.setdefault("renderer", "tui")
        raw["schema"] = PREFERENCE_SCHEMA
    if raw.get("schema") != PREFERENCE_SCHEMA:
        raise ValueError(f"Unsupported preferences schema in {path}")
    overrides = {key: value for key, value in raw.items() if key != "schema"}
    return _merge_dataclass(config, overrides)


def _normalize_config(config: AppConfig) -> AppConfig:
    render = config.render
    render = replace(
        render,
        material=render.material if render.material in MATERIAL_NAMES else "text",
        renderer=render.renderer if render.renderer in RENDERER_NAMES else "tui",
        weight=render.weight if render.weight in WEIGHT_NAMES else "balanced",
        edge=render.edge if render.edge in EDGE_NAMES else "soft",
        afterglow=render.afterglow if render.afterglow in AFTERGLOW_NAMES else "present",
        cell_aspect=max(1.0, min(3.0, float(render.cell_aspect))),
    )
    context = (
        config.listening_context
        if config.listening_context in LISTENING_CONTEXTS
        else "music"
    )
    route = "microphone" if context == "microphone" else "system"
    if config.audio.capture_route not in CAPTURE_ROUTES:
        route = "system"
    return replace(
        config,
        listening_context=context,
        audio=replace(config.audio, capture_route=route),
        render=render,
    )


def apply_profile(config: AppConfig, profile_name: str | None) -> AppConfig:
    if profile_name is None:
        return config
    if profile_name not in PROFILE_NAMES:
        raise ValueError(f"Unknown profile '{profile_name}'")
    if profile_name == "power-save":
        return replace(
            config,
            profile=profile_name,
            fps=12,
            audio=replace(
                config.audio,
                analysis="atlas",
                sample_rate=min(config.audio.sample_rate, 12000),
                frame_size=max(config.audio.frame_size, 3072),
            ),
            render=replace(
                config.render,
                scale=max(config.render.scale, 4),
                color_steps=min(config.render.color_steps, 4),
            ),
            lava=replace(
                config.lava,
                blobs=min(config.lava.blobs, 4),
                drift=min(config.lava.drift, 0.20),
                viscosity=max(config.lava.viscosity, 0.96),
            ),
        )
    if profile_name == "atlas":
        return replace(
            config,
            profile=profile_name,
            fps=min(22, max(config.fps, 18)),
            audio=replace(
                config.audio,
                analysis="bands",
                sample_rate=min(config.audio.sample_rate, 16000),
                frame_size=1024,
            ),
            render=replace(
                config.render,
                scale=max(config.render.scale, 3),
                color_steps=min(config.render.color_steps, 4),
            ),
            lava=replace(
                config.lava,
                blobs=min(config.lava.blobs, 4),
                drift=min(config.lava.drift, 0.22),
                viscosity=max(config.lava.viscosity, 0.95),
            ),
        )
    return replace(
        config,
        profile=profile_name,
        fps=max(config.fps, 26),
        audio=replace(
            config.audio,
            analysis="bands",
            sample_rate=max(config.audio.sample_rate, 22050),
            frame_size=min(config.audio.frame_size, 1024),
        ),
        render=replace(
            config.render,
            scale=1,
            color_steps=4,
        ),
        lava=replace(
            config.lava,
            blobs=max(config.lava.blobs, 8),
            drift=max(config.lava.drift, 0.30),
            viscosity=min(config.lava.viscosity, 0.92),
        ),
    )


def apply_cli_overrides(
    config: AppConfig,
    *,
    backend_name: str | None = None,
    renderer_name: str | None = None,
    source: str | None = None,
    show_stats: bool = False,
    hide_stats: bool = False,
    compact_tile: bool = False,
    max_visual_width: int | None = None,
    max_visual_height: int | None = None,
) -> AppConfig:
    audio = config.audio
    render = config.render
    if backend_name is not None or source is not None:
        audio = replace(
            config.audio,
            backend=backend_name or config.audio.backend,
            source=source if source is not None else config.audio.source,
        )
    if (
        renderer_name is not None
        or show_stats
        or hide_stats
        or compact_tile
        or max_visual_width
        or max_visual_height
    ):
        next_show_stats = render.show_stats
        if show_stats:
            next_show_stats = True
        if hide_stats or compact_tile:
            next_show_stats = False
        render = replace(
            render,
            renderer=renderer_name or render.renderer,
            show_stats=next_show_stats,
            compact=compact_tile or render.compact,
            scale=render.scale,
            color_steps=min(render.color_steps, 4) if compact_tile else render.color_steps,
            max_width=max_visual_width if max_visual_width else render.max_width,
            max_height=max_visual_height if max_visual_height else render.max_height,
        )
    if audio is config.audio and render is config.render:
        return config
    return replace(config, audio=audio, render=render)


def load_config(
    config_path: str | None,
    theme_name: str | None,
    profile_name: str | None = None,
    saved_preferences: Path | None = None,
) -> AppConfig:
    theme_key = THEME_ALIASES.get(theme_name or DEFAULT_THEME, theme_name or DEFAULT_THEME)
    if theme_key not in BUILTIN_THEMES:
        raise ValueError(f"Unknown theme '{theme_key}'")
    config = BUILTIN_THEMES[theme_key]

    if saved_preferences is not None:
        config = _apply_saved_preferences(config, saved_preferences)

    if config_path:
        raw = tomllib.loads(Path(config_path).read_text())
        if not isinstance(raw, dict):
            raise ValueError("Config root must be a table")
        # A glyph override predates material selection. Preserve its historical
        # text semantics instead of silently turning it into a volume preset.
        render_override = raw.get("render")
        if isinstance(render_override, dict) and "glyphs" in render_override and "material" not in render_override:
            render_override["material"] = "text"
        if "listening_context" not in raw and isinstance(raw.get("content_mode"), str):
            raw["listening_context"] = {
                "music": "music",
                "speech": "podcast",
                "book": "podcast",
                "auto": "radio",
            }.get(raw["content_mode"], "music")
        config = _merge_dataclass(config, raw)

    return _normalize_config(apply_profile(config, profile_name or config.profile))
