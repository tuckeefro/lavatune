"""Audio-to-force mapping, persistent body motion, and scalar-field rendering."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .audio import AudioFrame
from .config import LavaConfig


CELL_ASPECT = 1.85
DEVIATION_WINDOW_SECONDS = 2.4
DEVIATION_WARMUP_SECONDS = 0.45


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def lerp(current: float, target: float, amount: float) -> float:
    return current + (target - current) * clamp(amount)


def time_amount(reference_amount: float, dt: float, reference_fps: float = 22.0) -> float:
    """Convert a frame-relative smoothing amount into elapsed-time smoothing."""

    return 1.0 - (1.0 - clamp(reference_amount)) ** (clamp(dt, 1.0 / 120.0, 1.0) * reference_fps)


@dataclass(slots=True, frozen=True)
class AudioForces:
    """Physical vocabulary shared by analysis, motion, and rendering."""

    bass: float = 0.0
    voice: float = 0.0
    detail: float = 0.0
    transient: float = 0.0
    energy: float = 0.0
    level: float = -1.0
    tone: float = 0.5
    tempo: float = 0.0
    pulse: float = 0.0
    flux: float = 0.0
    rhythm_density: float = 0.0
    rhythm_impulse: float = 0.0
    bands: tuple[float, ...] = (0.0,) * 8
    hits: tuple[float, ...] = (0.0,) * 8
    deviations: tuple[float, ...] = (0.0,) * 8


@dataclass(slots=True, frozen=True)
class AffectiveState:
    """Slow acoustic posture, intentionally not an emotion classifier."""

    weight: float = 0.0
    agitation: float = 0.0
    cohesion: float = 0.5
    tension: float = 0.0
    openness: float = 0.0
    release: float = 0.0
    intimacy: float = 0.0
    volatility: float = 0.0
    novelty: float = 0.0
    fragility: float = 0.0
    yearning: float = 0.0
    catharsis: float = 0.0
    restraint: float = 0.0
    snap: float = 0.0


@dataclass(slots=True, frozen=True)
class NarrativeState:
    """Authored temporal meaning without named-emotion classification."""

    expectation: float = 0.0
    interruption: float = 0.0
    resolution: float = 0.0


class AffectiveTracker:
    """Accumulate gesture, phrase, and atmosphere cues with constant work."""

    def __init__(self) -> None:
        self.state = AffectiveState()
        self._last_energy = 0.0
        self._last_bands = (0.0,) * 8
        self._last_at = 0.0
        self._restraint_seconds = 0.0
        self._slow_energy = 0.0
        self._slow_bands = (0.0,) * 8
        self._context_initialized = False
        self._snap_candidate = 0.0
        self._snap_candidate_age = 0.0

    def reset(self) -> None:
        self.__init__()

    def update(self, forces: AudioForces, timestamp: float) -> AffectiveState:
        dt = 1.0 / 16.0
        if timestamp > 0.0 and self._last_at > 0.0 and timestamp > self._last_at:
            dt = clamp(timestamp - self._last_at, 1.0 / 120.0, 0.35)
        if timestamp > 0.0:
            self._last_at = timestamp

        bands = forces.bands or (0.0,) * 8
        signal_level = forces.level if forces.level >= 0.0 else forces.energy
        mean = sum(bands) / max(1, len(bands))
        spread = math.sqrt(sum((value - mean) ** 2 for value in bands) / max(1, len(bands)))
        novelty = sum(abs(value - old) for value, old in zip(bands, self._last_bands)) / 8.0
        novelty = clamp(novelty * 1.8 + forces.flux * 0.55 + max(forces.hits) * 0.25)
        self._last_bands = tuple(bands)

        if not self._context_initialized:
            self._slow_energy = signal_level
            self._slow_bands = tuple(bands)
            self._context_initialized = True
        energy_contrast = max(0.0, signal_level - self._slow_energy)
        band_rises = tuple(
            current - baseline for current, baseline in zip(bands, self._slow_bands)
        )
        band_contrast = sum(max(0.0, rise) for rise in band_rises) / max(
            1, len(band_rises)
        )
        coherent_rises = sum(rise >= 0.10 for rise in band_rises)

        # Restraint establishes context, then saturates. Continued calm never
        # charges a larger response than an already-qualified short passage.
        restrained = (
            signal_level <= 0.38
            and forces.transient <= 0.16
            and forces.pulse <= 0.18
            and forces.rhythm_density <= 0.22
        )
        if restrained:
            self._restraint_seconds = min(8.0, self._restraint_seconds + dt)
        else:
            self._restraint_seconds = max(0.0, self._restraint_seconds - dt * 0.55)
        restraint = clamp(self._restraint_seconds / 8.0)

        # A snap needs both a credible attack and a coherent multi-band change,
        # then one confirming frame of sustained contrast. This keeps a lone
        # notification local while allowing a musical break to open the group.
        attack_gate = (
            forces.transient >= 0.38
            or forces.pulse >= 0.42
            or forces.rhythm_impulse >= 0.30
        )
        coherent_change = energy_contrast >= 0.28 and coherent_rises >= 3
        contrast_strength = clamp(energy_contrast * 0.85 + band_contrast * 0.75)
        snap_target = 0.0
        if attack_gate and coherent_change and restraint >= 0.12:
            self._snap_candidate = max(self._snap_candidate, contrast_strength)
            self._snap_candidate_age = 0.0
        elif self._snap_candidate > 0.0:
            self._snap_candidate_age += dt
            sustained_change = energy_contrast >= 0.20 and coherent_rises >= 3
            if sustained_change and self._snap_candidate_age <= 0.24:
                snap_target = clamp(self._snap_candidate * 1.35) * restraint
                self._restraint_seconds = 0.0
                restraint = 0.0
                self._snap_candidate = 0.0
                self._snap_candidate_age = 0.0
            elif self._snap_candidate_age > 0.24 or energy_contrast < 0.10:
                self._snap_candidate = 0.0
                self._snap_candidate_age = 0.0

        context_amount = 1.0 - math.exp(-dt / 12.0)
        self._slow_energy = lerp(self._slow_energy, signal_level, context_amount)
        self._slow_bands = tuple(
            lerp(baseline, current, context_amount)
            for baseline, current in zip(self._slow_bands, bands)
        )

        agitation_target = clamp(
            forces.transient * 0.48
            + forces.pulse * 0.30
            + forces.flux * 0.42
            + forces.tempo * 0.18
            + forces.rhythm_density * 0.24
        )
        cohesion_target = clamp(1.0 - spread * 2.4 + forces.voice * 0.10)
        openness_target = clamp(spread * 2.1 + forces.detail * 0.28 + forces.tone * 0.12)
        weight_target = clamp(forces.bass * 0.72 + forces.energy * 0.20)
        intimacy_target = clamp(
            forces.voice * (0.82 - forces.transient * 0.32) + cohesion_target * 0.12
        )
        tension_target = clamp(
            forces.energy * 0.34 + agitation_target * 0.52 + forces.detail * 0.14
        )
        energy_rise = max(0.0, forces.energy - self._last_energy)
        energy_drop = max(0.0, self._last_energy - forces.energy)
        tension_drop = max(0.0, self.state.tension - tension_target)
        release_target = clamp(energy_drop * 1.4 + tension_drop * 1.8 + forces.pulse * 0.10)
        volatility_target = clamp(
            abs(forces.energy - self._last_energy) * 1.6 + novelty * 0.62
        )
        fragility_target = clamp(
            forces.detail * (0.92 - forces.energy * 0.62)
            + forces.voice * (1.0 - forces.transient) * 0.18
        )
        yearning_target = clamp(
            forces.voice * 0.38
            + forces.detail * 0.26
            + self.state.tension * 0.35
            + openness_target * 0.12
            - agitation_target * 0.18
        )
        catharsis_target = clamp(
            self.state.tension
            * (
                forces.transient * 0.60
                + forces.pulse * 0.50
                + energy_rise * 1.10
            )
            + release_target * 0.30
            + snap_target * 0.90
        )
        self._last_energy = forces.energy

        phrase = 1.0 - math.exp(-dt / 2.6)
        atmosphere = 1.0 - math.exp(-dt / 5.5)
        fast = 1.0 - math.exp(-dt / 0.32)
        release = max(
            self.state.release * math.exp(-dt / 1.15),
            release_target,
        )
        catharsis = max(
            self.state.catharsis * math.exp(-dt / 0.95),
            catharsis_target,
        )
        snap = max(
            self.state.snap * math.exp(-dt / 0.48),
            snap_target,
        )
        self.state = AffectiveState(
            weight=lerp(self.state.weight, weight_target, atmosphere),
            agitation=lerp(self.state.agitation, agitation_target, phrase),
            cohesion=lerp(self.state.cohesion, cohesion_target, atmosphere),
            tension=lerp(self.state.tension, tension_target, phrase),
            openness=lerp(self.state.openness, openness_target, atmosphere),
            release=release,
            intimacy=lerp(self.state.intimacy, intimacy_target, atmosphere),
            volatility=lerp(self.state.volatility, volatility_target, phrase),
            novelty=lerp(self.state.novelty, novelty, fast),
            fragility=lerp(self.state.fragility, fragility_target, phrase),
            yearning=lerp(self.state.yearning, yearning_target, phrase),
            catharsis=catharsis,
            restraint=restraint,
            snap=snap,
        )
        return self.state


class NarrativeTracker:
    """Interpret current gestures through recent predictability and posture."""

    def __init__(self) -> None:
        self.state = NarrativeState()
        self._last_at = 0.0

    def reset(self) -> None:
        self.__init__()

    def update(
        self,
        forces: AudioForces,
        affect: AffectiveState,
        timestamp: float,
    ) -> NarrativeState:
        dt = 1.0 / 16.0
        if timestamp > 0.0 and self._last_at > 0.0 and timestamp > self._last_at:
            dt = clamp(timestamp - self._last_at, 1.0 / 120.0, 0.35)
        if timestamp > 0.0:
            self._last_at = timestamp

        signal_level = forces.level if forces.level >= 0.0 else forces.energy
        predictability = clamp(
            forces.tempo * 0.35
            + (1.0 - forces.flux) * 0.25
            + (1.0 - affect.volatility) * 0.40
        )
        activity_gate = clamp((signal_level - 0.03) / 0.20)
        predictability *= activity_gate
        expectation = lerp(
            self.state.expectation,
            predictability,
            time_amount(0.06, dt),
        )
        surprise = clamp(
            forces.transient * 0.50
            + forces.flux * 0.55
            + max(forces.deviations, default=0.0) * 0.35
            + affect.snap * 0.65
        )
        interruption_target = clamp(self.state.expectation * surprise)
        interruption = max(
            self.state.interruption * math.exp(-dt / 0.45),
            interruption_target,
        )
        resolution_target = clamp(
            affect.tension * (affect.release * 0.70 + affect.catharsis * 0.45)
        )
        resolution = max(
            self.state.resolution * math.exp(-dt / 1.20),
            resolution_target,
        )
        expectation *= 1.0 - interruption * 0.35

        self.state = NarrativeState(
            expectation=expectation,
            interruption=interruption,
            resolution=resolution,
        )
        return self.state


@dataclass(slots=True)
class _AdaptiveRange:
    floor: float = 0.0
    ceiling: float = 0.12

    def normalize(self, value: float, dt: float) -> float:
        # The asymmetric rates preserve contrast without pumping when a source
        # changes volume or a quiet passage follows a loud one.
        value = max(0.0, value)
        if value <= self.floor:
            self.floor = value
        else:
            self.floor += (value - self.floor) * time_amount(0.002, dt)
        if value >= self.ceiling:
            self.ceiling = value
        else:
            self.ceiling += (value - self.ceiling) * time_amount(0.012, dt)
        self.ceiling = max(self.ceiling, self.floor + 0.05)
        return clamp((value - self.floor) / (self.ceiling - self.floor))


class AudioForceMapper:
    """Turns audio measurements into physical controls, never luminance."""

    def __init__(self) -> None:
        self._ranges = [_AdaptiveRange() for _ in range(4)]
        self._bass = 0.0
        self._voice = 0.0
        self._detail = 0.0
        self._energy = 0.0
        self._transient = 0.0
        self._tone = 0.5
        self._tempo = 0.0
        self._pulse = 0.0
        self._rhythm_density = 0.0
        self._last_density_onset_at = 0.0
        self._last_tempo_onset_at = 0.0
        self._onset_gate_until = 0.0
        self._raw_bands = [0.0] * 8
        self._bands = [0.0] * 8
        self._hits = [0.0] * 8
        self._deviation_means = [0.0] * 8
        self._deviation_variances = [0.0004] * 8
        self._deviation_elapsed = 0.0
        self._deviation_initialized = False
        self._last_frame_at = 0.0

    def reset(self) -> None:
        self.__init__()

    def map(self, frame: AudioFrame, mode: str, reactivity: float) -> AudioForces:
        timestamp = float(frame.timestamp)
        dt = 1.0 / 22.0
        if timestamp > 0.0 and self._last_frame_at > 0.0 and timestamp > self._last_frame_at:
            dt = clamp(timestamp - self._last_frame_at, 1.0 / 120.0, 1.0 / 3.0)
        if timestamp > 0.0:
            self._last_frame_at = timestamp
        bands = _eight_bands(frame.bands, frame.rms)
        deviations = self._deviation_spikes(bands, dt)
        band_total = sum(bands)
        tone = (
            sum(index * value for index, value in enumerate(bands))
            / max(0.0001, band_total * 7.0)
        )
        flux = sum(max(0.0, current - previous) for current, previous in zip(bands, self._raw_bands)) / 8.0
        self._raw_bands = bands[:]
        self._tone = lerp(self._tone, tone, time_amount(0.14, dt))
        low_raw = sum(bands[:3]) / 3.0
        voice_raw = sum(bands[2:6]) / 4.0
        detail_raw = max(sum(bands[5:]) / 3.0, frame.zcr * 0.72)
        energy_raw = clamp(frame.rms)

        low = self._ranges[0].normalize(low_raw, dt)
        voice = self._ranges[1].normalize(voice_raw, dt)
        detail = self._ranges[2].normalize(detail_raw, dt)
        energy = self._ranges[3].normalize(energy_raw, dt)

        previous_bass = self._bass
        previous_energy = self._energy
        self._bass = lerp(self._bass, low, time_amount(0.24, dt))
        self._voice = lerp(self._voice, voice, time_amount(0.20, dt))
        self._detail = lerp(self._detail, detail, time_amount(0.16, dt))
        self._energy = lerp(self._energy, energy, time_amount(0.18, dt))

        attack = clamp(frame.attack)
        onset = max(0.0, self._bass - previous_bass) * 1.4
        onset += max(0.0, self._energy - previous_energy) * 1.1
        transient_target = clamp(attack * 0.92 + onset)
        self._transient = max(self._transient * (0.58 ** (dt * 22.0)), transient_target)
        pulse_target = clamp(transient_target * 0.70 + flux * 1.45)
        self._pulse = max(self._pulse * (0.66 ** (dt * 22.0)), pulse_target)

        # Beat tempo and rapid subdivision density are related but distinct.
        # A short refractory gate rejects duplicate analysis frames while still
        # accepting fast 1/16-note and machine-gun patterns. Fast events do not
        # move the tempo anchor until enough time has elapsed to infer a beat.
        self._rhythm_density *= math.exp(-dt / 0.42)
        rhythm_impulse = 0.0
        onset_cue = attack >= 0.045 or flux >= 0.035
        onset_event = (
            pulse_target > 0.20
            and onset_cue
            and timestamp > 0.0
            and timestamp >= self._onset_gate_until
        )
        if onset_event:
            rhythm_impulse = clamp(pulse_target * 0.70 + attack * 0.30)
            density_interval = (
                timestamp - self._last_density_onset_at
                if self._last_density_onset_at
                else 0.0
            )
            if 0.035 <= density_interval <= 0.22:
                density_target = clamp((0.22 - density_interval) / 0.16)
                density_target *= 0.60 + rhythm_impulse * 0.40
                self._rhythm_density = max(self._rhythm_density, density_target)
            self._last_density_onset_at = timestamp
            self._onset_gate_until = timestamp + 0.035

            tempo_interval = (
                timestamp - self._last_tempo_onset_at
                if self._last_tempo_onset_at
                else 0.0
            )
            if not self._last_tempo_onset_at or tempo_interval > 1.5:
                self._last_tempo_onset_at = timestamp
            elif tempo_interval >= 0.14:
                pulses_per_second = 1.0 / tempo_interval
                tempo_target = clamp((pulses_per_second - 0.65) / 3.1)
                self._tempo = lerp(self._tempo, tempo_target, time_amount(0.24, dt))
                self._last_tempo_onset_at = timestamp
        else:
            self._tempo = lerp(self._tempo, clamp(flux * 2.8), time_amount(0.025, dt))

        # Keep both a smooth spectral shape and short-lived per-band rises. The
        # organism uses the former for shape and the latter for local impacts.
        for index, current in enumerate(bands):
            previous = self._bands[index]
            rise = max(0.0, current - previous)
            self._bands[index] = max(
                previous * (0.72 ** (dt * 22.0)),
                lerp(previous, current, time_amount(0.22, dt)),
            )
            self._hits[index] = max(
                self._hits[index] * (0.48 ** (dt * 22.0)),
                rise * 1.9 + attack * current * 0.28,
            )

        response = clamp(reactivity, 0.4, 2.2)
        if mode in {"speech", "book"}:
            bass_gain, voice_gain, detail_gain, hit_gain = 0.66, 0.92, 0.55, 0.62
        else:
            bass_gain, voice_gain, detail_gain, hit_gain = 0.90, 0.72, 0.78, 0.90

        return AudioForces(
            bass=clamp(self._bass * bass_gain * response),
            voice=clamp(self._voice * voice_gain * response),
            detail=clamp(self._detail * detail_gain * response),
            transient=clamp(self._transient * hit_gain * response),
            energy=clamp(self._energy * response),
            level=clamp(frame.rms),
            tone=clamp(self._tone),
            tempo=clamp(self._tempo),
            pulse=clamp(self._pulse * hit_gain * response),
            flux=clamp(flux * response * 2.0),
            rhythm_density=clamp(self._rhythm_density * response),
            rhythm_impulse=clamp(rhythm_impulse * hit_gain * response),
            bands=tuple(clamp(value * response) for value in self._bands),
            hits=tuple(clamp(value * response) for value in self._hits),
            deviations=tuple(clamp(value * response) for value in deviations),
        )

    def _deviation_spikes(self, bands: list[float], dt: float) -> list[float]:
        """Measure upward surprise against a noise-aware rolling band average."""

        if not self._deviation_initialized:
            self._deviation_means = bands[:]
            self._deviation_initialized = True
            return [0.0] * 8

        self._deviation_elapsed += dt
        ready = self._deviation_elapsed >= DEVIATION_WARMUP_SECONDS
        amount = 1.0 - math.exp(-dt / DEVIATION_WINDOW_SECONDS)
        deviations = []
        for index, current in enumerate(bands):
            mean = self._deviation_means[index]
            variance = self._deviation_variances[index]
            delta = current - mean
            noise = math.sqrt(max(0.0001, variance))
            threshold = 0.035 + noise * 1.10
            deviations.append(
                clamp((delta - threshold) / (0.16 + noise)) if ready else 0.0
            )
            next_mean = mean + delta * amount
            residual = current - next_mean
            self._deviation_means[index] = next_mean
            self._deviation_variances[index] = max(
                0.0001,
                variance + (residual * residual - variance) * amount,
            )
        return deviations


@dataclass(slots=True, frozen=True)
class TileComposition:
    name: str
    habitat: str
    active_bodies: int
    radius_scale: float
    vertical_flow: float
    horizontal_flow: float
    wall_padding: float


def compose_tile(width: int, height: int, requested_bodies: int) -> TileComposition:
    """Choose a habitat for a tile without changing normalized body positions."""

    width = max(10, width)
    height = max(6, height)
    area = width * height
    visual_aspect = width / max(1.0, height * 1.85)

    if area < 320:
        count, radius_scale, size = 1, 1.34, "micro"
    elif area < 760:
        count, radius_scale, size = 3, 1.10, "small"
    elif area < 1500:
        count, radius_scale, size = 4, 1.00, "medium"
    else:
        count, radius_scale, size = 6, 0.90, "large"

    if count == 1:
        habitat = "micro"
        vertical_flow, horizontal_flow = 0.92, 0.92
    elif visual_aspect < 0.78:
        habitat = "chimney"
        vertical_flow, horizontal_flow = 1.18, 0.68
        radius_scale *= 0.94
    elif visual_aspect > 1.75:
        habitat = "current"
        vertical_flow, horizontal_flow = 0.78, 1.16
    else:
        habitat = "basin"
        vertical_flow, horizontal_flow = 1.0, 1.0

    return TileComposition(
        name=habitat if habitat == "micro" else f"{size}-{habitat}",
        habitat=habitat,
        active_bodies=max(1, min(requested_bodies, count)),
        radius_scale=radius_scale,
        vertical_flow=vertical_flow,
        horizontal_flow=horizontal_flow,
        wall_padding=0.035 if area < 760 else 0.045,
    )


_HABITAT_ANCHORS: dict[str, tuple[tuple[float, float], ...]] = {
    "micro": ((0.50, 0.54),),
    "chimney": (
        (0.47, 0.74),
        (0.54, 0.46),
        (0.44, 0.22),
        (0.58, 0.62),
        (0.40, 0.36),
        (0.52, 0.12),
    ),
    "current": (
        (0.18, 0.61),
        (0.46, 0.42),
        (0.76, 0.56),
        (0.32, 0.72),
        (0.62, 0.28),
        (0.88, 0.38),
    ),
    "basin": (
        (0.25, 0.72),
        (0.64, 0.28),
        (0.77, 0.70),
        (0.28, 0.28),
        (0.50, 0.53),
        (0.78, 0.34),
    ),
}


def habitat_anchor(composition: TileComposition, index: int, phase: float) -> tuple[float, float]:
    """Return a slowly moving home region, not a fixed animation waypoint."""

    anchors = _HABITAT_ANCHORS[composition.habitat]
    x, y = anchors[index % len(anchors)]
    offset = phase * (0.23 + index * 0.017) + index * 1.71
    if composition.habitat == "current":
        x += math.sin(offset) * 0.045
        y += math.cos(offset * 0.71) * 0.025
    elif composition.habitat == "chimney":
        x += math.sin(offset * 0.83) * 0.025
        y += math.cos(offset) * 0.040
    elif composition.habitat == "basin":
        x += math.cos(offset) * 0.032
        y += math.sin(offset) * 0.032
    return x, y


def tile_axis_scales(
    width: int,
    height: int,
    cell_aspect: float = CELL_ASPECT,
) -> tuple[float, float]:
    """Convert one physical tile-relative distance into normalized x/y units."""

    physical_width = float(max(10, width))
    physical_height = float(max(6, height)) * clamp(cell_aspect, 1.0, 3.0)
    reference = min(physical_width, physical_height)
    return reference / physical_width, reference / physical_height


def adaptive_centroid_axis(
    position: float,
    target: float,
    velocity: float,
    dead_zone: float,
) -> float:
    """Return a soft shared correction only when a cast leaves its useful middle."""

    displacement = position - target
    distance = abs(displacement)
    if distance <= dead_zone:
        return 0.0

    available_edge = max(target, 1.0 - target)
    pressure = clamp((distance - dead_zone) / max(0.05, available_edge - dead_zone))
    pressure = pressure * pressure * (3.0 - 2.0 * pressure)
    direction = 1.0 if displacement > 0.0 else -1.0
    leash = -direction * pressure * 0.22

    # Remove only momentum that carries the whole cast farther outward. An
    # inward return and motion parallel to an edge remain part of the current.
    outward_velocity = velocity * direction
    momentum_bleed = -velocity * pressure * 1.35 if outward_velocity > 0.0 else 0.0
    return leash + momentum_bleed


def circulation_at(
    composition: TileComposition,
    x: float,
    y: float,
    phase: float,
) -> tuple[float, float]:
    """Return a continuous current shaped by the tile rather than by body index."""

    dx = x - 0.5
    dy = y - 0.5
    if composition.habitat == "chimney":
        # Warm material rises through the middle and returns along the walls.
        return (
            math.sin(y * math.tau + phase * 0.31) * 0.34,
            -math.cos(dx * math.tau) * 0.92,
        )
    if composition.habitat == "current":
        # Wide tiles carry a slow horizontal loop, including a quiet return lane.
        return (
            math.cos(dy * math.tau) * 0.94,
            math.sin(x * math.tau + phase * 0.27) * 0.28,
        )

    distance = max(0.12, math.hypot(dx, dy))
    orbit_x, orbit_y = -dy / distance, dx / distance
    if composition.habitat == "micro":
        return orbit_x * 0.72, orbit_y * 0.72
    breathing = 0.82 + math.sin(phase * 0.23 + distance * 4.0) * 0.16
    return orbit_x * breathing, orbit_y * breathing


@dataclass(slots=True, frozen=True)
class MotionProfile:
    name: str
    inertia: float
    idle_flow: float
    buoyancy: float
    collision: float
    audio_push: float
    surface_motion: float


MOTION_PROFILES: dict[str, MotionProfile] = {
    "neutral": MotionProfile("neutral", 0.90, 0.74, 0.58, 0.58, 0.76, 0.66),
    "heavy": MotionProfile("heavy", 0.95, 0.48, 0.44, 0.36, 0.58, 0.38),
    "buoyant": MotionProfile("buoyant", 0.88, 0.92, 0.78, 0.68, 0.72, 0.62),
    "tactile": MotionProfile("tactile", 0.84, 0.76, 0.64, 0.86, 1.00, 0.92),
}


@dataclass(slots=True, frozen=True)
class BodyCharacter:
    """An authored body identity that persists across every tile habitat."""

    name: str
    band: int
    size: float
    mass: float
    idle: float
    bass: float
    voice: float
    detail: float
    deformation: float


BODY_CHARACTERS: tuple[BodyCharacter, ...] = (
    BodyCharacter("ballast", 1, 0.70, 1.35, 0.70, 1.35, 0.35, 0.25, 0.78),
    BodyCharacter("listener", 3, 0.50, 1.00, 0.96, 0.55, 1.40, 0.58, 1.00),
    BodyCharacter("glint", 6, 0.18, 0.64, 1.24, 0.22, 0.58, 1.50, 1.34),
    BodyCharacter("drifter", 4, 0.36, 0.88, 1.06, 0.62, 0.82, 0.82, 0.94),
    BodyCharacter("echo", 2, 0.38, 0.82, 1.10, 0.72, 0.92, 0.62, 1.04),
    BodyCharacter("spark", 7, 0.23, 0.58, 1.30, 0.18, 0.48, 1.62, 1.42),
)


@dataclass(slots=True)
class Body:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    base_radius: float
    phase: float
    band: int
    character: BodyCharacter
    presence: float = 0.0
    stretch_x: float = 1.0
    stretch_y: float = 1.0
    wall_pressure: float = 0.0
    wall_pressure_x: float = 0.0
    wall_pressure_y: float = 0.0
    acoustic_pressure: float = 0.0
    pressure_angle: float = 0.0
    afterglow: float = 0.0
    spike: float = 0.0
    impact_angle: float = 0.0


@dataclass(slots=True)
class PressureWave:
    """A short acoustic disturbance traveling through the shared tile."""

    x: float
    y: float
    age: float
    strength: float
    speed: float


class AcousticOrganism:
    """Persistent bodies whose motion is disturbed by semantic audio forces."""

    def __init__(self, body_limit: int = 8, seed: int = 719) -> None:
        self._random = random.Random(seed)
        self.bodies: list[Body] = []
        self.pressure_waves: list[PressureWave] = []
        self.phase = 0.0
        self._last_event = 0.0
        self._wave_cooldown = 0.0
        self.composition = compose_tile(40, 18, body_limit)
        self.ensure_capacity(body_limit)

    def reset(self, body_limit: int | None = None) -> None:
        limit = body_limit if body_limit is not None else max(1, len(self.bodies))
        self.bodies = []
        self.pressure_waves = []
        self.phase = 0.0
        self._last_event = 0.0
        self._wave_cooldown = 0.0
        self.ensure_capacity(limit)

    def ensure_capacity(self, count: int) -> None:
        count = max(1, min(10, count))
        while len(self.bodies) < count:
            index = len(self.bodies)
            character = BODY_CHARACTERS[index % len(BODY_CHARACTERS)]
            angle = self._random.uniform(0.0, math.tau)
            anchor_x, anchor_y = _HABITAT_ANCHORS["basin"][index % 6]
            radius = 0.10 + character.size * 0.075
            self.bodies.append(
                Body(
                    x=anchor_x + self._random.uniform(-0.025, 0.025),
                    y=anchor_y + self._random.uniform(-0.025, 0.025),
                    vx=math.cos(angle) * self._random.uniform(0.015, 0.035),
                    vy=math.sin(angle) * self._random.uniform(0.015, 0.035),
                    radius=radius,
                    base_radius=radius,
                    phase=self._random.uniform(0.0, math.tau),
                    band=character.band,
                    character=character,
                    impact_angle=self._random.uniform(0.0, math.tau),
                )
            )

    def center_of_mass(self, count: int | None = None) -> tuple[float, float]:
        """Return the visual centroid without exposing it as a body waypoint."""

        selected = self.bodies[: count or self.composition.active_bodies]
        if not selected:
            return 0.5, 0.5
        weights = [
            body.character.mass * body.radius * body.radius * max(0.15, body.presence)
            for body in selected
        ]
        total = sum(weights)
        return (
            sum(body.x * weight for body, weight in zip(selected, weights)) / total,
            sum(body.y * weight for body, weight in zip(selected, weights)) / total,
        )

    def seed_for_tile(self, width: int, height: int, requested: int) -> None:
        """Place a never-rendered cast in its first habitat without affecting resizes."""

        if self.phase != 0.0 or any(body.presence > 0.0 for body in self.bodies):
            return
        self.composition = compose_tile(width, height, requested)
        for index, body in enumerate(self.bodies):
            body.x, body.y = habitat_anchor(self.composition, index, 0.0)
        center_x, center_y = self.center_of_mass(self.composition.active_bodies)
        shift_x = 0.5 - center_x
        shift_y = 0.52 - center_y
        for body in self.bodies[: self.composition.active_bodies]:
            body.x = clamp(body.x + shift_x, 0.06, 0.94)
            body.y = clamp(body.y + shift_y, 0.06, 0.94)

    def _advance_pressure_waves(self, dt: float, forces: AudioForces) -> None:
        """Emit on rising events, then let pressure cross the vessel over time."""

        self._wave_cooldown = max(0.0, self._wave_cooldown - dt)
        event = max(
            forces.transient * 0.92,
            forces.pulse * 0.78,
            forces.flux * 0.46,
            forces.rhythm_impulse * 0.70,
        )
        rising = event > max(0.18, self._last_event + 0.055)
        if rising and self._wave_cooldown <= 0.0:
            # Pitch chooses an edge, while phase prevents repeated beats from
            # entering at exactly the same point.
            angle = math.pi * (0.65 + forces.tone * 1.15) + math.sin(self.phase) * 0.08
            self.pressure_waves.append(
                PressureWave(
                    x=clamp(0.5 + math.cos(angle) * 0.54, 0.02, 0.98),
                    y=clamp(0.5 + math.sin(angle) * 0.54, 0.02, 0.98),
                    age=0.0,
                    strength=clamp(event),
                    speed=0.72 + forces.tempo * 0.36 + forces.energy * 0.12,
                )
            )
            self.pressure_waves = self.pressure_waves[-3:]
            self._wave_cooldown = 0.10
        self._last_event = event

        alive: list[PressureWave] = []
        for wave in self.pressure_waves:
            wave.age += dt
            wave.strength *= math.exp(-0.72 * dt)
            if wave.age < 2.2 and wave.strength > 0.025:
                alive.append(wave)
        self.pressure_waves = alive

    def update(
        self,
        dt: float,
        forces: AudioForces,
        width: int,
        height: int,
        lava_config: LavaConfig,
        motion_name: str = "neutral",
        cell_aspect: float = CELL_ASPECT,
        affective: AffectiveState | None = None,
        narrative: NarrativeState | None = None,
    ) -> TileComposition:
        dt = clamp(dt, 1.0 / 120.0, 1.0 / 12.0)
        requested = max(1, min(10, lava_config.blobs))
        self.ensure_capacity(requested)
        self.composition = compose_tile(width, height, requested)
        motion = MOTION_PROFILES.get(motion_name, MOTION_PROFILES["neutral"])
        drift = clamp(lava_config.drift, 0.05, 0.8)
        viscosity = clamp(lava_config.viscosity, 0.7, 0.99)
        radius_min = clamp(lava_config.radius_min, 0.04, 0.3)
        radius_max = clamp(lava_config.radius_max, radius_min, 0.35)
        affect = affective or AffectiveState()
        story = narrative or NarrativeState()
        self.phase += dt * (
            0.42
            + drift * 0.72
            + forces.voice * 0.16
            + forces.tempo * 0.34
            + forces.pulse * 0.18
            + forces.rhythm_density * 0.20
            + affect.agitation * 0.10
            + affect.snap * 0.18
            + story.interruption * 0.10
            + story.resolution * 0.04
        )
        self._advance_pressure_waves(dt, forces)
        center_x = 0.5 + math.sin(self.phase * 0.37) * 0.035
        center_y = (
            0.53
            + math.cos(self.phase * 0.29) * 0.028
            + affect.weight * 0.026
            - affect.openness * 0.014
            - affect.yearning * 0.012
        )
        axis_x, axis_y = tile_axis_scales(width, height, cell_aspect)

        # Resolve overlap as acceleration rather than teleporting bodies. This
        # keeps identity and momentum intact through resize recomposition.
        separation_x = [0.0] * len(self.bodies)
        separation_y = [0.0] * len(self.bodies)
        active_count = self.composition.active_bodies
        impact_target = min(
            range(active_count),
            key=lambda item: abs(self.bodies[item].band / 7.0 - forces.tone),
        )
        for left in range(active_count):
            for right in range(left + 1, active_count):
                first = self.bodies[left]
                second = self.bodies[right]
                dx = (second.x - first.x) / axis_x
                dy = (second.y - first.y) / axis_y
                distance = math.hypot(dx, dy)
                preferred = (first.radius + second.radius) * 1.04
                if distance >= preferred:
                    continue
                if distance < 0.0001:
                    angle = first.phase - second.phase
                    nx, ny = math.cos(angle), math.sin(angle)
                else:
                    nx, ny = dx / distance, dy / distance
                pressure = (preferred - distance) * 0.86
                separation_x[left] -= nx * pressure * axis_x
                separation_y[left] -= ny * pressure * axis_y
                separation_x[right] += nx * pressure * axis_x
                separation_y[right] += ny * pressure * axis_y

        mean_vx = sum(body.vx for body in self.bodies[:active_count]) / active_count
        mean_vy = sum(body.vy for body in self.bodies[:active_count]) / active_count
        mass_x, mass_y = self.center_of_mass(active_count)
        if self.composition.habitat == "current":
            group_pull_x = adaptive_centroid_axis(mass_x, 0.5, mean_vx, 0.18)
            group_pull_y = adaptive_centroid_axis(mass_y, center_y, mean_vy, 0.16)
        else:
            center_gain = 0.24 if self.composition.habitat == "micro" else 0.16
            group_pull_x = (0.5 - mass_x) * center_gain
            group_pull_y = (center_y - mass_y) * center_gain

        for index, body in enumerate(self.bodies):
            active = index < self.composition.active_bodies
            body.presence = lerp(body.presence, 1.0 if active else 0.0, dt * 2.8)
            if body.presence < 0.005 and not active:
                continue

            # Each body listens most closely to one band. Broad forces move the
            # whole population; band affinity gives individual bodies character.
            local_band = forces.bands[body.band % len(forces.bands)] if forces.bands else 0.0
            local_hit = forces.hits[body.band % len(forces.hits)] if forces.hits else 0.0
            local_deviation = (
                forces.deviations[body.band % len(forces.deviations)]
                if forces.deviations
                else 0.0
            )
            band_position = body.band / max(1, len(forces.bands) - 1)
            pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
            pitch_drive = local_band * pitch_affinity
            event = (
                max(local_hit, forces.transient, forces.rhythm_impulse * 0.72)
                if index == impact_target
                else 0.0
            )
            spike_event = local_deviation
            previous_afterglow = body.afterglow
            previous_spike = body.spike
            memory_decay = max(
                0.96,
                2.25
                - affect.intimacy * 0.72
                - affect.tension * 0.38
                - affect.yearning * 0.24,
            )
            body.afterglow = max(body.afterglow * math.exp(-memory_decay * dt), event)
            body.spike = max(body.spike * math.exp(-8.4 * dt), spike_event)
            if spike_event > max(previous_afterglow, previous_spike) + 0.08:
                body.impact_angle = body.phase * 1.9 + self.phase * 1.3
            angle = self.phase * (0.62 + index * 0.035) + body.phase
            current_x, current_y = circulation_at(
                self.composition,
                body.x,
                body.y,
                self.phase + body.phase * 0.16,
            )
            curl_x = (
                current_x * 0.78 + math.cos(angle * 0.83) * 0.22
            ) * motion.idle_flow * body.character.idle
            curl_y = (
                current_y * 0.78 + math.sin(angle * 0.71) * 0.22
            ) * motion.idle_flow * body.character.idle

            dx = body.x - center_x
            dy = body.y - center_y
            distance = max(0.08, math.hypot(dx, dy))
            outward_x, outward_y = dx / distance, dy / distance
            voice_swirl_x = -dy * forces.voice * motion.audio_push * body.character.voice
            voice_swirl_y = dx * forces.voice * motion.audio_push * body.character.voice
            bass_push = (
                forces.bass
                * motion.audio_push
                * body.character.bass
                * (1.05 - forces.tone * 0.22)
            )
            hit_direction = math.sin(body.phase * 1.73 + self.phase * 1.4)
            pitch_direction = angle + forces.tone * math.pi * 1.6
            convection = math.sin(self.phase * 0.46 + body.phase + index * 0.9)
            tempo_drive = forces.tempo * (0.28 + forces.energy * 0.72)
            tempo_phase = self.phase * (2.2 + forces.tempo * 3.8) + body.phase
            tempo_wave = math.sin(tempo_phase)
            rhythm_drive = forces.rhythm_density * (0.32 + forces.energy * 0.68)
            rhythm_phase = self.phase * (6.0 + forces.rhythm_density * 10.0) + body.phase * 1.7
            rhythm_wave = math.sin(rhythm_phase)
            emotional_cohesion = (
                affect.cohesion * 0.018
                + affect.intimacy * 0.022
                + affect.yearning * 0.008
            )
            emotional_contraction = affect.tension * 0.014 + story.expectation * 0.008
            emotional_release = (
                affect.release * 0.045
                + affect.catharsis * 0.065
                + affect.openness * 0.010
                + affect.snap * 0.080
                + story.interruption * 0.050
                + story.resolution * 0.035
            )
            center_pull_x = -dx * (
                0.035 + forces.energy * 0.012 + emotional_cohesion + emotional_contraction
            )
            center_pull_y = -dy * (
                0.050 + forces.energy * 0.012 + emotional_cohesion + emotional_contraction
            )
            anchor_x, anchor_y = habitat_anchor(self.composition, index, self.phase)
            habitat_pull = 0.052 if self.composition.habitat != "micro" else 0.090
            home_x = (anchor_x - body.x) * habitat_pull
            home_y = (anchor_y - body.y) * habitat_pull
            thermal_flow = (
                convection
                * motion.buoyancy
                * body.character.idle
                * (0.018 + forces.bass * 0.035)
                / body.character.mass
            )
            body_scale = 1.0 / body.character.mass

            wave_x = 0.0
            wave_y = 0.0
            wave_level = 0.0
            for wave in self.pressure_waves:
                wave_dx = (body.x - wave.x) / axis_x
                wave_dy = (body.y - wave.y) / axis_y
                wave_distance = max(0.001, math.hypot(wave_dx, wave_dy))
                wave_radius = 0.055 + wave.age * wave.speed
                thickness = 0.105 + wave.age * 0.035
                envelope = math.exp(-((wave_distance - wave_radius) / thickness) ** 2)
                local_pressure = wave.strength * envelope
                wave_x += wave_dx / wave_distance * local_pressure * axis_x
                wave_y += wave_dy / wave_distance * local_pressure * axis_y
                wave_level += local_pressure
            body.acoustic_pressure = max(
                body.acoustic_pressure * math.exp(-2.6 * dt),
                clamp(wave_level),
            )
            if abs(wave_x) + abs(wave_y) > 0.0001:
                body.pressure_angle = math.atan2(wave_y / axis_y, wave_x / axis_x)

            acceleration = (
                0.018
                + drift * 0.035
                + affect.agitation * 0.008
                + affect.catharsis * 0.012
                + affect.snap * 0.014
                + story.interruption * 0.006
                + story.resolution * 0.004
                + tempo_drive * 0.010
                + rhythm_drive * 0.009
            )
            body.vx += (
                curl_x * acceleration * self.composition.horizontal_flow
                + outward_x * bass_push * 0.110 * body_scale
                + voice_swirl_x * 0.125
                + hit_direction * (event + forces.pulse * 0.12) * 0.140 * body_scale
                + math.cos(body.impact_angle) * body.spike * 0.105 * body_scale
                + math.cos(pitch_direction) * pitch_drive * 0.082 * body.character.detail
                + math.cos(angle + math.pi * 0.5)
                * tempo_wave
                * tempo_drive
                * 0.030
                * body.character.idle
                + math.cos(rhythm_phase) * rhythm_drive * 0.022 * body.character.detail
                + center_pull_x
                + home_x
                + separation_x[index]
                + (mean_vx - body.vx) * 0.042
                + group_pull_x
                + wave_x * motion.audio_push * 0.135 * body_scale
                + outward_x * emotional_release
            ) * dt
            body.vy += (
                curl_y * acceleration * self.composition.vertical_flow
                + thermal_flow
                + outward_y * bass_push * 0.065 * body_scale
                + forces.bass * body.character.bass * 0.028
                + voice_swirl_y * 0.125
                + math.cos(body.phase * 1.37 + self.phase) * event * 0.140 * body_scale
                + math.sin(body.impact_angle) * body.spike * 0.105 * body_scale
                + math.sin(pitch_direction) * pitch_drive * 0.082 * body.character.detail
                + math.sin(angle + math.pi * 0.5)
                * tempo_wave
                * tempo_drive
                * 0.030
                * body.character.idle
                + math.sin(rhythm_phase) * rhythm_drive * 0.022 * body.character.detail
                + center_pull_y
                + home_y
                + separation_y[index]
                + (mean_vy - body.vy) * 0.042
                + group_pull_y
                + wave_y * motion.audio_push * 0.135 * body_scale
                + outward_y * emotional_release
                - affect.yearning
                * max(body.character.voice, body.character.detail * 0.62)
                * 0.010
            ) * dt

            drag = 0.28 + (1.0 - viscosity) * 3.2 + (1.0 - motion.inertia) * 2.0
            damping = math.exp(-drag * dt)
            body.vx *= damping
            body.vy *= damping
            speed_limit = (
                0.035
                + drift * 0.12
                + forces.transient * 0.10
                + forces.pulse * 0.035
                + forces.rhythm_density * 0.022
                + forces.rhythm_impulse * 0.024
            )
            speed = math.hypot(body.vx, body.vy)
            if speed > speed_limit:
                body.vx *= speed_limit / speed
                body.vy *= speed_limit / speed

            body.x += body.vx * dt
            body.y += body.vy * dt

            radius_band = radius_min + (radius_max - radius_min) * body.character.size
            target_radius = radius_band * self.composition.radius_scale
            target_radius *= (
                1.0
                + forces.bass * (0.10 - forces.tone * 0.030)
                + pitch_drive * 0.050
                + tempo_wave
                * tempo_drive
                * (0.016 + body.character.deformation * 0.010)
                - affect.tension * 0.025
                + affect.release * 0.055
                + affect.catharsis * 0.075
                + affect.snap * 0.060
                + story.interruption * 0.030
                + story.resolution * 0.025
            )
            body.base_radius = lerp(body.base_radius, target_radius, dt * 1.6)
            body.radius = lerp(body.radius, body.base_radius, dt * 3.4)

            # Wall margins use physical tile geometry, so contact feels alike
            # in a wide current and a narrow chimney.
            margin_x = axis_x * (self.composition.wall_padding + body.radius * 0.62)
            margin_y = axis_y * (self.composition.wall_padding + body.radius * 0.62)
            wall_pressure_x = 0.0
            wall_pressure_y = 0.0
            if body.x < margin_x:
                wall_pressure_x = clamp((margin_x - body.x) / max(0.02, margin_x))
                body.x = margin_x
                body.vx = abs(body.vx) * (0.16 + motion.collision * 0.18)
            elif body.x > 1.0 - margin_x:
                wall_pressure_x = clamp(
                    (body.x - (1.0 - margin_x)) / max(0.02, margin_x)
                )
                body.x = 1.0 - margin_x
                body.vx = -abs(body.vx) * (0.16 + motion.collision * 0.18)
            if body.y < margin_y:
                wall_pressure_y = clamp((margin_y - body.y) / max(0.02, margin_y))
                body.y = margin_y
                body.vy = abs(body.vy) * (0.14 + motion.collision * 0.16)
            elif body.y > 1.0 - margin_y:
                wall_pressure_y = clamp(
                    (body.y - (1.0 - margin_y)) / max(0.02, margin_y)
                )
                body.y = 1.0 - margin_y
                body.vy = -abs(body.vy) * (0.14 + motion.collision * 0.16)

            body.wall_pressure_x = max(
                body.wall_pressure_x * math.exp(-4.0 * dt), wall_pressure_x
            )
            body.wall_pressure_y = max(
                body.wall_pressure_y * math.exp(-4.0 * dt), wall_pressure_y
            )
            body.wall_pressure = max(body.wall_pressure_x, body.wall_pressure_y)
            velocity_angle = math.atan2(body.vy, body.vx)
            speed_stretch = clamp(math.hypot(body.vx, body.vy) / max(0.03, speed_limit))
            travel_x = math.cos(velocity_angle) ** 2
            travel_y = math.sin(velocity_angle) ** 2
            body.stretch_x = 1.0 + travel_x * speed_stretch * 0.20 - travel_y * speed_stretch * 0.07
            body.stretch_y = 1.0 + travel_y * speed_stretch * 0.20 - travel_x * speed_stretch * 0.07
            tonal_shape = (
                forces.detail * body.character.detail * (0.035 + forces.tone * 0.105)
                + forces.flux * 0.11
                + event * 0.10
                + affect.fragility * body.character.detail * 0.025
            ) * body.character.deformation
            body.stretch_x += tonal_shape * (0.55 + 0.45 * abs(math.cos(pitch_direction)))
            body.stretch_y += tonal_shape * (0.55 + 0.45 * abs(math.sin(pitch_direction)))
            tempo_shape = tempo_wave * tempo_drive * 0.055 * body.character.deformation
            body.stretch_x += tempo_shape
            body.stretch_y -= tempo_shape * 0.58
            rhythm_shape = rhythm_wave * rhythm_drive * 0.045 * body.character.deformation
            body.stretch_x += rhythm_shape
            body.stretch_y -= rhythm_shape * 0.72
            yearning_shape = (
                affect.yearning
                * max(body.character.voice, body.character.detail * 0.70)
                * 0.040
            )
            body.stretch_x -= yearning_shape * 0.28
            body.stretch_y += yearning_shape
            body.stretch_x += abs(math.cos(body.impact_angle)) * body.spike * 0.08
            body.stretch_y += abs(math.sin(body.impact_angle)) * body.spike * 0.08
            pressure_x = math.cos(body.pressure_angle) ** 2 * body.acoustic_pressure
            pressure_y = math.sin(body.pressure_angle) ** 2 * body.acoustic_pressure
            body.stretch_x += pressure_y * 0.13 - pressure_x * 0.08
            body.stretch_y += pressure_x * 0.13 - pressure_y * 0.08
            body.stretch_x += body.wall_pressure_y * 0.24 - body.wall_pressure_x * 0.17
            body.stretch_y += body.wall_pressure_x * 0.24 - body.wall_pressure_y * 0.17
            body.stretch_x = max(0.72, body.stretch_x)
            body.stretch_y = max(0.72, body.stretch_y)

        return self.composition


@dataclass(slots=True)
class FieldFrame:
    """Semantic field channels shared by every terminal output material."""

    mass: list[list[float]]
    surface: list[list[float]]
    attention: list[list[float]]

    @classmethod
    def empty(cls, width: int, height: int) -> "FieldFrame":
        return cls(
            mass=[[0.0] * width for _ in range(height)],
            surface=[[0.0] * width for _ in range(height)],
            attention=[[0.0] * width for _ in range(height)],
        )

    def composite(
        self,
        mass_gain: float = 1.0,
        surface_gain: float = 0.17,
        attention_gain: float = 0.34,
    ) -> list[list[float]]:
        """Build the original balanced view for metrics and compatibility."""

        rows: list[list[float]] = []
        for mass_row, surface_row, attention_row in zip(
            self.mass,
            self.surface,
            self.attention,
        ):
            rows.append(
                [
                    clamp(
                        mass * mass_gain
                        + surface * surface_gain
                        + min(attention_gain, attention * attention_gain)
                    )
                    for mass, surface, attention in zip(
                        mass_row,
                        surface_row,
                        attention_row,
                    )
                ]
            )
        return rows


class OrganismFieldRenderer:
    """Rasterizes body mass and spends bright values only on local events."""

    def render(
        self,
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        phase: float,
        motion_name: str = "neutral",
        cell_aspect: float = CELL_ASPECT,
    ) -> FieldFrame:
        width = max(10, width)
        height = max(6, height)
        motion = MOTION_PROFILES.get(motion_name, MOTION_PROFILES["neutral"])
        # The buffer stores shape intensity, not terminal color. The curses
        # layer applies glyphs and palettes later, which keeps brightness from
        # becoming a second equalizer.
        mass_rows = [[0.0] * width for _ in range(height)]
        surface_rows = [[0.0] * width for _ in range(height)]
        attention_rows = [[0.0] * width for _ in range(height)]
        axis_x, axis_y = tile_axis_scales(width, height, cell_aspect)

        for y in range(height):
            ny = y / max(1, height - 1)
            for x in range(width):
                nx = x / max(1, width - 1)
                mass = 0.0
                local_detail = 0.0
                local_attention = 0.0
                for index, body in enumerate(bodies):
                    if body.presence < 0.01:
                        continue
                    radius = max(0.035, body.radius)
                    radius_x = radius * axis_x
                    radius_y = radius * axis_y
                    band_position = body.band / max(1, len(forces.bands) - 1)
                    pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
                    dx = (nx - body.x) / (radius_x * body.stretch_x)
                    dy = (ny - body.y) / (radius_y * body.stretch_y)
                    dist2 = dx * dx + dy * dy
                    influence = body.presence / ((1.0 + dist2) ** 2.65)
                    # A soft union lets touching bodies merge at their skirts
                    # without turning several bodies into one saturated slab.
                    mass = max(mass, influence) + min(mass, influence) * 0.22

                    surface = max(0.0, 1.0 - abs(math.sqrt(dist2) - 0.92) * 3.6)
                    texture = 0.5 + 0.5 * math.sin(
                        nx * (10.0 + forces.tone * 15.0)
                        + ny * (6.0 + forces.tone * 7.0)
                        + phase * (1.6 + forces.tempo * 2.8)
                        + body.phase
                    )
                    local_detail += (
                        influence
                        * surface
                        * texture
                        * forces.detail
                        * body.character.detail
                    )

                    ripple_radius = 0.82 + 0.18 * math.sin(
                        phase * (1.2 + forces.tempo * 2.2) + body.phase
                    )
                    ripple = max(0.0, 1.0 - abs(math.sqrt(dist2) - ripple_radius) * 6.0)
                    local_detail += influence * ripple * forces.pulse * (0.35 + pitch_affinity * 0.65)

                    hit = forces.hits[body.band % len(forces.hits)] if forces.hits else 0.0
                    impact_x = body.x + math.cos(body.impact_angle) * radius_x * 0.72
                    impact_y = body.y + math.sin(body.impact_angle) * radius_y * 0.72
                    impact_dx = (nx - impact_x) / max(0.012, radius_x * 0.42)
                    impact_dy = (ny - impact_y) / max(0.012, radius_y * 0.42)
                    local_attention += (
                        max(body.afterglow, hit)
                        * math.exp(-(impact_dx * impact_dx + impact_dy * impact_dy) * 1.8)
                    )

                density = clamp((mass - 0.090) / 0.68)
                if density <= 0.0:
                    continue
                mass_rows[y][x] = density ** 0.82 * 0.72
                surface_rows[y][x] = clamp(local_detail * motion.surface_motion)
                attention_rows[y][x] = clamp(local_attention)
        return FieldFrame(mass_rows, surface_rows, attention_rows)


@dataclass(slots=True, frozen=True)
class FieldMetrics:
    visible: float
    bright: float
    saturated: float
    regions: int
    p90: float


def measure_field(buffer: list[list[float]], cutoff: float = 0.055) -> FieldMetrics:
    if not buffer or not buffer[0]:
        return FieldMetrics(0.0, 0.0, 0.0, 0, 0.0)
    values = [value for row in buffer for value in row]
    total = len(values)
    ordered = sorted(values)
    # Low-density metaball skirts may touch while the readable cores stay distinct.
    regions = _connected_regions(buffer, max(cutoff, 0.30))
    return FieldMetrics(
        visible=sum(value > cutoff for value in values) / total,
        bright=sum(value > 0.78 for value in values) / total,
        saturated=sum(value >= 0.99 for value in values) / total,
        regions=regions,
        p90=ordered[min(total - 1, int(total * 0.9))],
    )


def _connected_regions(buffer: list[list[float]], cutoff: float) -> int:
    height = len(buffer)
    width = len(buffer[0])
    seen: set[tuple[int, int]] = set()
    sizes: list[int] = []
    for y in range(height):
        for x in range(width):
            if (x, y) in seen or buffer[y][x] <= cutoff:
                continue
            seen.add((x, y))
            stack = [(x, y)]
            size = 0
            while stack:
                px, py = stack.pop()
                size += 1
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if (nx, ny) in seen or buffer[ny][nx] <= cutoff:
                        continue
                    seen.add((nx, ny))
                    stack.append((nx, ny))
            sizes.append(size)
    return sum(size >= 3 for size in sizes)


def _eight_bands(values, fallback: float) -> list[float]:
    source = [clamp(float(value)) for value in (values or [])]
    if not source:
        return [clamp(fallback)] * 8
    if len(source) == 8:
        return source
    if len(source) == 1:
        return source * 8
    result = []
    for index in range(8):
        position = index * (len(source) - 1) / 7.0
        left = int(position)
        right = min(len(source) - 1, left + 1)
        result.append(lerp(source[left], source[right], position - left))
    return result
