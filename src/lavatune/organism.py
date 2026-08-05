"""Audio-to-force mapping, persistent body motion, and scalar-field rendering."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from .config import LavaConfig
from .signals import (
    AffectiveState,
    AffectiveTracker,
    AudioForceMapper,
    AudioForces,
    NarrativeState,
    NarrativeTracker,
    clamp,
    lerp,
    time_amount,
)

# Compatibility façade for callers that imported signal types from organism.
__all__ = [
    "AffectiveState",
    "AffectiveTracker",
    "AudioForceMapper",
    "AudioForces",
    "NarrativeState",
    "NarrativeTracker",
    "clamp",
    "lerp",
    "time_amount",
]


CELL_ASPECT = 1.85
VOLUME_BODY_LIMIT = 4


@dataclass(slots=True, frozen=True)
class SharedPosture:
    """A bounded shared climate that leaves each organism its own agency."""

    contraction: float = 0.0
    fracture: float = 0.0
    openness: float = 0.0
    stillness: float = 0.0
    synchrony: float = 0.0


def shared_posture(affect: AffectiveState, story: NarrativeState) -> SharedPosture:
    """Translate existing acoustic posture into visible group relationships."""

    return SharedPosture(
        contraction=clamp(
            affect.tension * 0.78
            + affect.restraint * 0.32
            + story.expectation * 0.18
            + story.held_pressure * 0.28
        ),
        fracture=clamp(
            affect.snap * 0.72
            + story.interruption * 0.78
            + story.rupture * 0.55
            + story.overdrive * 0.62
            + affect.volatility * 0.16
        ),
        openness=clamp(
            affect.release * 0.70
            + affect.catharsis * 0.62
            + affect.openness * 0.28
            + story.resolution * 0.22
            + story.overdrive * 0.18
        ),
        stillness=clamp(
            affect.weight * 0.62
            + affect.tension * 0.22
            + story.aftermath * 0.30
            - story.overdrive * 0.26
            - affect.agitation * 0.14
        ),
        synchrony=clamp(
            affect.cohesion * 0.66
            + affect.intimacy * 0.24
            + affect.yearning * 0.10
            + story.cadence * 0.10
            - affect.volatility * 0.42
            - story.interruption * 0.22
            - story.overdrive * 0.22
        ),
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
        # Keep a small requested cast readable instead of collapsing it to one
        # metaball. Smaller bodies preserve identity better than one oversized
        # center mass when the tile is constrained.
        count, radius_scale, size = 3, 0.98, "micro"
    elif area < 760:
        count, radius_scale, size = 3, 1.10, "small"
    elif area < 1500:
        count, radius_scale, size = 4, 1.00, "medium"
    else:
        count, radius_scale, size = 6, 0.90, "large"

    if size == "micro":
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
    "micro": (
        (0.34, 0.62),
        (0.58, 0.40),
        (0.70, 0.68),
    ),
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


def thermal_habitat_anchor(
    composition: TileComposition,
    index: int,
    phase: float,
    role: str,
) -> tuple[float, float]:
    """Compress authored lanes into one readable Volume vessel."""

    x, y = habitat_anchor(composition, index, phase)
    # Pull the established habitat inward, then retain a quiet role lane so a
    # concentrated cast does not become four interchangeable marks.
    x = 0.5 + (x - 0.5) * 0.84
    y = 0.52 + (y - 0.52) * 0.84
    if role == "ballast":
        y += 0.022
    elif role == "listener":
        y += 0.0
    elif role == "glint":
        x -= 0.012
        y -= 0.105
    elif role == "drifter":
        orbit = phase * 0.42 + index * 1.71
        x += math.cos(orbit) * 0.008
        y += math.sin(orbit) * 0.006
    return clamp(x, 0.10, 0.90), clamp(y, 0.10, 0.90)


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
    planar_gain: float = 1.0
    travel_limit: float = 1.0
    orientation_gain: float = 1.0
    planar_smoothing: float = 0.0
    vocabulary_gain: float = 0.0


@dataclass(slots=True, frozen=True)
class MotionCues:
    """Small motion vocabulary kept separate from the raw audio channels."""

    float_drive: float = 0.0
    chop_drive: float = 0.0
    chop_wave: float = 0.0
    stab_drive: float = 0.0
    surge_drive: float = 0.0


def motion_cues(
    forces: AudioForces,
    phase: float,
    body_phase: float,
    stab_gain: float = 0.0,
) -> MotionCues:
    """Derive slow and staccato movement intentions from already-mapped forces."""

    music_context = stab_gain > 0.0
    float_drive = clamp(
        forces.tempo
        * (
            0.52 + forces.energy * 0.70
            if music_context
            else 0.42 + forces.energy * 0.58
        )
    )
    chop_signal = clamp(
        forces.detail * (0.35 + forces.tone * 0.65)
        + forces.flux * 0.60
        + forces.rhythm_density * 0.35
        + forces.transient * 0.12
    )
    # Music keeps the chop vocabulary, but gives it less directional force so
    # the same detail becomes contour texture instead of nervous travel.
    chop_drive = clamp(chop_signal * (0.92 if music_context else 1.10))
    chop_phase = phase * (
        7.0 + forces.tone * 5.0 + forces.rhythm_density * 6.0
    ) + body_phase * 1.7
    stab_drive = clamp(
        (
            max(0.0, forces.transient - 0.10) * 1.55
            + forces.rhythm_impulse * 0.28
            + forces.pulse * 0.08
        )
        * max(0.0, stab_gain)
    )
    return MotionCues(
        float_drive=float_drive,
        chop_drive=chop_drive,
        chop_wave=math.sin(chop_phase),
        stab_drive=stab_drive,
        surge_drive=clamp(
            forces.bass * 0.78
            + forces.pulse * 0.16
            + forces.rhythm_impulse * 0.12
        ),
    )


MOTION_PROFILES: dict[str, MotionProfile] = {
    "neutral": MotionProfile("neutral", 0.90, 0.74, 0.58, 0.58, 0.76, 0.66),
    "heavy": MotionProfile("heavy", 0.95, 0.48, 0.44, 0.36, 0.58, 0.38),
    "buoyant": MotionProfile("buoyant", 0.88, 0.92, 0.78, 0.68, 0.72, 0.62),
    "tactile": MotionProfile("tactile", 0.84, 0.76, 0.64, 0.86, 1.00, 0.92),
    # Lavatune's default body language: the signal still changes the inner
    # state, contour, surface, and afterglow, while the cast drifts through
    # the vessel with thick, slow lava-lamp motion.
    "lavalamp": MotionProfile(
        "lavalamp",
        0.72,
        0.36,
        0.56,
        0.24,
        0.30,
        0.78,
        planar_gain=0.58,
        travel_limit=0.44,
        orientation_gain=0.72,
        planar_smoothing=3.4,
        vocabulary_gain=1.0,
    ),
}


@dataclass(slots=True, frozen=True)
class BehaviorProfile:
    """One listening context's physical interpretation of the same audio."""

    name: str
    active_bodies: int
    bass_gain: float
    voice_gain: float
    detail_gain: float
    transient_gain: float
    tempo_gain: float
    rhythm_gain: float
    flux_gain: float
    pressure_wave_gain: float
    stab_gain: float = 0.0


