"""Optional local MPRIS metadata support through playerctl."""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass

from .text import sanitize_display_text


@dataclass(slots=True, frozen=True)
class MediaInfo:
    title: str = ""
    artist: str = ""
    source: str = ""
    status: str = ""

    def display(self) -> str:
        if not self.title:
            return ""
        detail = self.title
        if self.artist and self.artist.casefold() not in self.title.casefold():
            detail = f"{detail} - {self.artist}"
        prefix = self.source or "Media"
        if self.status.casefold() == "paused":
            prefix = f"{prefix} [paused]"
        return sanitize_display_text(f"{prefix} | {detail}")


class MediaWatcher:
    """Polls local MPRIS metadata without blocking the render loop."""

    FORMAT = "{{playerName}}\t{{status}}\t{{xesam:title}}\t{{xesam:artist}}\t{{xesam:url}}"

    def __init__(self, interval: float = 1.25) -> None:
        self.interval = interval
        self._playerctl = shutil.which("playerctl")
        self._latest = MediaInfo()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._playerctl or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="lavatune-media", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.4)

    def latest(self) -> MediaInfo:
        with self._lock:
            return self._latest

    def _run(self) -> None:
        while not self._stop.is_set():
            info = self._poll()
            with self._lock:
                self._latest = info
            self._stop.wait(self.interval)

    def _poll(self) -> MediaInfo:
        if not self._playerctl:
            return MediaInfo()
        try:
            result = subprocess.run(
                [self._playerctl, "-a", "metadata", "--format", self.FORMAT],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return MediaInfo()
        if result.returncode != 0:
            return MediaInfo()
        return parse_playerctl(result.stdout)


def parse_playerctl(output: str) -> MediaInfo:
    players: list[MediaInfo] = []
    for line in output.splitlines():
        parts = line.split("\t", 4)
        parts.extend([""] * (5 - len(parts)))
        player, status, title, artist, url = (sanitize_display_text(part) for part in parts)
        if not title:
            continue
        players.append(
            MediaInfo(
                title=title,
                artist=artist,
                source=_source_name(player, url),
                status=status,
            )
        )
    if not players:
        return MediaInfo()
    return next(
        (player for player in players if player.status.casefold() == "playing"),
        players[0],
    )

def _source_name(player: str, url: str) -> str:
    combined = f"{player} {url}".casefold()
    if "youtube" in combined or "youtu.be" in combined:
        return "YouTube"
    if "spotify" in combined:
        return "Spotify"
    if "vlc" in combined:
        return "VLC"
    if "firefox" in combined:
        return "Firefox"
    if "chrom" in combined:
        return "Chromium"
    cleaned = player.split(".", 1)[0].replace("-", " ").strip()
    return cleaned.title() if cleaned else "Media"
