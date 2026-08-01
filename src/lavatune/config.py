"""Configuration data and the few transformations exposed by the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import tomllib


BACKEND_NAMES = ("auto", "pipewire", "pulse", "ffmpeg")
PROFILE_NAMES = ("power-save", "atlas", "responsive")
CONTENT_MODES = ("auto", "music", "speech", "book")
DEFAULT_THEME = "soft-afterglow"
THEME_ALIASES = {"warm-braille": DEFAULT_THEME}


@dataclass(slots=True)
class AudioConfig:
    backend: str = "auto"
    source: str | None = None
    analysis: str = "atlas"
    sample_rate: int = 22050
    channels: int = 1
    frame_size: int = 1024


@dataclass(slots=True)
class RenderConfig:
    glyphs: str = " .,:;~oO@"
    palette: list[str] | str | None = "soft-afterglow"
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
                analysis="atlas",
                sample_rate=min(config.audio.sample_rate, 16000),
                frame_size=max(config.audio.frame_size, 2048),
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
    if show_stats or hide_stats or compact_tile or max_visual_width or max_visual_height:
        next_show_stats = render.show_stats
        if show_stats:
            next_show_stats = True
        if hide_stats or compact_tile:
            next_show_stats = False
        render = replace(
            render,
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
) -> AppConfig:
    theme_key = THEME_ALIASES.get(theme_name or DEFAULT_THEME, theme_name or DEFAULT_THEME)
    if theme_key not in BUILTIN_THEMES:
        raise ValueError(f"Unknown theme '{theme_key}'")
    config = BUILTIN_THEMES[theme_key]

    if config_path:
        raw = tomllib.loads(Path(config_path).read_text())
        if not isinstance(raw, dict):
            raise ValueError("Config root must be a table")
        config = _merge_dataclass(config, raw)

    return apply_profile(config, profile_name or config.profile)
