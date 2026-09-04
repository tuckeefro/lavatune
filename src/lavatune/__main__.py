from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from . import __version__
from .app import LavaTuneApp
from .config import (
    BACKEND_NAMES,
    CONTENT_MODES,
    DEFAULT_THEME_NAMES,
    PROFILE_NAMES,
    RENDERER_NAMES,
    apply_cli_overrides,
    load_config,
    preference_path,
)
from .doctor import format_report, inspect_environment
from .text import sanitize_display_text
from .motion import (
    DEFAULT_MOTION_ANALYSIS_PATH,
    MOTION_ANALYSIS_MAX_SECONDS,
    MOTION_ANALYSIS_MIN_SECONDS,
    capture_motion_analysis,
)
from .trace import DEFAULT_TRACE_PATH, TRACE_MAX_SECONDS, TRACE_MIN_SECONDS, capture_trace


EXPERIMENTAL_RENDERERS = ("kitty",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lavatune",
        description="A local-first terminal and desktop acoustic organism for Linux and macOS.",
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
        "--renderer",
        choices=(*RENDERER_NAMES, *EXPERIMENTAL_RENDERERS),
        help=(
            "Presentation renderer: terminal-native tui (default), Kitty/Ghostty pixel wax, "
            "experimental canvas, or standalone window."
        ),
    )
    parser.add_argument(
        "--canvas",
        action="store_true",
        help="Compatibility alias for --renderer canvas.",
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="Open standalone floating window renderer.",
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
    parser.add_argument(
        "--trace-once",
        type=float,
        metavar="SECONDS",
        help=(
            "Capture local feature values for one bounded pass, then exit "
            f"({TRACE_MIN_SECONDS:g}-{TRACE_MAX_SECONDS:g} seconds; no audio is recorded)."
        ),
    )
    parser.add_argument(
        "--trace-output",
        help=f"Feature-trace path (default: {DEFAULT_TRACE_PATH}).",
    )
    parser.add_argument(
        "--motion-analysis",
        type=float,
        metavar="SECONDS",
        help=(
            "Analyze live production motion for one bounded pass, then exit "
            f"({MOTION_ANALYSIS_MIN_SECONDS:g}-{MOTION_ANALYSIS_MAX_SECONDS:g} seconds; no PCM is stored)."
        ),
    )
    parser.add_argument(
        "--motion-output",
        help=f"Motion-analysis path (default: {DEFAULT_MOTION_ANALYSIS_PATH}).",
    )
    return parser


def _install_signal_handlers() -> None:
    def handle_sigterm(_signum, _frame):
        raise KeyboardInterrupt()

    try:
        signal.signal(signal.SIGTERM, handle_sigterm)
    except (ValueError, OSError):
        pass


def main() -> int:
    _install_signal_handlers()
    parser = build_parser()
    args = parser.parse_args()

    if args.no_audio_probe and not args.doctor:
        parser.error("--no-audio-probe requires --doctor")
    if args.trace_output and args.trace_once is None:
        parser.error("--trace-output requires --trace-once")
    if args.motion_output and args.motion_analysis is None:
        parser.error("--motion-output requires --motion-analysis")
    if args.trace_once is not None and args.motion_analysis is not None:
        parser.error("--trace-once and --motion-analysis cannot be combined")
    if args.trace_once is not None and args.demo:
        parser.error("--trace-once captures live audio and cannot be used with --demo")
    if args.motion_analysis is not None and args.demo:
        parser.error("--motion-analysis captures live audio and cannot be used with --demo")
    if args.canvas and args.window:
        parser.error("--canvas and --window cannot be combined")
    if args.canvas and args.renderer and args.renderer != "canvas":
        parser.error("--canvas cannot be combined with another --renderer value")
    if args.window and args.renderer and args.renderer != "window":
        parser.error("--window cannot be combined with another --renderer value")
    renderer_name = "window" if args.window else ("canvas" if args.canvas else args.renderer)
    visual_renderers = ("canvas", "window", "kitty")
    if args.trace_once is not None and renderer_name in visual_renderers:
        parser.error(f"--trace-once cannot be used with the {renderer_name} renderer")
    if args.motion_analysis is not None and renderer_name in visual_renderers:
        parser.error(f"--motion-analysis cannot be used with the {renderer_name} renderer")

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
            # Kitty is deliberately CLI-only while the visual direction is
            # still a prototype, so persisted config remains portable.
            renderer_name=None if renderer_name == "kitty" else renderer_name,
            source=args.source,
            show_stats=args.show_stats,
            hide_stats=args.no_stats,
            compact_tile=args.compact_tile,
            max_visual_width=args.max_visual_width,
            max_visual_height=args.max_visual_height,
        )
        if renderer_name == "kitty":
            config.render.renderer = "kitty"
    except (OSError, TypeError, ValueError) as exc:
        print(f"Config error: {sanitize_display_text(str(exc), max_chars=500)}", file=sys.stderr)
        return 2

    if args.doctor:
        report = inspect_environment(config, probe_audio=not args.no_audio_probe)
        print(format_report(report))
        return report.exit_code

    if args.trace_once is not None:
        try:
            result = capture_trace(
                config,
                args.trace_once,
                DEFAULT_TRACE_PATH if args.trace_output is None else Path(args.trace_output),
            )
        except RuntimeError as exc:
            print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
            return 1
        print(
            f"Trace complete: {result.samples} feature samples from "
            f"{result.frames} analysis frames at {result.path}"
        )
        return 0

    if args.motion_analysis is not None:
        try:
            result = capture_motion_analysis(
                config,
                args.motion_analysis,
                DEFAULT_MOTION_ANALYSIS_PATH
                if args.motion_output is None
                else Path(args.motion_output),
            )
        except RuntimeError as exc:
            print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
            return 1
        print(
            f"Motion analysis complete: {result.samples} motion samples from "
            f"{result.frames} analysis frames at {result.path}"
        )
        print(result.summary)
        return 0

    if config.render.renderer == "kitty":
        try:
            from .kitty import run_kitty

            return run_kitty(config, args.demo)
        except RuntimeError as exc:
            print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
            return 1

    if config.render.renderer == "canvas":
        try:
            from .canvas import run_canvas

            return run_canvas(config, args.demo)
        except RuntimeError as exc:
            print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
            return 1

    if config.render.renderer == "window":
        try:
            from .window import run_window

            return run_window(config, args.demo)
        except RuntimeError as exc:
            print(sanitize_display_text(str(exc), max_chars=500), file=sys.stderr)
            return 1

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
