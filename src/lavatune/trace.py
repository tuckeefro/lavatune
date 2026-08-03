"""One-shot, local feature traces for calibrating Lavatune to real playback."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .audio import AudioCapture, AudioFrame
from .config import AppConfig
from .organism import (
    AffectiveTracker,
    AudioForceMapper,
    NarrativeTracker,
    apply_behavior_profile,
    behavior_for_context,
)


TRACE_INTERVAL_SECONDS = 0.10
TRACE_MIN_SECONDS = 5.0
TRACE_MAX_SECONDS = 600.0
DEFAULT_TRACE_PATH = Path("/tmp/lavatune-trace.json")


@dataclass(slots=True, frozen=True)
class TraceResult:
    """Small handoff describing one completed local analysis pass."""

    path: Path
    samples: int
    frames: int


class TraceRecorder:
    """Sample existing Lavatune state at a bounded rate; never retain PCM."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.mapper = AudioForceMapper()
        self.affect = AffectiveTracker()
        self.narrative = NarrativeTracker()
        self.behavior = behavior_for_context(config.listening_context)
        self.records: list[dict[str, object]] = []
        self.frames = 0
        self._started_at: float | None = None
        self._last_recorded_at: float | None = None

    def observe(self, frame: AudioFrame) -> None:
        """Update every existing analysis frame, retaining one in ten per second."""

        timestamp = float(frame.timestamp)
        if self._started_at is None:
            self._started_at = timestamp
        mode = self.config.content_mode if self.config.content_mode != "auto" else "music"
        forces = self.mapper.map(frame, mode, self.config.lava.reactivity)
        forces = apply_behavior_profile(forces, self.behavior)
        affect = self.affect.update(forces, timestamp)
        narrative = self.narrative.update(forces, affect, timestamp)
        self.frames += 1
        if (
            self._last_recorded_at is not None
            and timestamp - self._last_recorded_at < TRACE_INTERVAL_SECONDS
        ):
            return
        self._last_recorded_at = timestamp
        self.records.append(
            {
                "at_seconds": round(timestamp - self._started_at, 3),
                "signal": {
                    "rms": round(frame.rms, 4),
                    "attack": round(frame.attack, 4),
                    "zcr": round(frame.zcr, 4),
                    "bands": [round(value, 4) for value in frame.bands],
                },
                "forces": {
                    key: value
                    for key, value in asdict(forces).items()
                    if key not in {"bands", "hits", "deviations"}
                },
                "affect": asdict(affect),
                "phrase": asdict(narrative),
            }
        )

    def payload(self) -> dict[str, object]:
        """Return feature-only data plus useful peak locations for review."""

        def peak(group: str, key: str) -> dict[str, float]:
            record = max(self.records, key=lambda item: float(item[group][key]))
            return {
                "value": round(float(record[group][key]), 4),
                "at_seconds": float(record["at_seconds"]),
            }

        return {
            "format": "lavatune-feature-trace-v1",
            "privacy": "Feature values only; no PCM, audio recording, titles, or metadata.",
            "context": self.config.listening_context,
            "analysis": self.config.audio.analysis,
            "sample_interval_seconds": TRACE_INTERVAL_SECONDS,
            "captured_analysis_frames": self.frames,
            "samples": self.records,
            "peaks": {
                "attack": peak("signal", "attack"),
                "bass": peak("forces", "bass"),
                "voice": peak("forces", "voice"),
                "detail": peak("forces", "detail"),
                "cadence": peak("phrase", "cadence"),
                "rupture": peak("phrase", "rupture"),
                "overdrive": peak("phrase", "overdrive"),
            }
            if self.records
            else {},
        }


def capture_trace(
    config: AppConfig,
    seconds: float,
    output: Path = DEFAULT_TRACE_PATH,
    *,
    capture_factory: Callable[[object], AudioCapture] = AudioCapture,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> TraceResult:
    """Capture one bounded local trace, then always release the audio source."""

    duration = max(TRACE_MIN_SECONDS, min(TRACE_MAX_SECONDS, float(seconds)))
    capture = capture_factory(config.audio)
    recorder = TraceRecorder(config)
    sequence = 0
    print(f"Tracing live audio for {duration:g} seconds. Start playback now.", flush=True)
    capture.start()
    deadline = clock() + duration
    try:
        while clock() < deadline:
            for captured in capture.drain_after(sequence):
                sequence = captured.sequence
                recorder.observe(captured.frame)
            if capture.error():
                raise RuntimeError(capture.error())
            sleeper(0.02)
    finally:
        capture.stop()

    if not recorder.records:
        raise RuntimeError("No live audio frames arrived during the one-shot trace.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(recorder.payload(), indent=2) + "\n", encoding="utf-8")
    return TraceResult(output, len(recorder.records), recorder.frames)
