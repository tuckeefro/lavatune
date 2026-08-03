"""Renderer-neutral runtime that advances Lavatune's organism world."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace

from .audio import AudioFrame
from .config import LavaConfig
from .organism import (
    AcousticOrganism,
    AffectiveState,
    AffectiveTracker,
    AudioForceMapper,
    AudioForces,
    BehaviorProfile,
    Body,
    FieldFrame,
    NarrativeState,
    NarrativeTracker,
    OrganismFieldRenderer,
    TileComposition,
    apply_behavior_profile,
)
from .presentation import PresentationFrame
from .wax import WaxState


@dataclass
class RuntimeMetrics:
    wakeups: int = 0
    audio_packets: int = 0
    physics_steps: int = 0
    draws: int = 0
    changed_cells: int = 0
    written_runs: int = 0
    map_seconds: float = 0.0
    affect_seconds: float = 0.0
    physics_seconds: float = 0.0
    raster_seconds: float = 0.0
    material_seconds: float = 0.0
    terminal_seconds: float = 0.0


@dataclass
class ReactionLatch:
    transient: float = 0.0
    pulse: float = 0.0
    novelty: float = 0.0
    rhythm_density: float = 0.0
    rhythm_impulse: float = 0.0
    hits: tuple[float, ...] = (0.0,) * 8
    deviations: tuple[float, ...] = (0.0,) * 8
    requested_at: float = 0.0

    @property
    def level(self) -> float:
        return max(
            self.transient,
            self.pulse,
            self.novelty,
            self.rhythm_density,
            self.rhythm_impulse,
            max(self.hits, default=0.0),
            max(self.deviations, default=0.0),
        )

    @property
    def pending(self) -> bool:
        return self.level >= 0.08

    def observe(self, forces: AudioForces, affect: AffectiveState, now: float) -> None:
        self.transient = max(self.transient, forces.transient)
        self.pulse = max(self.pulse, forces.pulse)
        self.novelty = max(self.novelty, affect.novelty)
        self.rhythm_density = max(self.rhythm_density, forces.rhythm_density)
        self.rhythm_impulse = min(1.0, self.rhythm_impulse + forces.rhythm_impulse)
        self.hits = tuple(max(old, new) for old, new in zip(self.hits, forces.hits))
        self.deviations = tuple(
            max(old, new) for old, new in zip(self.deviations, forces.deviations)
        )
        if self.pending and self.requested_at <= 0.0:
            self.requested_at = now

    def consume(self, forces: AudioForces) -> AudioForces:
        merged = replace(
            forces,
            transient=max(forces.transient, self.transient),
            pulse=max(forces.pulse, self.pulse),
            flux=max(forces.flux, self.novelty * 0.72),
            rhythm_density=max(forces.rhythm_density, self.rhythm_density),
            rhythm_impulse=max(forces.rhythm_impulse, self.rhythm_impulse),
            hits=tuple(max(old, new) for old, new in zip(forces.hits, self.hits)),
            deviations=tuple(
                max(old, new) for old, new in zip(forces.deviations, self.deviations)
            ),
        )
        self.transient = 0.0
        self.pulse = 0.0
        self.novelty *= 0.24
        self.rhythm_density = 0.0
        self.rhythm_impulse = 0.0
        self.hits = (0.0,) * 8
        self.deviations = (0.0,) * 8
        self.requested_at = 0.0
        return merged

    def clear(self) -> None:
        self.transient = 0.0
        self.pulse = 0.0
        self.novelty = 0.0
        self.rhythm_density = 0.0
        self.rhythm_impulse = 0.0
        self.hits = (0.0,) * 8
        self.deviations = (0.0,) * 8
        self.requested_at = 0.0


class LavaField:
    """Own one renderable organism and translate audio frames into its forces."""

    def __init__(self, motion_profile: str = "buoyant") -> None:
        self.w = 0
        self.h = 0
        self.motion_profile = motion_profile
        self.mapper = AudioForceMapper()
        self.affect_tracker = AffectiveTracker()
        self.narrative_tracker = NarrativeTracker()
        self.organism = AcousticOrganism()
        self.wax = WaxState()
        self.renderer = OrganismFieldRenderer()
        self.forces = AudioForces()
        self.render_forces = AudioForces()
        self.affect = AffectiveState()
        self.narrative = NarrativeState()
        self.reactions = ReactionLatch()
        self.metrics = RuntimeMetrics()
        self.field_frame = FieldFrame.empty(0, 0)
        self._last_step_at: float | None = None
        self._last_audio_key: tuple[float, str, float] | None = None
        self.phase = 0.0
        self.reactivity = 1.0
        self.frames_seen = 0

    @property
    def bodies(self) -> list[Body]:
        return self.organism.bodies

    @property
    def composition(self) -> TileComposition:
        return self.organism.composition

    def presentation_frame(self) -> PresentationFrame:
        """Expose simulation state to a renderer without duplicating physics."""

        return PresentationFrame(
            bodies=tuple(self.organism.bodies),
            forces=self.render_forces,
            affect=self.affect,
            narrative=self.narrative,
            phase=self.phase,
        )

    @property
    def buffers(self) -> list[list[float]]:
        """Compatibility composite used by metrics, not the material hot path."""

        return self.field_frame.composite()

    @property
    def attention_buffers(self) -> list[list[float]]:
        return self.field_frame.attention

    @property
    def response_gain(self) -> float:
        return self.reactivity

    @property
    def calibration_frames(self) -> int:
        return self.frames_seen

    @property
    def last_low(self) -> float:
        return self.forces.bass

    @property
    def last_mid(self) -> float:
        return self.forces.voice

    @property
    def last_high(self) -> float:
        return self.forces.detail

    @property
    def last_kick(self) -> float:
        return self.forces.transient

    @property
    def last_voice(self) -> float:
        return self.forces.voice

    @property
    def impact(self) -> float:
        return self.forces.transient

    @property
    def spectral_bands(self) -> tuple[float, ...]:
        return self.forces.bands

    @property
    def spectral_hits(self) -> tuple[float, ...]:
        return self.forces.hits

    def resize(self, width: int, height: int) -> None:
        width = max(10, width)
        height = max(6, height)
        if width == self.w and height == self.h:
            return
        first_viewport = self.w == 0 or self.h == 0
        self.w = width
        self.h = height
        if first_viewport:
            self.organism.seed_for_tile(width, height, len(self.organism.bodies))
        self.field_frame = FieldFrame.empty(width, height)

    def clear(self) -> None:
        capacity = max(1, len(self.organism.bodies))
        self.mapper.reset()
        self.affect_tracker.reset()
        self.narrative_tracker.reset()
        self.organism.reset(capacity)
        self.wax.reset()
        self.organism.seed_for_tile(self.w, self.h, capacity)
        self.forces = AudioForces()
        self.render_forces = AudioForces()
        self.affect = AffectiveState()
        self.narrative = NarrativeState()
        self.reactions.clear()
        self._last_step_at = None
        self._last_audio_key = None
        self.phase = 0.0
        self.reactivity = 1.0
        self.frames_seen = 0
        self.field_frame = FieldFrame.empty(self.w, self.h)

    def observe(
        self,
        frame: AudioFrame,
        mode: str,
        reactivity: float,
        behavior: BehaviorProfile | None = None,
    ) -> bool:
        """Map each new capture frame even when the display is between draws."""

        key = (
            float(frame.timestamp),
            mode,
            behavior.name if behavior is not None else "",
            round(reactivity, 4),
        )
        if frame.timestamp > 0.0 and key == self._last_audio_key:
            return False
        started = time.perf_counter()
        self.forces = self.mapper.map(frame, mode, reactivity)
        if behavior is not None:
            self.forces = apply_behavior_profile(self.forces, behavior)
        self.metrics.map_seconds += time.perf_counter() - started
        started = time.perf_counter()
        self.affect = self.affect_tracker.update(self.forces, float(frame.timestamp))
        self.narrative = self.narrative_tracker.update(
            self.forces,
            self.affect,
            float(frame.timestamp),
        )
        self.metrics.affect_seconds += time.perf_counter() - started
        self.reactions.observe(self.forces, self.affect, time.monotonic())
        self._last_audio_key = key
        self.reactivity = reactivity
        self.frames_seen += 1
        return True

    def step(
        self,
        frame: AudioFrame,
        mode: str,
        profile: str,
        reactivity: float,
        lava_config: LavaConfig,
        cell_aspect: float = 1.85,
        rasterize: bool = True,
        advance_physics: bool = True,
        behavior: BehaviorProfile | None = None,
        embody_posture: bool = False,
        embody_wax: bool = False,
        surface_ripples: bool = False,
    ) -> None:
        if self.w <= 0 or self.h <= 0:
            return
        self.observe(frame, mode, reactivity, behavior)
        self.render_forces = self.reactions.consume(self.forces)
        if advance_physics:
            now = time.monotonic()
            nominal_fps = (
                22.0 if profile == "atlas" else 12.0 if profile == "power-save" else 28.0
            )
            elapsed = (
                1.0 / nominal_fps if self._last_step_at is None else now - self._last_step_at
            )
            elapsed = max(1.0 / 120.0, min(0.5, elapsed))
            self._last_step_at = now

            substeps = max(1, math.ceil(elapsed / (1.0 / 12.0)))
            dt = elapsed / substeps
            physics_started = time.perf_counter()
            for _ in range(substeps):
                self.organism.update(
                    dt,
                    self.render_forces,
                    self.w,
                    self.h,
                    lava_config,
                    self.motion_profile,
                    cell_aspect,
                    self.affect,
                    self.narrative,
                    behavior,
                    embody_posture,
                    surface_ripples,
                )
                if embody_wax:
                    self.wax.advance(
                        dt,
                        self.render_forces,
                        self.narrative,
                        behavior.name if behavior is not None else mode,
                    )
            self.metrics.physics_steps += substeps
            self.metrics.physics_seconds += time.perf_counter() - physics_started
        if rasterize:
            raster_started = time.perf_counter()
            self.field_frame = self.renderer.render(
                self.organism.bodies,
                self.render_forces,
                self.w,
                self.h,
                self.organism.phase,
                self.motion_profile,
                cell_aspect,
            )
            self.metrics.raster_seconds += time.perf_counter() - raster_started

        self.phase = self.organism.phase