LISTENING_BEHAVIORS: dict[str, BehaviorProfile] = {
    "podcast": BehaviorProfile("podcast", 2, 0.35, 1.00, 0.55, 0.14, 0.08, 0.05, 0.45, 0.0),
    # Radio and music share nearly the same continuous motion envelope. Radio
    # keeps its speaker/listener cast, while music alone gets local stabs.
    "radio": BehaviorProfile("radio", 3, 0.58, 0.66, 0.52, 0.30, 0.44, 0.28, 0.48, 0.24, 0.0),
    "music": BehaviorProfile("music", 4, 0.66, 0.70, 0.60, 0.40, 0.52, 0.36, 0.58, 0.30, 0.86),
    "microphone": BehaviorProfile("microphone", 1, 0.08, 1.00, 0.34, 0.10, 0.05, 0.04, 0.24, 0.0),
}


def behavior_for_context(context: str) -> BehaviorProfile:
    return LISTENING_BEHAVIORS.get(context, LISTENING_BEHAVIORS["music"])


def apply_behavior_profile(forces: AudioForces, profile: BehaviorProfile) -> AudioForces:
    """Scale physical forces without reinterpreting or re-analyzing the audio."""

    def scaled(values: tuple[float, ...], gain: float) -> tuple[float, ...]:
        return tuple(clamp(value * gain) for value in values)

    return replace(
        forces,
        bass=clamp(forces.bass * profile.bass_gain),
        voice=clamp(forces.voice * profile.voice_gain),
        detail=clamp(forces.detail * profile.detail_gain),
        transient=clamp(forces.transient * profile.transient_gain),
        tempo=clamp(forces.tempo * profile.tempo_gain),
        pulse=clamp(forces.pulse * profile.transient_gain),
        flux=clamp(forces.flux * profile.flux_gain),
        rhythm_density=clamp(forces.rhythm_density * profile.rhythm_gain),
        rhythm_impulse=clamp(forces.rhythm_impulse * profile.transient_gain),
        bands=scaled(forces.bands, max(profile.bass_gain, profile.voice_gain, profile.detail_gain)),
        hits=scaled(forces.hits, profile.transient_gain),
        deviations=scaled(forces.deviations, profile.transient_gain),
    )


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
    volume_width: float
    volume_height: float
    volume_lobe_size: float
    volume_lobe_offset: float
    volume_core_shape: str
    volume_lobe_shape: str
    turn: float


