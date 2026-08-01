"""Audio-to-force mapping, persistent body motion, and scalar-field rendering."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .audio import AudioFrame
from .config import LavaConfig


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def lerp(current: float, target: float, amount: float) -> float:
    return current + (target - current) * clamp(amount)


@dataclass(slots=True, frozen=True)
class AudioForces:
    """Physical vocabulary shared by analysis, motion, and rendering."""

    bass: float = 0.0
    voice: float = 0.0
    detail: float = 0.0
    transient: float = 0.0
    energy: float = 0.0
    tone: float = 0.5
    tempo: float = 0.0
    pulse: float = 0.0
    flux: float = 0.0
    bands: tuple[float, ...] = (0.0,) * 8
    hits: tuple[float, ...] = (0.0,) * 8


@dataclass(slots=True)
class _AdaptiveRange:
    floor: float = 0.0
    ceiling: float = 0.12

    def normalize(self, value: float) -> float:
        # The asymmetric rates preserve contrast without pumping when a source
        # changes volume or a quiet passage follows a loud one.
        value = max(0.0, value)
        if value <= self.floor:
            self.floor = value
        else:
            self.floor += (value - self.floor) * 0.002
        if value >= self.ceiling:
            self.ceiling = value
        else:
            self.ceiling += (value - self.ceiling) * 0.012
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
        self._last_onset_at = 0.0
        self._raw_bands = [0.0] * 8
        self._bands = [0.0] * 8
        self._hits = [0.0] * 8

    def reset(self) -> None:
        self.__init__()

    def map(self, frame: AudioFrame, mode: str, reactivity: float) -> AudioForces:
        bands = _eight_bands(frame.bands, frame.rms)
        band_total = sum(bands)
        tone = (
            sum(index * value for index, value in enumerate(bands))
            / max(0.0001, band_total * 7.0)
        )
        flux = sum(max(0.0, current - previous) for current, previous in zip(bands, self._raw_bands)) / 8.0
        self._raw_bands = bands[:]
        self._tone = lerp(self._tone, tone, 0.14)
        low_raw = sum(bands[:3]) / 3.0
        voice_raw = sum(bands[2:6]) / 4.0
        detail_raw = max(sum(bands[5:]) / 3.0, frame.zcr * 0.72)
        energy_raw = clamp(frame.rms)

        low = self._ranges[0].normalize(low_raw)
        voice = self._ranges[1].normalize(voice_raw)
        detail = self._ranges[2].normalize(detail_raw)
        energy = self._ranges[3].normalize(energy_raw)

        previous_bass = self._bass
        previous_energy = self._energy
        self._bass = lerp(self._bass, low, 0.24)
        self._voice = lerp(self._voice, voice, 0.20)
        self._detail = lerp(self._detail, detail, 0.16)
        self._energy = lerp(self._energy, energy, 0.18)

        attack = clamp(frame.attack)
        onset = max(0.0, self._bass - previous_bass) * 1.4
        onset += max(0.0, self._energy - previous_energy) * 1.1
        transient_target = clamp(attack * 0.92 + onset)
        self._transient = max(self._transient * 0.58, transient_target)
        pulse_target = clamp(transient_target * 0.70 + flux * 1.45)
        self._pulse = max(self._pulse * 0.66, pulse_target)

        timestamp = float(frame.timestamp)
        if pulse_target > 0.20 and timestamp > 0.0:
            interval = timestamp - self._last_onset_at if self._last_onset_at else 0.0
            if 0.14 <= interval <= 1.5:
                pulses_per_second = 1.0 / interval
                tempo_target = clamp((pulses_per_second - 0.65) / 3.1)
                self._tempo = lerp(self._tempo, tempo_target, 0.24)
            self._last_onset_at = timestamp
        else:
            self._tempo = lerp(self._tempo, clamp(flux * 2.8), 0.025)

        # Keep both a smooth spectral shape and short-lived per-band rises. The
        # organism uses the former for shape and the latter for local impacts.
        for index, current in enumerate(bands):
            previous = self._bands[index]
            rise = max(0.0, current - previous)
            self._bands[index] = max(previous * 0.72, lerp(previous, current, 0.22))
            self._hits[index] = max(self._hits[index] * 0.48, rise * 1.9 + attack * current * 0.28)

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
            tone=clamp(self._tone),
            tempo=clamp(self._tempo),
            pulse=clamp(self._pulse * hit_gain * response),
            flux=clamp(flux * response * 2.0),
            bands=tuple(clamp(value * response) for value in self._bands),
            hits=tuple(clamp(value * response) for value in self._hits),
        )


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
    afterglow: float = 0.0
    impact_angle: float = 0.0


class AcousticOrganism:
    """Persistent bodies whose motion is disturbed by semantic audio forces."""

    def __init__(self, body_limit: int = 8, seed: int = 719) -> None:
        self._random = random.Random(seed)
        self.bodies: list[Body] = []
        self.phase = 0.0
        self.composition = compose_tile(40, 18, body_limit)
        self.ensure_capacity(body_limit)

    def reset(self, body_limit: int | None = None) -> None:
        limit = body_limit if body_limit is not None else max(1, len(self.bodies))
        self.bodies = []
        self.phase = 0.0
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

    def update(
        self,
        dt: float,
        forces: AudioForces,
        width: int,
        height: int,
        lava_config: LavaConfig,
        motion_name: str = "neutral",
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
        self.phase += dt * (
            0.42
            + drift * 0.72
            + forces.voice * 0.16
            + forces.tempo * 0.34
            + forces.pulse * 0.18
        )
        center_x = 0.5 + math.sin(self.phase * 0.37) * 0.035
        center_y = 0.53 + math.cos(self.phase * 0.29) * 0.028

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
                dx = second.x - first.x
                dy = second.y - first.y
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
                separation_x[left] -= nx * pressure
                separation_y[left] -= ny * pressure
                separation_x[right] += nx * pressure
                separation_y[right] += ny * pressure

        for index, body in enumerate(self.bodies):
            active = index < self.composition.active_bodies
            body.presence = lerp(body.presence, 1.0 if active else 0.0, dt * 2.8)
            if body.presence < 0.005 and not active:
                continue

            # Each body listens most closely to one band. Broad forces move the
            # whole population; band affinity gives individual bodies character.
            local_band = forces.bands[body.band % len(forces.bands)] if forces.bands else 0.0
            local_hit = forces.hits[body.band % len(forces.hits)] if forces.hits else 0.0
            band_position = body.band / max(1, len(forces.bands) - 1)
            pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
            pitch_drive = local_band * pitch_affinity
            event = max(local_hit, forces.transient) if index == impact_target else 0.0
            previous_afterglow = body.afterglow
            body.afterglow = max(body.afterglow * math.exp(-2.25 * dt), event)
            if event > previous_afterglow + 0.08:
                body.impact_angle = body.phase * 1.9 + self.phase * 1.3
            angle = self.phase * (0.62 + index * 0.035) + body.phase
            curl_x = math.cos(angle * 0.83) * motion.idle_flow * body.character.idle
            curl_y = math.sin(angle * 0.71) * motion.idle_flow * body.character.idle

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
            center_pull_x = -dx * (0.035 + forces.energy * 0.012)
            center_pull_y = -dy * (0.050 + forces.energy * 0.012)
            anchor_x, anchor_y = habitat_anchor(self.composition, index, self.phase)
            habitat_pull = 0.130 if self.composition.habitat != "micro" else 0.180
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

            acceleration = 0.018 + drift * 0.035
            body.vx += (
                curl_x * acceleration * self.composition.horizontal_flow
                + outward_x * bass_push * 0.110 * body_scale
                + voice_swirl_x * 0.100
                + hit_direction * (event + forces.pulse * 0.12) * 0.140 * body_scale
                + math.cos(pitch_direction) * pitch_drive * 0.082 * body.character.detail
                + center_pull_x
                + home_x
                + separation_x[index]
            ) * dt
            body.vy += (
                curl_y * acceleration * self.composition.vertical_flow
                + thermal_flow
                + outward_y * bass_push * 0.065 * body_scale
                + forces.bass * body.character.bass * 0.028
                + voice_swirl_y * 0.100
                + math.cos(body.phase * 1.37 + self.phase) * event * 0.140 * body_scale
                + math.sin(pitch_direction) * pitch_drive * 0.082 * body.character.detail
                + center_pull_y
                + home_y
                + separation_y[index]
            ) * dt

            drag = 0.28 + (1.0 - viscosity) * 3.2 + (1.0 - motion.inertia) * 2.0
            damping = math.exp(-drag * dt)
            body.vx *= damping
            body.vy *= damping
            speed_limit = 0.035 + drift * 0.12 + forces.transient * 0.10 + forces.pulse * 0.035
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
            )
            body.base_radius = lerp(body.base_radius, target_radius, dt * 1.6)
            body.radius = lerp(body.radius, body.base_radius, dt * 3.4)

            # Walls rebound velocity and leave a decaying pressure value. The
            # renderer turns that pressure into a brief squash, not a flash.
            margin = self.composition.wall_padding + body.radius * 0.42
            wall_pressure = 0.0
            if body.x < margin:
                wall_pressure = max(wall_pressure, clamp((margin - body.x) / max(0.02, margin)))
                body.x = margin
                body.vx = abs(body.vx) * (0.52 + motion.collision * 0.30)
            elif body.x > 1.0 - margin:
                wall_pressure = max(wall_pressure, clamp((body.x - (1.0 - margin)) / max(0.02, margin)))
                body.x = 1.0 - margin
                body.vx = -abs(body.vx) * (0.52 + motion.collision * 0.30)
            if body.y < margin:
                wall_pressure = max(wall_pressure, clamp((margin - body.y) / max(0.02, margin)))
                body.y = margin
                body.vy = abs(body.vy) * (0.48 + motion.collision * 0.28)
            elif body.y > 1.0 - margin:
                wall_pressure = max(wall_pressure, clamp((body.y - (1.0 - margin)) / max(0.02, margin)))
                body.y = 1.0 - margin
                body.vy = -abs(body.vy) * (0.48 + motion.collision * 0.28)

            body.wall_pressure = max(body.wall_pressure * math.exp(-4.0 * dt), wall_pressure)
            velocity_angle = math.atan2(body.vy, body.vx)
            speed_stretch = clamp(math.hypot(body.vx, body.vy) / max(0.03, speed_limit))
            body.stretch_x = 1.0 + abs(math.cos(velocity_angle)) * speed_stretch * 0.20
            body.stretch_y = 1.0 + abs(math.sin(velocity_angle)) * speed_stretch * 0.20
            tonal_shape = (
                forces.detail * body.character.detail * (0.035 + forces.tone * 0.105)
                + forces.flux * 0.11
                + event * 0.10
            ) * body.character.deformation
            body.stretch_x += tonal_shape * (0.55 + 0.45 * abs(math.cos(pitch_direction)))
            body.stretch_y += tonal_shape * (0.55 + 0.45 * abs(math.sin(pitch_direction)))
            if body.wall_pressure > 0.0:
                body.stretch_x += body.wall_pressure * 0.26
                body.stretch_y = max(0.72, body.stretch_y - body.wall_pressure * 0.18)

        return self.composition


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
    ) -> tuple[list[list[float]], list[list[float]]]:
        width = max(10, width)
        height = max(6, height)
        motion = MOTION_PROFILES.get(motion_name, MOTION_PROFILES["neutral"])
        # The buffer stores shape intensity, not terminal color. The curses
        # layer applies glyphs and palettes later, which keeps brightness from
        # becoming a second equalizer.
        rows = [[0.0] * width for _ in range(height)]
        attention_rows = [[0.0] * width for _ in range(height)]

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
                    band_position = body.band / max(1, len(forces.bands) - 1)
                    pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
                    dx = (nx - body.x) / (radius * body.stretch_x)
                    dy = (ny - body.y) / (radius * body.stretch_y)
                    dist2 = dx * dx + dy * dy
                    influence = body.presence / ((1.0 + dist2) ** 2.65)
                    mass += influence

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
                    impact_x = body.x + math.cos(body.impact_angle) * radius * 0.72
                    impact_y = body.y + math.sin(body.impact_angle) * radius * 0.72
                    impact_dx = (nx - impact_x) / max(0.025, radius * 0.42)
                    impact_dy = (ny - impact_y) / max(0.025, radius * 0.42)
                    local_attention += (
                        max(body.afterglow, hit)
                        * math.exp(-(impact_dx * impact_dx + impact_dy * impact_dy) * 1.8)
                    )

                density = clamp((mass - 0.090) / 0.68)
                if density <= 0.0:
                    continue
                body_tone = density ** 0.82 * 0.72
                surface_tone = local_detail * motion.surface_motion * 0.17
                attention = min(0.34, local_attention * 0.34)
                rows[y][x] = clamp(body_tone + surface_tone + attention, 0.0, 1.0)
                attention_rows[y][x] = clamp(local_attention)
        return rows, attention_rows


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
