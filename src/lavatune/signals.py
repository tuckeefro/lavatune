"""Bounded audio-force mapping and slow listening posture."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .audio import AudioFrame

DEVIATION_WINDOW_SECONDS = 2.4
DEVIATION_WARMUP_SECONDS = 0.45


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def lerp(current: float, target: float, amount: float) -> float:
    return current + (target - current) * clamp(amount)


def time_amount(reference_amount: float, dt: float, reference_fps: float = 22.0) -> float:
    """Convert a frame-relative smoothing amount into elapsed-time smoothing."""

    return 1.0 - (1.0 - clamp(reference_amount)) ** (clamp(dt, 1.0 / 120.0, 1.0) * reference_fps)


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
    cadence: float = 0.0
    held_pressure: float = 0.0
    rupture: float = 0.0
    aftermath: float = 0.0
    overdrive: float = 0.0



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
        # Fixed scalar phrase memory. It deliberately does not retain audio
        # frames, beats, lyrics, or a growing event history.
        self._last_onset_at = 0.0
        self._interval_mean = 0.0
        self._interval_error = 0.0
        self._pressure_seconds = 0.0
        self._quiet_seconds = 0.0
        self._rupture_memory = 0.0
        self._overdrive = 0.0

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
        onset = (
            forces.rhythm_impulse >= 0.18
            and timestamp > 0.0
            and (
                not self._last_onset_at
                or timestamp - self._last_onset_at >= 0.06
            )
        )
        cadence_error = 0.0
        if onset:
            interval = timestamp - self._last_onset_at if self._last_onset_at else 0.0
            if 0.14 <= interval <= 1.50 and self._interval_mean > 0.0:
                cadence_error = clamp(
                    (abs(interval - self._interval_mean) - 0.035)
                    / (self._interval_mean * 0.42 + 0.045)
                )
                self._interval_error = lerp(
                    self._interval_error, cadence_error, time_amount(0.24, dt)
                )
                self._interval_mean = lerp(
                    self._interval_mean, interval, time_amount(0.18, dt)
                )
            elif 0.14 <= interval <= 1.50:
                self._interval_mean = interval
            self._last_onset_at = timestamp

        cadence_target = clamp(
            (1.0 - self._interval_error * 1.35)
            * clamp((forces.tempo - 0.08) / 0.30)
        )
        cadence = lerp(self.state.cadence, cadence_target, time_amount(0.08, dt))
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

        # Phrase state extends the existing fast event vocabulary with a
        # bounded memory of what preceded the event. A low sustained tone and
        # stable cadence can accumulate pressure; a cadence break can rupture
        # it; only a following sparse passage earns an aftermath.
        pressure_gate = (
            clamp((affect.tension - 0.20) / 0.45)
            * clamp((signal_level - 0.06) / 0.24)
            * (0.55 + cadence * 0.45)
            * (0.75 + (1.0 - forces.tone) * 0.25)
        )
        if pressure_gate >= 0.24 and affect.release < 0.20 and affect.snap < 0.18:
            self._pressure_seconds = min(8.0, self._pressure_seconds + dt)
        else:
            self._pressure_seconds = max(0.0, self._pressure_seconds - dt * 0.70)
        held_pressure = clamp(self._pressure_seconds / 2.6)

        break_evidence = clamp(
            cadence_error * 0.72
            + affect.snap * 0.62
            + max(forces.deviations, default=0.0) * 0.24
        )
        rupture_target = clamp(
            (held_pressure * 0.62 + expectation * 0.48) * break_evidence
        )
        rupture = max(self.state.rupture * math.exp(-dt / 0.85), rupture_target)
        self._rupture_memory = max(
            self._rupture_memory * math.exp(-dt / 3.6), rupture_target
        )
        quiet_gate = (
            signal_level < 0.13
            and forces.transient < 0.10
            and forces.rhythm_density < 0.16
        )
        self._quiet_seconds = (
            min(5.0, self._quiet_seconds + dt)
            if quiet_gate
            else max(0.0, self._quiet_seconds - dt * 1.2)
        )
        aftermath_target = self._rupture_memory * clamp(self._quiet_seconds / 0.75)
        aftermath = max(
            self.state.aftermath * math.exp(-dt / 2.8), aftermath_target
        )
        # Some music does not offer a clean cadence break. Dense, sustained
        # peaks need their own bounded escape hatch so relentless intensity
        # can become physical overdrive instead of polite held tension.
        peak_level = max(forces.energy, signal_level)
        peak_gate = clamp((peak_level - 0.62) / 0.24)
        impact_texture = clamp(
            forces.bass * 0.20
            + forces.rhythm_density * 0.30
            + forces.transient * 0.44
            + forces.pulse * 0.28
            + forces.rhythm_impulse * 0.28
        )
        overdrive_target = peak_gate * clamp((impact_texture - 0.30) / 0.55)
        self._overdrive = max(
            self._overdrive * math.exp(-dt / 0.72), overdrive_target
        )

        self.state = NarrativeState(
            expectation=expectation,
            interruption=interruption,
            resolution=resolution,
            cadence=cadence,
            held_pressure=held_pressure,
            rupture=rupture,
            aftermath=aftermath,
            overdrive=self._overdrive,
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
        # Treble can be sharp without being a physical hit. Keep a cheap
        # lower/mid-band rise separate so crisp melodic texture does not make
        # every organism flinch like a kick drum did something to it.
        low_mid_flux = sum(
            max(0.0, current - previous)
            for current, previous in zip(bands[:5], self._raw_bands[:5])
        ) / 5.0
        low_mid_deviation = max(deviations[:5], default=0.0)
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
        bass_rate = 0.55 if low > self._bass else 0.18
        voice_rate = 0.45 if voice > self._voice else 0.16
        detail_rate = 0.50 if detail > self._detail else 0.14
        energy_rate = 0.50 if energy > self._energy else 0.15

        self._bass = lerp(self._bass, low, time_amount(bass_rate, dt))
        self._voice = lerp(self._voice, voice, time_amount(voice_rate, dt))
        self._detail = lerp(self._detail, detail, time_amount(detail_rate, dt))
        self._energy = lerp(self._energy, energy, time_amount(energy_rate, dt))

        attack = clamp(frame.attack)
        bass_rise = max(0.0, self._bass - previous_bass)
        energy_rise = max(0.0, self._energy - previous_energy)
        onset = bass_rise * 1.65 + energy_rise * 0.35
        impact_support = clamp(
            low_mid_flux * 4.0
            + low_mid_deviation * 0.60
            + bass_rise * 1.80
            + energy_rise * 0.25
        )
        transient_target = clamp(attack * (0.12 + impact_support * 0.78) + onset)
        self._transient = max(self._transient * (0.58 ** (dt * 22.0)), transient_target)
        pulse_target = clamp(transient_target * 0.80 + low_mid_flux * 0.70 + flux * 0.26)
        self._pulse = max(self._pulse * (0.66 ** (dt * 22.0)), pulse_target)

        # Beat tempo and rapid subdivision density are related but distinct.
        # A short refractory gate rejects duplicate analysis frames while still
        # accepting fast 1/16-note and machine-gun patterns. Fast events do not
        # move the tempo anchor until enough time has elapsed to infer a beat.
        self._rhythm_density *= math.exp(-dt / 0.42)
        rhythm_impulse = 0.0
        onset_cue = attack >= 0.045 or flux >= 0.060
        onset_event = (
            (pulse_target > 0.20 or attack >= 0.40)
            and onset_cue
            and timestamp > 0.0
            and timestamp >= self._onset_gate_until
        )
        if onset_event:
            rhythm_impulse = clamp(pulse_target * 0.35 + attack * 0.65)
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
