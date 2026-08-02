"""Environment diagnostics for failures that happen before the TUI can start."""

from __future__ import annotations

import curses
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Callable

from .audio import CAPTURE_BINARIES, AudioCapture
from .config import AppConfig
from .text import sanitize_display_text


@dataclass(slots=True, frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    remedy: str = ""


@dataclass(slots=True, frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def errors(self) -> int:
        return sum(check.status == "error" for check in self.checks)

    @property
    def warnings(self) -> int:
        return sum(check.status == "warn" for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def _terminal_color_count() -> int:
    try:
        curses.setupterm(term=os.environ.get("TERM") or None)
        return max(0, curses.tigetnum("colors"))
    except (curses.error, OSError):
        return 0


def _backend_check(config: AppConfig) -> tuple[DoctorCheck, str | None]:
    available = [
        backend
        for backend, binary in CAPTURE_BINARIES.items()
        if shutil.which(binary) is not None
    ]
    preferred = config.audio.backend
    if preferred != "auto" and preferred not in available:
        binary = CAPTURE_BINARIES.get(preferred, preferred)
        return (
            DoctorCheck(
                "audio backend",
                "error",
                f"requested {preferred}; {binary} was not found",
                "Install the backend program or choose --backend auto.",
            ),
            None,
        )
    if not available:
        return (
            DoctorCheck(
                "audio backend",
                "error",
                "no supported capture program found",
                "Install pw-cat, parec, or ffmpeg.",
            ),
            None,
        )
    selected = preferred if preferred != "auto" else available[0]
    return (
        DoctorCheck(
            "audio backend",
            "ok",
            f"selected {selected}; available {', '.join(available)}",
        ),
        selected,
    )


def _probe_audio(
    config: AppConfig,
    *,
    timeout: float,
    capture_factory: Callable[..., AudioCapture],
) -> DoctorCheck:
    capture: AudioCapture | None = None
    try:
        capture = capture_factory(config.audio)
        capture.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if capture.frames_received() > 0:
                frame = capture.latest()
                return DoctorCheck(
                    "audio frames",
                    "ok",
                    f"received PCM through {capture.status()} (level {frame.rms:0.3f})",
                )
            if capture.error():
                return DoctorCheck(
                    "audio frames",
                    "error",
                    capture.error() or "capture stopped",
                    "Run wpctl status or pactl list short sources, then pass --source explicitly.",
                )
            time.sleep(0.05)
        return DoctorCheck(
            "audio frames",
            "error",
            f"no PCM arrived within {timeout:0.1f}s",
            "Play audio, verify the monitor source, or try another --backend.",
        )
    except (OSError, RuntimeError) as exc:
        return DoctorCheck(
            "audio frames",
            "error",
            sanitize_display_text(str(exc), max_chars=500),
            "Check the selected backend and monitor source.",
        )
    finally:
        if capture is not None:
            capture.stop()


def inspect_environment(
    config: AppConfig,
    *,
    probe_audio: bool = True,
    probe_timeout: float = 1.5,
    capture_factory: Callable[..., AudioCapture] = AudioCapture,
) -> DoctorReport:
    checks: list[DoctorCheck] = []
    linux = platform.system() == "Linux"
    checks.append(
        DoctorCheck(
            "platform",
            "ok" if linux else "error",
            f"{platform.system()} {platform.machine()}".strip(),
            "Lavatune currently supports Linux only." if not linux else "",
        )
    )

    supported_python = sys.version_info >= (3, 11)
    checks.append(
        DoctorCheck(
            "python",
            "ok" if supported_python else "error",
            platform.python_version(),
            "Install Python 3.11 or newer." if not supported_python else "",
        )
    )

    colors = _terminal_color_count()
    checks.append(
        DoctorCheck(
            "terminal colors",
            "ok" if colors >= 256 else "warn",
            f"{colors} colors reported",
            "Use a 256-color terminal for the intended palette." if colors < 256 else "",
        )
    )

    backend, selected_backend = _backend_check(config)
    checks.append(backend)

    playerctl = shutil.which("playerctl")
    checks.append(
        DoctorCheck(
            "media metadata",
            "ok" if playerctl else "warn",
            "playerctl available" if playerctl else "playerctl not found; titles will be hidden",
            "Install playerctl only if local media titles are wanted." if not playerctl else "",
        )
    )

    if probe_audio and selected_backend is not None and linux:
        checks.append(
            _probe_audio(
                config,
                timeout=max(0.2, min(5.0, probe_timeout)),
                capture_factory=capture_factory,
            )
        )
    elif probe_audio:
        checks.append(
            DoctorCheck(
                "audio frames",
                "skip",
                "audio probe is Linux-only in this release",
                "Use --demo or wait for the 0.2.0 macOS native track.",
            )
        )
    elif not probe_audio:
        checks.append(DoctorCheck("audio frames", "skip", "live probe disabled"))

    return DoctorReport(tuple(checks))


def format_report(report: DoctorReport) -> str:
    lines = ["Lavatune doctor", ""]
    for check in report.checks:
        detail = sanitize_display_text(check.detail, max_chars=500)
        lines.append(f"[{check.status:5}] {check.name}: {detail}")
        if check.remedy:
            lines.append(f"        {check.remedy}")
    lines.extend(
        [
            "",
            f"Result: {report.errors} error(s), {report.warnings} warning(s)",
        ]
    )
    return "\n".join(lines)