BODY_CHARACTERS: tuple[BodyCharacter, ...] = (
    # Each actor has its own stable volume anatomy as well as its audio role.
    # The values stay within the existing Volume bounds, so identity does not
    # purchase more samples. Proportion, a persistent soft asymmetry, and
    # lobe placement distinguish roles without turning them into hard icons.
    BodyCharacter("ballast", 1, 0.70, 1.35, 0.70, 1.35, 0.35, 0.25, 0.78, 1.14, 0.78, 0.54, 0.72, "organic", "organic", 0.58),
    BodyCharacter("listener", 3, 0.50, 1.00, 0.96, 0.55, 1.40, 0.58, 1.00, 0.82, 1.18, 0.36, 0.62, "organic", "organic", 0.82),
    BodyCharacter("glint", 6, 0.18, 0.64, 1.24, 0.22, 0.58, 1.50, 1.34, 0.66, 0.72, 0.58, 1.04, "organic", "organic", 1.42),
    BodyCharacter("drifter", 4, 0.36, 0.88, 1.06, 0.62, 0.82, 0.82, 0.94, 0.96, 0.98, 0.45, 0.88, "organic", "organic", 1.00),
    BodyCharacter("echo", 2, 0.38, 0.82, 1.10, 0.72, 0.92, 0.62, 1.04, 1.02, 0.88, 0.48, 0.94, "organic", "organic", 0.76),
    BodyCharacter("spark", 7, 0.23, 0.58, 1.30, 0.18, 0.48, 1.62, 1.42, 0.58, 0.64, 0.62, 1.10, "organic", "organic", 1.62),
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
    # Depth is normalized with 0.0 at the back of the vessel and 1.0 nearest
    # the viewer. It deliberately remains separate from the planar habitat:
    # collisions and anchors stay legible in a small terminal tile while the
    # renderers can project a modest sense of foreground and background.
    z: float = 0.5
    vz: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    angular_yaw: float = 0.0
    angular_pitch: float = 0.0
    angular_roll: float = 0.0
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
    scar: float = 0.0
    scar_angle: float = 0.0
    # Thermal state is deliberately small and persistent.  It gives the
    # Volume material a lava-lamp grammar without a cellular fluid solver.
    thermal_heat: float = 0.22
    thermal_buoyancy: float = 0.0
    thermal_viscosity: float = 0.90
    adhesion: float = 0.0
    bridge_strength: float = 0.0
    bridge_angle: float = 0.0
    thermal_active: bool = False
    flow_memory_x: float = 0.0
    flow_memory_y: float = 0.0
    planar_force_x: float = 0.0
    planar_force_y: float = 0.0
    pressure_memory: float = 0.0
    speech_flow: float = 0.0
    speech_pulse: float = 0.0
    listening: float = 0.0
    # Fluid's surface is allowed a small, persistent wave memory.  This is
    # intentionally separate from position and Volume's thermal state: a
    # hit travels around an existing contour instead of moving the organism
    # or rebuilding it from raw capture pixels.
    surface_ripple: float = 0.0
    surface_ripple_angle: float = 0.0
    surface_ripple_phase: float = 0.0
    surface_ripples_active: bool = False
    # A short silhouette-only response.  This is intentionally separate from
    # velocity so an attack can deform the body without kicking the whole
    # habitat into a jump.
    shape_pulse: float = 0.0


@dataclass(slots=True)
class PressureWave:
    """A short acoustic disturbance traveling through the shared tile."""

    x: float
    y: float
    age: float
    strength: float
    speed: float


@dataclass(slots=True)
class ScarState:
    """Bounded residue of a credible phrase rupture, not an emotion label."""

    shared: float = 0.0
    origin_x: float = 0.5
    origin_y: float = 0.5
    last_rupture: float = 0.0
    recovery_seconds: float = 0.0


@dataclass(slots=True)
class SpeechState:
    """Bounded radio-speech posture; it contains no language information."""

    speaker_index: int = 1
    candidate_index: int = 1
    candidate_seconds: float = 0.0
    voice_flow: float = 0.0
    cadence_hold: float = 0.0
    pause_release: float = 0.0
    syllable: float = 0.0
    last_signal: float = 0.0


class AcousticOrganism:
    """Persistent bodies whose motion is disturbed by semantic audio forces."""

    def __init__(self, body_limit: int = 8, seed: int = 719) -> None:
        self._random = random.Random(seed)
        self.bodies: list[Body] = []
        self.pressure_waves: list[PressureWave] = []
        self.phase = 0.0
        self._last_event = 0.0
        self._wave_cooldown = 0.0
        self.scar_state = ScarState()
        self.speech_state = SpeechState()
        self.dominant_bridge: tuple[int, int] | None = None
        self.composition = compose_tile(40, 18, body_limit)
        self.ensure_capacity(body_limit)

    def reset(self, body_limit: int | None = None) -> None:
        limit = body_limit if body_limit is not None else max(1, len(self.bodies))
        self.bodies = []
        self.pressure_waves = []
        self.phase = 0.0
        self._last_event = 0.0
        self._wave_cooldown = 0.0
        self.scar_state = ScarState()
        self.speech_state = SpeechState()
        self.dominant_bridge = None
        self.ensure_capacity(limit)

    def ensure_capacity(self, count: int) -> None:
        count = max(1, min(10, count))
        while len(self.bodies) < count:
            index = len(self.bodies)
            character = BODY_CHARACTERS[index % len(BODY_CHARACTERS)]
            angle = self._random.uniform(0.0, math.tau)
            anchor_x, anchor_y = _HABITAT_ANCHORS["basin"][index % 6]
            radius = 0.10 + character.size * 0.075
            body_x = anchor_x + self._random.uniform(-0.025, 0.025)
            body_y = anchor_y + self._random.uniform(-0.025, 0.025)
            body_vx = math.cos(angle) * self._random.uniform(0.015, 0.035)
            body_vy = math.sin(angle) * self._random.uniform(0.015, 0.035)
            # Keep the established random sequence for the planar cast. Depth
            # is instead derived from its persistent authored phase.
            body_phase = self._random.uniform(0.0, math.tau)
            self.bodies.append(
                Body(
                    x=body_x,
                    y=body_y,
                    vx=body_vx,
                    vy=body_vy,
                    z=0.50 + math.sin(body_phase * 1.43 + index * 0.71) * 0.28,
                    vz=math.cos(body_phase * 0.91 + index) * 0.018,
                    yaw=body_phase,
                    pitch=body_phase * 0.63,
                    roll=body_phase * 0.41,
                    angular_yaw=0.16 * character.turn,
                    angular_pitch=0.09 * character.turn,
                    angular_roll=0.07 * character.turn,
                    radius=radius,
                    base_radius=radius,
                    phase=body_phase,
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

    def _advance_pressure_waves(
        self, dt: float, forces: AudioForces, gain: float = 1.0
    ) -> None:
        """Emit on rising events, then let pressure cross the vessel over time."""

        self._wave_cooldown = max(0.0, self._wave_cooldown - dt)
        event = max(
            forces.transient * 0.92,
            forces.pulse * 0.78,
            forces.flux * 0.46,
            forces.rhythm_impulse * 0.70,
        ) * gain
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

    def _advance_scars(
        self,
        dt: float,
        forces: AudioForces,
        affect: AffectiveState,
        story: NarrativeState,
        active_count: int,
        enabled: bool,
    ) -> None:
        """Mark credible ruptures; fade only after demonstrated new stability."""

        state = self.scar_state
        if not enabled:
            state.last_rupture = story.rupture
            return

        rupture_rise = max(0.0, story.rupture - state.last_rupture)
        credible = rupture_rise >= 0.045 and story.held_pressure >= 0.12
        if credible:
            state.shared = max(state.shared, clamp(story.rupture))
            source = min(2, max(0, active_count - 1))
            state.origin_x = self.bodies[source].x
            state.origin_y = self.bodies[source].y
            role_residue = {
                "ballast": 0.62,
                "listener": 0.92,
                "glint": 1.34,
                "drifter": 0.84,
            }
            for body in self.bodies[:active_count]:
                local_band = forces.bands[body.band % len(forces.bands)] if forces.bands else 0.0
                amount = rupture_rise * (0.42 + role_residue.get(body.character.name, 0.75) * 0.58)
                body.scar = max(body.scar, clamp(amount * (0.78 + local_band * 0.22)))
                away_x = body.x - state.origin_x
                away_y = body.y - state.origin_y
                body.scar_angle = (
                    math.atan2(away_y, away_x)
                    if math.hypot(away_x, away_y) > 0.025
                    else body.phase + math.pi * 0.5
                )

        signal_level = forces.level if forces.level >= 0.0 else forces.energy
        stable_pattern = (
            story.cadence >= 0.55
            and story.rupture <= 0.08
            and story.interruption <= 0.12
            and story.overdrive <= 0.18
            and affect.volatility <= 0.28
            and signal_level >= 0.12
            and (story.resolution >= 0.10 or affect.openness >= 0.20)
        )
        state.recovery_seconds = (
            min(4.0, state.recovery_seconds + dt)
            if stable_pattern
            else 0.0
        )
        # A few seconds of audible, low-volatility cadence proves that the
        # piece found a different footing.  Empty silence cannot make the
        # residue disappear; that would turn a scar back into an afterglow.
        if state.recovery_seconds >= 2.4:
            state.shared *= math.exp(-dt / 10.0)
            for body in self.bodies[:active_count]:
                body.scar *= math.exp(-dt / 11.0)
        state.last_rupture = story.rupture

    def _advance_speech(
        self,
        dt: float,
        forces: AudioForces,
        behavior: BehaviorProfile | None,
        active_count: int,
    ) -> SpeechState:
        """Give Radio one stable voice carrier and a visible pause grammar."""

        state = self.speech_state
        if behavior is None or behavior.name != "radio" or active_count <= 0:
            state.voice_flow *= math.exp(-3.0 * dt)
            state.cadence_hold *= math.exp(-2.2 * dt)
            state.pause_release *= math.exp(-2.0 * dt)
            state.syllable *= math.exp(-7.0 * dt)
            return state

        mid_bands = forces.bands[2:5] if len(forces.bands) >= 5 else forces.bands
        mid_energy = sum(mid_bands) / max(1, len(mid_bands))
        signal = clamp(forces.voice * 0.72 + mid_energy * 0.28)
        rise = max(0.0, signal - state.last_signal)
        drop = max(0.0, state.last_signal - signal)
        state.voice_flow = lerp(state.voice_flow, signal, dt * 6.2)
        state.syllable = max(state.syllable * math.exp(-8.5 * dt), clamp(rise * 3.2 + forces.detail * 0.16))
        state.pause_release = max(state.pause_release * math.exp(-1.9 * dt), clamp(drop * 2.2))
        if state.voice_flow >= 0.12:
            state.cadence_hold = min(1.0, state.cadence_hold + dt * 0.70)
        else:
            state.cadence_hold *= math.exp(-2.1 * dt)
        state.last_signal = signal

        candidate = min(
            range(active_count),
            key=lambda item: abs(self.bodies[item].band / 7.0 - forces.tone),
        )
        if candidate == state.speaker_index:
            state.candidate_index = candidate
            state.candidate_seconds = 0.0
        elif candidate == state.candidate_index and signal >= 0.16:
            state.candidate_seconds += dt
        else:
            state.candidate_index = candidate
            state.candidate_seconds = 0.0
        # A voice handoff needs sustained timbral evidence. It can never
        # flicker between bodies at syllable speed.
        if state.candidate_seconds >= 2.2:
            state.speaker_index = state.candidate_index
            state.candidate_seconds = 0.0
        state.speaker_index = min(active_count - 1, state.speaker_index)
        return state

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
        behavior: BehaviorProfile | None = None,
        embody_posture: bool = False,
        surface_ripples: bool = False,
    ) -> TileComposition:
        dt = clamp(dt, 1.0 / 120.0, 1.0 / 12.0)
        requested = max(1, min(10, lava_config.blobs))
        if behavior is not None:
            requested = min(requested, behavior.active_bodies)
        if embody_posture:
            # Experimental Volume keeps a fixed four-body interaction budget.
            # Fluid and Text retain the existing tile-dependent population.
            requested = min(requested, VOLUME_BODY_LIMIT)
        self.ensure_capacity(requested)
        self.composition = compose_tile(width, height, requested)
        motion = MOTION_PROFILES.get(motion_name, MOTION_PROFILES["neutral"])
        drift = clamp(lava_config.drift, 0.05, 0.8)
        viscosity = clamp(lava_config.viscosity, 0.7, 0.99)
        radius_min = clamp(lava_config.radius_min, 0.04, 0.3)
        radius_max = clamp(lava_config.radius_max, radius_min, 0.35)
        affect = affective or AffectiveState()
        story = narrative or NarrativeState()
        posture = shared_posture(affect, story) if embody_posture else SharedPosture()
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
        self._advance_pressure_waves(
            dt,
            forces,
            behavior.pressure_wave_gain if behavior is not None else 1.0,
        )
        center_x = 0.5 + math.sin(self.phase * 0.37) * 0.035
        center_y = (
            0.53
            + math.cos(self.phase * 0.29) * 0.028
            + affect.weight * 0.026
            - affect.openness * 0.014
            - affect.yearning * 0.012
        )
        if embody_posture:
            # Volume's vessel is intentionally quieter and more central than
            # the broad daily habitats, while still breathing with the phrase.
            center_x = 0.5 + math.sin(self.phase * 0.37) * 0.014
            center_y = 0.52 + math.cos(self.phase * 0.29) * 0.012
        axis_x, axis_y = tile_axis_scales(width, height, cell_aspect)

        # Resolve overlap as acceleration rather than teleporting bodies. This
        # keeps identity and momentum intact through resize recomposition.
        separation_x = [0.0] * len(self.bodies)
        separation_y = [0.0] * len(self.bodies)
        adhesion_x = [0.0] * len(self.bodies)
        adhesion_y = [0.0] * len(self.bodies)
        bridge_strength = [0.0] * len(self.bodies)
        bridge_angle = [0.0] * len(self.bodies)
        previous_bridge = self.dominant_bridge if embody_posture else None
        dominant_bridge: tuple[int, int, float, float, float, float] | None = None
        active_count = self.composition.active_bodies
        speech = self._advance_speech(dt, forces, behavior, active_count)
        radio_speech = behavior is not None and behavior.name == "radio"
        speaker_x = self.bodies[speech.speaker_index].x if radio_speech else 0.5
        speaker_y = self.bodies[speech.speaker_index].y if radio_speech else 0.5
        impact_target = min(
            range(active_count),
            key=lambda item: abs(self.bodies[item].band / 7.0 - forces.tone),
        )
        self._advance_scars(
            dt, forces, affect, story, active_count, embody_posture
        )
        for left in range(active_count):
            for right in range(left + 1, active_count):
                first = self.bodies[left]
                second = self.bodies[right]
                dx = (second.x - first.x) / axis_x
                dy = (second.y - first.y) / axis_y
                distance = math.hypot(dx, dy)
                preferred = (first.radius + second.radius) * 1.04
                if distance < 0.0001:
                    angle = first.phase - second.phase
                    nx, ny = math.cos(angle), math.sin(angle)
                else:
                    nx, ny = dx / distance, dy / distance
                if distance < preferred:
                    # Retain readable core spacing for every pair. The chosen
                    # bridge is expressed through its existing lobe and a
                    # bounded attraction below, rather than allowing a warm
                    # cluster to collapse into an indistinct pile.
                    pressure = (preferred - distance) * 1.15
                    separation_x[left] -= nx * pressure * axis_x
                    separation_y[left] -= ny * pressure * axis_y
                    separation_x[right] += nx * pressure * axis_x
                    separation_y[right] += ny * pressure * axis_y

                if embody_posture and distance < preferred * 1.72:
                    # At most six pair interactions for the four visible
                    # bodies. This is a bounded proximity cue, not a field
                    # pass: warm nearby bodies draw together and lend their
                    # existing lobe toward each other as a soft bridge.
                    proximity = clamp(
                        (preferred * 1.72 - distance) / max(0.001, preferred * 0.58)
                    )
                    warmth = clamp((first.thermal_heat + second.thermal_heat) * 0.5)
                    # Cool wax separates instead of retaining a weak bridge
                    # forever just because its centers remain close.
                    bridge_heat = clamp((warmth - 0.22) / 0.78)
                    adhesion = proximity * bridge_heat * (
                        0.48 + posture.synchrony * 0.52
                    )
                    selection_strength = adhesion + (
                        0.035 if previous_bridge == (left, right) else 0.0
                    )
                    if adhesion >= 0.06 and (
                        dominant_bridge is None
                        or selection_strength > dominant_bridge[5]
                    ):
                        dominant_bridge = (
                            left,
                            right,
                            adhesion,
                            nx,
                            ny,
                            selection_strength,
                        )

        # A single pair may bridge in one frame. This prevents a compact cast
        # from turning into a permanent unreadable knot while keeping pairwise
        # work fixed at at most six comparisons.
        self.dominant_bridge = None
        if dominant_bridge is not None:
            left, right, adhesion, nx, ny, _ = dominant_bridge
            pull = adhesion * 0.055
            adhesion_x[left] = nx * pull * axis_x
            adhesion_y[left] = ny * pull * axis_y
            adhesion_x[right] = -nx * pull * axis_x
            adhesion_y[right] = -ny * pull * axis_y
            bridge_strength[left] = bridge_strength[right] = adhesion
            bridge_angle[left] = math.atan2(ny, nx)
            bridge_angle[right] = math.atan2(-ny, -nx)
            self.dominant_bridge = (left, right)

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
        thermal_centroid_x = (0.5 - mass_x) * 0.045 if embody_posture else 0.0
        thermal_centroid_y = (center_y - mass_y) * 0.045 if embody_posture else 0.0

        for index, body in enumerate(self.bodies):
            active = index < self.composition.active_bodies
            body.presence = lerp(body.presence, 1.0 if active else 0.0, dt * 2.8)
            if body.presence < 0.005 and not active:
                continue

            speaking = radio_speech and index == speech.speaker_index and active
            body.speech_flow = lerp(
                body.speech_flow, speech.voice_flow if speaking else 0.0, dt * 5.2
            )
            body.speech_pulse = lerp(
                body.speech_pulse, speech.syllable if speaking else 0.0, dt * 8.0
            )
            if radio_speech and active and not speaking:
                body.listening = lerp(body.listening, speech.voice_flow, dt * 3.6)
            else:
                body.listening *= math.exp(-3.6 * dt)

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
            speech_pull_x = 0.0
            speech_pull_y = 0.0
            speech_yaw = 0.0
            speech_depth = 0.0
            if speaking:
                # A speaking body breathes forward and carries syllable-scale
                # pressure without becoming a literal mouth animation.
                speech_depth = speech.voice_flow * 0.060
                speech_pull_x = (center_x - body.x) * speech.voice_flow * 0.045
                speech_pull_y = (center_y - body.y) * speech.voice_flow * 0.028
                speech_yaw = math.sin(body.phase + self.phase * 1.7) * speech.cadence_hold * 0.24
            elif radio_speech and active:
                heading = math.atan2(speaker_y - body.y, speaker_x - body.x)
                speech_yaw = math.sin(heading - body.yaw) * body.listening * 0.48
                speech_pull_x = (speaker_x - body.x) * body.listening * 0.018
                speech_pull_y = (speaker_y - body.y) * body.listening * 0.018
            if embody_posture:
                body.thermal_active = True
                # Heat is phrase-led: a passage has to hold pressure before a
                # body truly rises. Raw attacks only ripple the surface.
                heat_target = clamp(
                    0.08
                    + forces.bass * 0.46
                    + forces.energy * 0.16
                    + local_band * 0.12
                    + story.held_pressure * 0.24
                    + story.cadence * 0.08
                    - story.aftermath * 0.08
                    - affect.release * 0.04
                )
                heat_rate = 0.68 if heat_target > body.thermal_heat else 0.34
                body.thermal_heat = lerp(body.thermal_heat, heat_target, dt * heat_rate)
                body.thermal_viscosity = lerp(
                    body.thermal_viscosity,
                    0.62 + (1.0 - body.thermal_heat) * 0.34,
                    dt * 0.90,
                )
                lift_target = -(
                    body.thermal_heat - 0.34
                ) * 0.28 / body.character.mass
                body.thermal_buoyancy = lerp(
                    body.thermal_buoyancy, lift_target, dt * 0.92
                )
                body.adhesion = lerp(body.adhesion, bridge_strength[index], dt * 2.4)
                if bridge_strength[index] >= body.bridge_strength:
                    body.bridge_angle = bridge_angle[index]
                body.bridge_strength = lerp(
                    body.bridge_strength, bridge_strength[index], dt * 3.0
                )
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
            if surface_ripples:
                # Fluid is waxy by default: deviations become the input to a
                # travelling surface wave, not a fresh mountain-shaped tooth
                # on every capture frame.
                body.spike = max(body.spike * math.exp(-10.5 * dt), spike_event * 0.10)
            else:
                body.spike = max(body.spike * math.exp(-8.4 * dt), spike_event)
            if spike_event > max(previous_afterglow, previous_spike) + 0.08:
                body.impact_angle = body.phase * 1.9 + self.phase * 1.3
            body.surface_ripples_active = surface_ripples
            if surface_ripples:
                # Keep the impulse local and let it coast around the contour.
                # Raw detail still colors the body, but no longer has to make
                # the edge teleport cell by cell to feel present.
                ripple_impulse = event * 0.78 + spike_event * 0.34
                previous_ripple = body.surface_ripple
                body.surface_ripple = max(
                    body.surface_ripple * math.exp(-3.0 * dt), ripple_impulse
                )
                if ripple_impulse > previous_ripple + 0.06:
                    body.surface_ripple_angle = body.impact_angle
                    body.surface_ripple_phase = 0.0
                else:
                    body.surface_ripple_phase += dt * (
                        2.1 + forces.tempo * 3.0 + forces.rhythm_density * 1.4
                    )
            else:
                body.surface_ripple *= math.exp(-4.0 * dt)
                body.surface_ripples_active = False
            fluid_motion_gain = 0.24 if surface_ripples else 1.0
            motion_event = event * fluid_motion_gain
            motion_spike = body.spike * fluid_motion_gain
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
            group_dx = mass_x - body.x
            group_dy = mass_y - body.y
            personal_axis = body.phase + index * 1.618
            role_pull_x = group_dx * posture.contraction * 0.075
            role_pull_y = group_dy * posture.contraction * 0.075
            role_open_x = -group_dx * posture.openness * 0.090
            role_open_y = -group_dy * posture.openness * 0.090
            role_depth = 0.0
            role_yaw = 0.0
            role_pitch = 0.0
            role_roll = 0.0
            if body.character.name == "ballast":
                # Weight is carried deep in the vessel instead of translated
                # into a generic group pulse.
                role_depth = -posture.stillness * 0.055 - posture.contraction * 0.030
                role_open_x *= 0.35
                role_open_y *= 0.35
                role_yaw = math.sin(personal_axis) * posture.fracture * 0.42
                role_pitch = posture.fracture * 0.34
            elif body.character.name == "listener":
                # The listener resolves toward the group without becoming a
                # literal waypoint: its rotation, rather than its position,
                # carries the attention.
                heading = math.atan2(group_dy, group_dx)
                heading_error = math.sin(heading - body.yaw)
                role_yaw = heading_error * posture.synchrony * 0.72
                role_roll = math.cos(personal_axis) * posture.fracture * 0.56
                role_open_x *= 0.62
                role_open_y *= 0.62
            elif body.character.name == "glint":
                # Interruptions reach the glint first and make it break from
                # the shared cadence before the larger organisms follow.
                role_yaw = math.sin(personal_axis) * posture.fracture * 1.34
                role_pitch = math.cos(personal_axis) * posture.fracture * 0.96
                role_roll = math.sin(personal_axis * 1.7) * posture.fracture * 1.42
                role_open_x *= 1.16
                role_open_y *= 1.16
            elif body.character.name == "drifter":
                # Release lets the drifter choose distance sooner than the
                # rest of the group, preserving an independent mind.
                role_open_x *= 1.72
                role_open_y *= 1.72
                role_yaw = math.sin(personal_axis) * posture.fracture * 0.88
                role_roll = math.cos(personal_axis) * posture.fracture * 0.94
            if embody_posture and body.scar > 0.0:
                # A scar changes formation continuously. It is not afterglow:
                # without new stable music, the altered relationship remains.
                scar_push = body.scar * (0.018 + self.scar_state.shared * 0.018)
                role_open_x += math.cos(body.scar_angle) * scar_push
                role_open_y += math.sin(body.scar_angle) * scar_push
                if body.character.name == "ballast":
                    role_depth -= body.scar * 0.050
                    role_pitch += body.scar * 0.24
                elif body.character.name == "listener":
                    heading = math.atan2(
                        self.scar_state.origin_y - body.y,
                        self.scar_state.origin_x - body.x,
                    )
                    role_yaw += math.sin(heading - body.yaw) * body.scar * 0.92
                elif body.character.name == "glint":
                    role_yaw += math.sin(body.scar_angle) * body.scar * 1.08
                    role_roll += math.cos(body.scar_angle) * body.scar * 1.20
                elif body.character.name == "drifter":
                    role_open_x += math.cos(body.scar_angle) * body.scar * 0.030
                    role_open_y += math.sin(body.scar_angle) * body.scar * 0.030
            role_depth += speech_depth
            role_yaw += speech_yaw
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
            cues = (
                motion_cues(
                    forces,
                    self.phase,
                    body.phase,
                    behavior.stab_gain if behavior is not None else 0.0,
                )
                if motion.vocabulary_gain > 0.0
                else MotionCues()
            )
            stab_event = cues.stab_drive if index == impact_target else 0.0
            float_lift = 1.0 + cues.float_drive * (
                0.44 + body.character.idle * 0.22
            )
            curl_x *= float_lift
            curl_y *= float_lift
            if embody_posture:
                emotional_cohesion = posture.synchrony * 0.030
                emotional_contraction = posture.contraction * 0.018
                emotional_release = posture.openness * 0.070 + posture.fracture * 0.040
            else:
                # Preserve the established behavior for Fluid and Text. The
                # new shared-posture layer is intentionally Volume-only.
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
            if embody_posture:
                anchor_x, anchor_y = thermal_habitat_anchor(
                    self.composition, index, self.phase, body.character.name
                )
            else:
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
            thermal_flow *= 1.0 + cues.float_drive * 0.58
            thermal_lift = body.thermal_buoyancy if embody_posture else 0.0
            body_scale = 1.0 / body.character.mass
            chop_angle = body.impact_angle + body.phase * 0.63 + self.phase * 0.41
            chop_force = (
                cues.chop_wave
                * cues.chop_drive
                * (0.009 + forces.tempo * 0.004)
                * body_scale
            )
            if behavior is not None and behavior.name == "music":
                chop_force *= 0.56
            stab_angle = body.impact_angle + body.phase * 0.37 + self.phase * 0.19
            stab_force = stab_event * (0.024 + forces.tone * 0.010) * body_scale
            shape_target = clamp(
                local_deviation * (0.84 if surface_ripples else 1.0)
                + event * 0.68
                + stab_event * 0.24
            )
            if shape_target > body.shape_pulse:
                # Fast attack, soft release: the contour notices the event
                # immediately, then returns through the material instead of
                # snapping back on the next audio frame.
                body.shape_pulse = lerp(
                    body.shape_pulse,
                    shape_target,
                    1.0 - math.exp(-18.0 * dt),
                )
            else:
                body.shape_pulse = max(
                    body.shape_pulse * math.exp(-4.2 * dt), shape_target
                )

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
                + cues.float_drive * 0.012
                + cues.surge_drive * 0.004
            )
            planar_force_x = (
                curl_x * acceleration * self.composition.horizontal_flow
                + outward_x * bass_push * 0.110 * body_scale
                + voice_swirl_x * 0.125
                + hit_direction
                * (motion_event + forces.pulse * 0.12 * fluid_motion_gain)
                * 0.140
                * body_scale
                + math.cos(body.impact_angle) * motion_spike * 0.105 * body_scale
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
                + adhesion_x[index]
                + (mean_vx - body.vx) * 0.042
                + group_pull_x
                + thermal_centroid_x
                + wave_x * motion.audio_push * 0.135 * body_scale
                + outward_x * emotional_release
                + role_pull_x
                + role_open_x
                + speech_pull_x
                + math.cos(chop_angle) * chop_force
                + math.cos(stab_angle) * stab_force
            ) * motion.planar_gain
            planar_force_y = (
                curl_y * acceleration * self.composition.vertical_flow
                + thermal_flow
                + thermal_lift
                + outward_y * bass_push * 0.065 * body_scale
                + forces.bass * body.character.bass * 0.028
                + voice_swirl_y * 0.125
                + math.cos(body.phase * 1.37 + self.phase)
                * motion_event
                * 0.140
                * body_scale
                + math.sin(body.impact_angle) * motion_spike * 0.105 * body_scale
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
                + adhesion_y[index]
                + (mean_vy - body.vy) * 0.042
                + group_pull_y
                + thermal_centroid_y
                + wave_y * motion.audio_push * 0.135 * body_scale
                + outward_y * emotional_release
                + role_pull_y
                + role_open_y
                + speech_pull_y
                - affect.yearning
                * max(body.character.voice, body.character.detail * 0.62)
                * 0.010
                + math.sin(chop_angle) * chop_force
                + math.sin(stab_angle) * stab_force
            ) * motion.planar_gain
            if motion.planar_smoothing > 0.0:
                smoothing = 1.0 - math.exp(-motion.planar_smoothing * dt)
                body.planar_force_x = lerp(
                    body.planar_force_x, planar_force_x, smoothing
                )
                body.planar_force_y = lerp(
                    body.planar_force_y, planar_force_y, smoothing
                )
            else:
                body.planar_force_x = planar_force_x
                body.planar_force_y = planar_force_y
            body.vx += body.planar_force_x * dt
            body.vy += body.planar_force_y * dt

            thermal_drag = (
                max(0.0, body.thermal_viscosity - 0.62) * 1.15
                if embody_posture
                else 0.0
            )
            drag = (
                0.28
                + (1.0 - viscosity) * 3.2
                + (1.0 - motion.inertia) * 2.0
                + thermal_drag
            )
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
                + cues.float_drive * 0.065
                + cues.surge_drive * 0.012
            ) * motion.travel_limit
            speed = math.hypot(body.vx, body.vy)
            if speed > speed_limit:
                body.vx *= speed_limit / speed
                body.vy *= speed_limit / speed

            body.x += body.vx * dt
            body.y += body.vy * dt

            # A shallow third axis gives the terminal projection parallax
            # without making the established 2D habitat unstable.  Voice and
            # tempo sustain an orbit; bass and confirmed gestures give it a
            # brief outward push.  Individual phase keeps the cast from
            # moving through depth as one rigid sheet.
            depth_phase = self.phase * (0.38 + forces.tempo * 0.38) + body.phase * 1.61
            depth_target = 0.50 + role_depth + math.sin(depth_phase) * (
                0.16 + forces.voice * 0.06 + forces.energy * 0.035
            )
            depth_push = (
                forces.bass * body.character.bass * 0.052
                + motion_event * 0.070
                + motion_spike * 0.038
                + affect.release * 0.028
                + affect.catharsis * 0.040
            ) * math.sin(body.phase * 1.17 + self.phase * 0.72)
            body.vz += (
                (depth_target - body.z) * 0.72 + depth_push
            ) * motion.travel_limit * dt
            body.vz *= math.exp(-(1.35 + (1.0 - viscosity) * 1.8) * dt)
            body.vz = clamp(body.vz, -0.14, 0.14)
            body.z += body.vz * dt
            if body.z < 0.08:
                body.z = 0.08
                body.vz = abs(body.vz) * 0.32
            elif body.z > 0.92:
                body.z = 0.92
                body.vz = -abs(body.vz) * 0.32

            # Orientation is persistent state, not a screen-space texture.
            # Each actor carries separate angular momentum: a hit tumbles the
            # actor that heard it, then it visibly coasts rather than all cast
            # members mechanically advancing at the same rate.
            turn_gain = behavior.tempo_gain if behavior is not None else 1.0
            flip_gain = behavior.transient_gain if behavior is not None else 1.0
            impact = max(0.0, motion_event - previous_afterglow * fluid_motion_gain)
            turn = body.character.turn
            body.angular_yaw += (
                dt
                * (
                    0.18 * turn
                    + forces.tempo * 1.85 * turn_gain * turn
                    + forces.bass * body.character.bass * 0.52
                    + forces.voice * body.character.voice * 0.30
                    + role_yaw
                )
                + impact * 2.35 * flip_gain * turn
            ) * motion.orientation_gain
            body.angular_pitch += (
                dt
                * (
                    0.10 * turn
                    + forces.bass * body.character.bass * 0.88 * turn_gain
                    + motion_spike * 0.72 * flip_gain
                    + role_pitch
                )
                + impact * 1.25 * flip_gain
            ) * motion.orientation_gain
            body.angular_roll += (
                dt
                * (
                    0.07 * turn
                    + forces.tempo * 0.38 * turn_gain
                    + forces.detail * body.character.detail * 0.84 * turn_gain
                    + role_roll
                )
                + impact * 1.55 * flip_gain * turn
            ) * motion.orientation_gain
            angular_damping = math.exp(
                -(1.45 + (1.0 - forces.energy) * 0.50 + posture.stillness * 0.35) * dt
            )
            body.angular_yaw = max(-4.2, min(4.2, body.angular_yaw * angular_damping))
            body.angular_pitch = max(-3.6, min(3.6, body.angular_pitch * angular_damping))
            body.angular_roll = max(-3.8, min(3.8, body.angular_roll * angular_damping))
            body.yaw += body.angular_yaw * dt
            body.pitch += body.angular_pitch * dt
            body.roll += body.angular_roll * dt

            radius_band = radius_min + (radius_max - radius_min) * body.character.size
            target_radius = radius_band * self.composition.radius_scale
            target_radius *= (
                1.0
                + forces.bass * (0.25 - forces.tone * 0.070)
                + pitch_drive * 0.095
                + tempo_wave
                * tempo_drive
                * (0.045 + body.character.deformation * 0.025)
                + motion_event * 0.115
                + motion_spike * 0.070
                - affect.tension * 0.025
                + affect.release * 0.055
                + affect.catharsis * 0.075
                + affect.snap * 0.060
                + story.interruption * 0.030
                + story.resolution * 0.025
                + body.shape_pulse * (0.16 + body.character.deformation * 0.08)
                + motion.idle_flow
                * (0.010 + cues.float_drive * 0.026)
                * (1.0 - forces.transient * 0.42)
                * math.sin(self.phase * 0.54 + body.phase * 0.67)
            )
            if embody_posture:
                # Heat makes wax yield gradually. Keep attacks as brief
                # pressure events rather than letting them inflate the whole
                # body like a beat-driven balloon.
                target_radius *= (
                    1.0
                    + (body.thermal_heat - 0.32) * 0.10
                    - event * 0.070
                    - body.spike * 0.040
                    + body.bridge_strength * 0.045
                )
            elif speaking:
                target_radius *= 1.0 + body.speech_flow * 0.055 + body.speech_pulse * 0.022
            radius_attack = 1.6 + body.shape_pulse * 2.6
            body.base_radius = lerp(body.base_radius, target_radius, dt * radius_attack)
            body.radius = lerp(body.radius, body.base_radius, dt * (3.4 + body.shape_pulse * 1.2))

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
                body.planar_force_x = max(0.0, body.planar_force_x)
            elif body.x > 1.0 - margin_x:
                wall_pressure_x = clamp(
                    (body.x - (1.0 - margin_x)) / max(0.02, margin_x)
                )
                body.x = 1.0 - margin_x
                body.vx = -abs(body.vx) * (0.16 + motion.collision * 0.18)
                body.planar_force_x = min(0.0, body.planar_force_x)
            if body.y < margin_y:
                wall_pressure_y = clamp((margin_y - body.y) / max(0.02, margin_y))
                body.y = margin_y
                body.vy = abs(body.vy) * (0.14 + motion.collision * 0.16)
                body.planar_force_y = max(0.0, body.planar_force_y)
            elif body.y > 1.0 - margin_y:
                wall_pressure_y = clamp(
                    (body.y - (1.0 - margin_y)) / max(0.02, margin_y)
                )
                body.y = 1.0 - margin_y
                body.vy = -abs(body.vy) * (0.14 + motion.collision * 0.16)
                body.planar_force_y = min(0.0, body.planar_force_y)

            body.wall_pressure_x = max(
                body.wall_pressure_x * math.exp(-4.0 * dt), wall_pressure_x
            )
            body.wall_pressure_y = max(
                body.wall_pressure_y * math.exp(-4.0 * dt), wall_pressure_y
            )
            body.wall_pressure = max(body.wall_pressure_x, body.wall_pressure_y)
            if embody_posture:
                # Shape follows a low-pass motion and pressure history. This
                # gives the wax a delayed bulge and long recovery instead of
                # changing silhouette on every raw capture frame.
                body.flow_memory_x = lerp(body.flow_memory_x, body.vx, dt * 1.15)
                body.flow_memory_y = lerp(body.flow_memory_y, body.vy, dt * 1.15)
                held_thermal_pressure = clamp(
                    story.held_pressure
                    * (
                        0.10
                        + local_band * 0.12
                        + body.character.bass * 0.025
                    )
                    + body.adhesion * 0.06
                )
                body.pressure_memory = lerp(
                    body.pressure_memory,
                    max(body.acoustic_pressure, held_thermal_pressure),
                    dt * 0.72,
                )
                shape_vx = body.flow_memory_x
                shape_vy = body.flow_memory_y
                shape_pressure = body.pressure_memory
                shape_event = body.shape_pulse
                shape_spike = body.spike * 0.38
            else:
                shape_vx = body.vx
                shape_vy = body.vy
                shape_pressure = body.acoustic_pressure
                shape_event = body.shape_pulse
                shape_spike = motion_spike
            velocity_angle = math.atan2(shape_vy, shape_vx)
            speed_stretch = clamp(
                math.hypot(shape_vx, shape_vy) / max(0.03, speed_limit)
            )
            travel_x = math.cos(velocity_angle) ** 2
            travel_y = math.sin(velocity_angle) ** 2
            body.stretch_x = 1.0 + travel_x * speed_stretch * 0.20 - travel_y * speed_stretch * 0.07
            body.stretch_y = 1.0 + travel_y * speed_stretch * 0.20 - travel_x * speed_stretch * 0.07
            tonal_shape = (
                forces.detail * body.character.detail * (0.035 + forces.tone * 0.105)
                + forces.flux * 0.11
                + shape_event * 0.10
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
            quiet_flow = (
                motion.idle_flow
                * body.character.deformation
                * (0.014 + cues.float_drive * 0.030)
                * (1.0 - forces.transient * 0.42)
            )
            flow_phase = self.phase * (0.46 + forces.tempo * 0.24) + body.phase * 0.73
            flow_wave = math.sin(flow_phase)
            # Quiet material breathes around its neutral shape. The audio can
            # still change the contour while the center remains in slow flow.
            body.stretch_x += quiet_flow * flow_wave
            body.stretch_y += quiet_flow * flow_wave * 0.72
            pulse_axis_x = 0.58 + 0.42 * abs(math.cos(body.impact_angle))
            pulse_axis_y = 0.58 + 0.42 * abs(math.sin(body.impact_angle))
            body.stretch_x += shape_event * 0.25 * pulse_axis_x
            body.stretch_y += shape_event * 0.25 * pulse_axis_y
            chop_shape = (
                cues.chop_wave
                * cues.chop_drive
                * (0.086 if behavior is not None and behavior.name == "music" else 0.065)
                * body.character.deformation
            )
            body.stretch_x += chop_shape * (0.55 + 0.45 * abs(math.cos(chop_angle)))
            body.stretch_y -= chop_shape * (0.35 + 0.35 * abs(math.sin(chop_angle)))
            yearning_shape = (
                affect.yearning
                * max(body.character.voice, body.character.detail * 0.70)
                * 0.040
            )
            body.stretch_x -= yearning_shape * 0.28
            body.stretch_y += yearning_shape
            body.stretch_x += abs(math.cos(body.impact_angle)) * shape_spike * 0.08
            body.stretch_y += abs(math.sin(body.impact_angle)) * shape_spike * 0.08
            pressure_x = math.cos(body.pressure_angle) ** 2 * shape_pressure
            pressure_y = math.sin(body.pressure_angle) ** 2 * shape_pressure
            body.stretch_x += pressure_y * 0.13 - pressure_x * 0.08
            body.stretch_y += pressure_x * 0.13 - pressure_y * 0.08
            body.stretch_x += body.wall_pressure_y * 0.24 - body.wall_pressure_x * 0.17
            body.stretch_y += body.wall_pressure_x * 0.24 - body.wall_pressure_y * 0.17
            if embody_posture:
                # A bridge broadens at its contact point while buoyant wax
                # grows a little taller. The existing hit deformation is
                # softened, never replaced with a new surface.
                body.stretch_x += body.bridge_strength * 0.12 - body.spike * 0.040
                body.stretch_y += body.thermal_heat * 0.055 - body.spike * 0.040
            elif speaking:
                # Voice is a small expanding/settling breath; detail is a
                # local consonant flick, not a body-wide hit response.
                body.stretch_x += body.speech_flow * 0.065 + body.speech_pulse * 0.026
                body.stretch_y += body.speech_flow * 0.040 - body.speech_pulse * 0.012
                body.afterglow = max(body.afterglow, body.speech_pulse * 0.24)
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
        camera_x = math.sin(phase * 0.19) * 0.018
        camera_y = math.cos(phase * 0.15) * 0.012
        blend_gains = [0.10] * len(bodies)
        visible = [
            (index, body)
            for index, body in enumerate(bodies)
            if body.presence >= 0.01
        ]
        for left_index, left in visible:
            for right_index, right in visible:
                if left_index >= right_index:
                    continue
                distance = math.hypot(
                    (left.x - right.x) / max(0.001, axis_x),
                    (left.y - right.y) / max(0.001, axis_y),
                )
                reach = max(0.08, (left.radius + right.radius) * 1.85)
                proximity = clamp(1.0 - distance / reach)
                if proximity <= 0.0:
                    continue
                blend = 0.10 + proximity * 0.20
                blend_gains[left_index] = max(blend_gains[left_index], blend)
                blend_gains[right_index] = max(blend_gains[right_index], blend)

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
                    depth_scale = 0.78 + clamp(body.z) * 0.36
                    depth_luminance = 0.70 + clamp(body.z) * 0.30
                    parallax = 0.5 - clamp(body.z)
                    projected_x = clamp(body.x + camera_x * parallax)
                    projected_y = clamp(body.y + camera_y * parallax)
                    radius_x = radius * axis_x * depth_scale
                    radius_y = radius * axis_y * depth_scale
                    band_position = body.band / max(1, len(forces.bands) - 1)
                    pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
                    dx = (nx - projected_x) / (radius_x * body.stretch_x)
                    dy = (ny - projected_y) / (radius_y * body.stretch_y)
                    dist2 = dx * dx + dy * dy
                    influence = (
                        body.presence * depth_luminance / ((1.0 + dist2) ** 2.65)
                    )
                    # A soft union lets touching bodies share skirts while the
                    # lower blend keeps their readable cores separate.
                    mass = max(mass, influence) + min(mass, influence) * blend_gains[index]

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
                    impact_x = projected_x + math.cos(body.impact_angle) * radius_x * 0.72
                    impact_y = projected_y + math.sin(body.impact_angle) * radius_y * 0.72
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
