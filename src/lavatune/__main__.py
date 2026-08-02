from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import LavaTuneApp
from .config import (
    BACKEND_NAMES,
    CONTENT_MODES,
    DEFAULT_THEME_NAMES,
    PROFILE_NAMES,
    apply_cli_overrides,
    load_config,
    preference_path,
)
from .doctor import format_report, inspect_environment
from .text import sanitize_display_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lavatune",
        description="A terminal-native acoustic organism for Linux.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", help="Path to a TOML config override.")
    parser.add_argument(
        "--theme",
        choices=DEFAULT_THEME_NAMES,
        help="Built-in theme to use without a config file.",
    )
    parser.add_argument(
        "--list-themes",
        action="store_true",
        help="List built-in themes and exit.",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="List supported audio backends and exit.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List runtime power profiles and exit.",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        help="Runtime profile for latency and CPU usage.",
    )
    parser.add_argument(
        "--content-mode",
        choices=CONTENT_MODES,
        help="Force audio response tuning instead of auto-detecting content.",
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_NAMES,
        help="Audio backend override.",
    )
    parser.add_argument(
        "--analysis",
        choices=("atlas", "bands"),
        help="Audio analysis model override.",
    )
    parser.add_argument(
        "--source",
        help="Explicit audio monitor/source name for your Linux audio stack.",
    )
    parser.add_argument(
        "--show-stats",
        action="store_true",
        help="Show backend/profile status in the terminal footer at startup.",
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Hide live analysis stats.",
    )
    parser.add_argument(
        "--compact-tile",
        action="store_true",
        help="Keep the visual field small inside a larger terminal tile.",
    )
    parser.add_argument(
        "--max-visual-width",
        type=int,
        help="Maximum visual field width in terminal columns.",
    )
    parser.add_argument(
        "--max-visual-height",
        type=int,
        help="Maximum visual field height in terminal rows.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run without live audio using a synthetic signal.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check the local environment and audio path, then exit.",
    )
    parser.add_argument(
        "--no-audio-probe",
        action="store_true",
        help="With --doctor, skip the short live PCM probe.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.no_audio_probe and not args.doctor:
        parser.error("--no-audio-probe requires --doctor")

    if args.list_themes:
        for theme in DEFAULT_THEME_NAMES:
            print(theme)
        return 0

    if args.list_backends:
        for backend in BACKEND_NAMES:
            print(backend)
        return 0

    if args.list_profiles:
        for profile in PROFILE_NAMES:
            print(profile)
        return 0

    try:
        saved_preferences = preference_path()
        config = load_config(
            args.config,
            args.theme,
            args.profile,
            saved_preferences=None if args.config else saved_preferences,
        )
        if args.content_mode:
            config.content_mode = args.content_mode
        if args.analysis:
            config.audio.analysis = args.analysis
            if args.analysis == "bands":
                config.audio.sample_rate = max(config.audio.sample_rate, 22050)
                config.audio.frame_size = min(config.audio.frame_size, 1024)
        config = apply_cli_overrides(
            config,
            backend_name=args.backend,
            source=args.source,
            show_stats=args.show_stats,
            hide_stats=args.no_stats,
            compact_tile=args.compact_tile,
            max_visual_width=args.max_visual_width,
            max_visual_height=args.max_visual_height,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"Config error: {sanitize_display_text(str(exc), max_chars=500)}", file=sys.stderr)
        return 2

    if args.doctor:
        report = inspect_environment(config, probe_audio=not args.no_audio_probe)
        print(format_report(report))
        return report.exit_code

    app = LavaTuneApp(
        config,
        demo_mode=args.demo,
        saved_preferences=None if args.config else saved_preferences,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
