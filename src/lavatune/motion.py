"""Live, feature-only motion analysis for tuning Lavatune's body language."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .audio import AudioCapture, AudioFrame
from .config import AppConfig
from .organism import behavior_for_context, motion_cues
from .runtime import LavaField
from .signals import clamp


MOTION_ANALYSIS_MIN_SECONDS = 5.0
MOTION_ANALYSIS_MAX_SECONDS = 600.0
MOTION_ANALYSIS_INTERVAL_SECONDS = 0.10
DEFAULT_MOTION_ANALYSIS_PATH = Path("/tmp/lavatune-motion.json")


@dataclass(slots=True, frozen=True)
class MotionAnalysisResult:
    path: Path
    samples: int
    frames: int
    summary: str


class MotionAnalyzer:
    """Advance the real organism and retain only derived motion telemetry."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.field = LavaField()
        self.field.resize(44, 18)
        self.behavior = behavior_for_context(config.listening_context)
        self.records: list[dict[str, object]] = []
        self.frames = 0
        self._started_at: float | None = None
        self._last_timestamp: float | None = None
        self._last_recorded_at: float | None = None
        self._previous_velocity: dict[int, tuple[float, float]] = {}
        self._starts: dict[int, tuple[float, float]] = {}

    def observe(self, frame: AudioFrame) -> None:
        timestamp = float(frame.timestamp)
        if self._started_at is None:
            self._started_at = timestamp
        dt = (
            1.0 / 22.0
            if self._last_timestamp is None
            else clamp(timestamp - self._last_timestamp, 1.0 / 120.0, 1.0 / 12.0)
        )
        self._last_timestamp = timestamp
        self.field.observe(
            frame,
            "music",
            self.config.lava.reactivity,
            self.behavior,
        )
        self.field.render_forces = self.field.reactions.consume(self.field.forces)
        surface_ripples = self.config.render.material == "fluid"
        embody_posture = self.config.render.material == "volume"
        self.field.organism.update(
            dt,
            self.field.render_forces,
            self.field.w,
            self.field.h,
            self.config.lava,
            self.field.motion_profile,
            self.config.render.cell_aspect,
            self.field.affect,
            self.field.narrative,
            self.behavior,
            embody_posture,
            surface_ripples,
        )
        self.field.phase = self.field.organism.phase
        self.frames += 1

        if (
            self._last_recorded_at is not None
            and timestamp - self._last_recorded_at < MOTION_ANALYSIS_INTERVAL_SECONDS
        ):
            return
        sample_dt = (
            dt
            if self._last_recorded_at is None
            else clamp(timestamp - self._last_recorded_at, 1.0 / 120.0, 0.5)
        )
        self._last_recorded_at = timestamp

        bodies: list[dict[str, object]] = []
        speeds: list[float] = []
        accelerations: list[float] = []
        for index, body in enumerate(self.field.bodies[: self.field.composition.active_bodies]):
            self._starts.setdefault(index, (body.x, body.y))
            previous_vx, previous_vy = self._previous_velocity.get(index, (body.vx, body.vy))
            speed = math.hypot(body.vx, body.vy)
            acceleration = math.hypot(
                (body.vx - previous_vx) / sample_dt,
                (body.vy - previous_vy) / sample_dt,
            )
            start_x, start_y = self._starts[index]
            cues = motion_cues(self.field.render_forces, self.field.phase, body.phase)
            speeds.append(speed)
            accelerations.append(acceleration)
            self._previous_velocity[index] = (body.vx, body.vy)
            bodies.append(
                {
                    "index": index,
                    "role": body.character.name,
                    "x": round(body.x, 5),
                    "y": round(body.y, 5),
                    "travel": round(math.hypot(body.x - start_x, body.y - start_y), 5),
                    "speed": round(speed, 5),
                    "acceleration": round(acceleration, 5),
                    "planar_force": round(math.hypot(body.planar_force_x, body.planar_force_y), 5),
                    "float_drive": round(cues.float_drive, 4),
                    "chop_drive": round(cues.chop_drive, 4),
                    "chop_signed": round(cues.chop_wave * cues.chop_drive, 4),
                    "stretch": round(abs(body.stretch_x - 1.0) + abs(body.stretch_y - 1.0), 5),
                    "radius": round(body.radius, 5),
                    "spike": round(body.spike, 4),
                    "afterglow": round(body.afterglow, 4),
                }
            )

        self.records.append(
            {
                "at_seconds": round(timestamp - self._started_at, 3),
                "forces": {
                    key: value
                    for key, value in asdict(self.field.render_forces).items()
                    if key not in {"bands", "hits", "deviations"}
                },
                "affect": asdict(self.field.affect),
                "phrase": asdict(self.field.narrative),
                "group": {
                    "mean_speed": round(sum(speeds) / max(1, len(speeds)), 5),
                    "max_speed": round(max(speeds, default=0.0), 5),
                    "max_acceleration": round(max(accelerations, default=0.0), 5),
                    "max_float": round(max((body["float_drive"] for body in bodies), default=0.0), 4),
                    "max_chop": round(max((body["chop_drive"] for body in bodies), default=0.0), 4),
                    "max_spike": round(max((body["spike"] for body in bodies), default=0.0), 4),
                },
                "bodies": bodies,
            }
        )

    def payload(self) -> dict[str, object]:
        if not self.records:
            return {
                "format": "lavatune-motion-analysis-v1",
                "privacy": "Derived motion telemetry only; no PCM, audio, titles, or metadata.",
                "samples": [],
            }

        groups = [record["group"] for record in self.records]
        body_records = [body for record in self.records for body in record["bodies"]]
        return {
            "format": "lavatune-motion-analysis-v1",
            "privacy": "Derived motion telemetry only; no PCM, audio, titles, or metadata.",
            "motion_profile": self.field.motion_profile,
            "context": self.config.listening_context,
            "material": self.config.render.material,
            "sample_interval_seconds": MOTION_ANALYSIS_INTERVAL_SECONDS,
            "captured_analysis_frames": self.frames,
            "samples": self.records,
            "summary": {
                "mean_speed": round(
                    sum(float(group["mean_speed"]) for group in groups) / len(groups), 5
                ),
                "peak_speed": round(max(float(group["max_speed"]) for group in groups), 5),
                "peak_acceleration": round(
                    max(float(group["max_acceleration"]) for group in groups), 5
                ),
                "peak_float": round(max(float(group["max_float"]) for group in groups), 4),
                "peak_chop": round(max(float(group["max_chop"]) for group in groups), 4),
                "peak_spike": round(max(float(group["max_spike"]) for group in groups), 4),
                "peak_body_travel": round(
                    max(float(body["travel"]) for body in body_records), 5
                ),
            },
        }

    def summary_line(self) -> str:
        summary = self.payload().get("summary", {})
        return (
            "Motion analysis | "
            f"speed mean {summary.get('mean_speed', 0.0):.4f} | "
            f"peak accel {summary.get('peak_acceleration', 0.0):.4f} | "
            f"float {summary.get('peak_float', 0.0):.3f} | "
            f"chop {summary.get('peak_chop', 0.0):.3f} | "
            f"spike {summary.get('peak_spike', 0.0):.3f} | "
            f"travel {summary.get('peak_body_travel', 0.0):.4f}"
        )


def capture_motion_analysis(
    config: AppConfig,
    seconds: float,
    output: Path = DEFAULT_MOTION_ANALYSIS_PATH,
    *,
    capture_factory: Callable[[object], AudioCapture] = AudioCapture,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> MotionAnalysisResult:
    """Capture live audio, advance the production motion path, and write telemetry."""

    duration = max(
        MOTION_ANALYSIS_MIN_SECONDS,
        min(MOTION_ANALYSIS_MAX_SECONDS, float(seconds)),
    )
    capture = capture_factory(config.audio)
    analyzer = MotionAnalyzer(config)
    sequence = 0
    print(
        f"Analyzing live motion for {duration:g} seconds. Start playback now.",
        flush=True,
    )
    capture.start()
    deadline = clock() + duration
    try:
        while clock() < deadline:
            for captured in capture.drain_after(sequence):
                sequence = captured.sequence
                analyzer.observe(captured.frame)
            if capture.error():
                raise RuntimeError(capture.error())
            sleeper(0.02)
    finally:
        capture.stop()

    if not analyzer.records:
        raise RuntimeError("No live audio frames arrived during motion analysis.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(analyzer.payload(), indent=2) + "\n", encoding="utf-8")
    return MotionAnalysisResult(
        output,
        len(analyzer.records),
        analyzer.frames,
        analyzer.summary_line(),
    )
