"""Fixed-cost thermal wax simulation for the experimental terminal material."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .organism import AudioForces, NarrativeState, clamp, lerp


WAX_WIDTH = 64
WAX_HEIGHT = 32
WAX_SIZE = WAX_WIDTH * WAX_HEIGHT


def _sample(values: list[float], x: float, y: float) -> float:
    """Bilinearly sample a fixed lattice with solid vessel walls."""

    x = clamp(x, 0.0, WAX_WIDTH - 1.0)
    y = clamp(y, 0.0, WAX_HEIGHT - 1.0)
    left = int(x)
    top = int(y)
    right = min(WAX_WIDTH - 1, left + 1)
    bottom = min(WAX_HEIGHT - 1, top + 1)
    tx = x - left
    ty = y - top
    upper = values[top * WAX_WIDTH + left] * (1.0 - tx) + values[
        top * WAX_WIDTH + right
    ] * tx
    lower = values[bottom * WAX_WIDTH + left] * (1.0 - tx) + values[
        bottom * WAX_WIDTH + right
    ] * tx
    return upper * (1.0 - ty) + lower * ty


@dataclass(slots=True)
class WaxState:
    """A bounded, low-resolution wax vessel with no terminal-sized buffers."""

    density: list[float] = field(default_factory=lambda: [0.0] * WAX_SIZE)
    heat: list[float] = field(default_factory=lambda: [0.0] * WAX_SIZE)
    flow_x: list[float] = field(default_factory=lambda: [0.0] * WAX_SIZE)
    flow_y: list[float] = field(default_factory=lambda: [0.0] * WAX_SIZE)
    target_mass: float = 0.0
    phase: float = 0.0
    last_hit: float = 0.0
    impulse_x: float = 0.5
    impulse_y: float = 0.5
    impulse: float = 0.0

    def __post_init__(self) -> None:
        if self.target_mass <= 0.0:
            self.reset()

    def reset(self) -> None:
        self.density[:] = [0.0] * WAX_SIZE
        self.heat[:] = [0.0] * WAX_SIZE
        self.flow_x[:] = [0.0] * WAX_SIZE
        self.flow_y[:] = [0.0] * WAX_SIZE
        # Three deliberately unequal droplets. Their density—not separate
        # actor geometry—defines whether wax has joined or separated.
        for center_x, center_y, radius in (
            (0.36, 0.74, 0.17),
            (0.57, 0.56, 0.13),
            (0.68, 0.79, 0.10),
        ):
            self._stamp_density(center_x, center_y, radius, 1.0)
        self.target_mass = sum(self.density)
        self.phase = 0.0
        self.last_hit = 0.0
        self.impulse = 0.0

    def _stamp_density(self, center_x: float, center_y: float, radius: float, amount: float) -> None:
        left = max(0, int((center_x - radius) * WAX_WIDTH) - 1)
        right = min(WAX_WIDTH - 1, int((center_x + radius) * WAX_WIDTH) + 1)
        top = max(0, int((center_y - radius) * WAX_HEIGHT) - 1)
        bottom = min(WAX_HEIGHT - 1, int((center_y + radius) * WAX_HEIGHT) + 1)
        for y in range(top, bottom + 1):
            normalized_y = (y + 0.5) / WAX_HEIGHT
            for x in range(left, right + 1):
                normalized_x = (x + 0.5) / WAX_WIDTH
                distance = math.hypot(normalized_x - center_x, normalized_y - center_y)
                if distance < radius:
                    index = y * WAX_WIDTH + x
                    self.density[index] = clamp(
                        self.density[index]
                        + (1.0 - distance / radius) * amount
                    )

    @staticmethod
    def _context_gain(context: str) -> tuple[float, float]:
        return {
            "music": (1.0, 1.0),
            "radio": (0.66, 0.68),
            "podcast": (0.28, 0.34),
            "microphone": (0.16, 0.20),
        }.get(context, (0.66, 0.68))

    def advance(
        self,
        dt: float,
        forces: AudioForces,
        narrative: NarrativeState,
        context: str,
    ) -> None:
        """Advance fixed simulation work once; no array scales with the TUI."""

        dt = clamp(dt, 1.0 / 120.0, 1.0 / 12.0)
        heat_gain, motion_gain = self._context_gain(context)
        sustained_heat = clamp(
            forces.bass * 0.56
            + forces.energy * 0.16
            + narrative.held_pressure * 0.24
            + narrative.cadence * 0.08
            - narrative.aftermath * 0.10
        ) * heat_gain
        hit = clamp(forces.transient * 0.82 + forces.pulse * 0.38)
        if hit > self.last_hit + 0.08:
            angle = math.pi * (0.20 + forces.tone * 0.60) + math.sin(self.phase) * 0.18
            self.impulse_x = clamp(0.5 + math.cos(angle) * 0.31)
            self.impulse_y = clamp(0.70 + math.sin(angle) * 0.16)
            self.impulse = max(self.impulse, hit * motion_gain)
        self.last_hit = hit
        self.impulse *= math.exp(-3.6 * dt)
        self.phase += dt * (0.20 + forces.tempo * 0.42 + sustained_heat * 0.14)

        next_heat = [0.0] * WAX_SIZE
        next_flow_x = [0.0] * WAX_SIZE
        next_flow_y = [0.0] * WAX_SIZE
        for y in range(WAX_HEIGHT):
            normalized_y = (y + 0.5) / WAX_HEIGHT
            wall_y = min(normalized_y, 1.0 - normalized_y) * 2.0
            bottom_heat = max(0.0, (normalized_y - 0.66) / 0.34) * sustained_heat
            for x in range(WAX_WIDTH):
                index = y * WAX_WIDTH + x
                normalized_x = (x + 0.5) / WAX_WIDTH
                wall_x = min(normalized_x, 1.0 - normalized_x) * 2.0
                cooled = self.heat[index] * (1.0 - dt * (0.38 + (1.0 - wall_x) * 0.46 + (1.0 - wall_y) * 0.24))
                heat = clamp(cooled + bottom_heat * dt * 1.9)
                next_heat[index] = heat
                center = 1.0 - abs(normalized_x - 0.5) * 2.0
                upward = heat * (0.38 + center * 0.30) * motion_gain
                return_flow = (1.0 - center) * (0.050 + sustained_heat * 0.08)
                swirl = math.sin(self.phase + normalized_y * math.tau) * forces.voice * 0.026
                # Closed convection: hot wax rises centrally, fans outward
                # near the cool top, and returns inward along the warm base.
                circulation_x = (
                    (normalized_x - 0.5)
                    * (0.52 - normalized_y)
                    * (0.12 + sustained_heat * 0.11)
                    * motion_gain
                )
                # Dense, cooled wax fans into separate return lobes along the
                # vessel floor. This lets a previously connected neck release
                # naturally instead of preserving one permanent giant blob.
                cooling_split = (
                    math.tanh((normalized_x - 0.5) * 9.0)
                    * max(0.0, (normalized_y - 0.56) / 0.44)
                    * (1.0 - sustained_heat)
                    * 0.24
                    * motion_gain
                )
                cooling_sink = (
                    (1.0 - sustained_heat)
                    * (0.030 + self.density[index] * 0.10)
                    * motion_gain
                    * max(0.0, 1.0 - normalized_y) * 1.45
                )
                impulse_dx = normalized_x - self.impulse_x
                impulse_dy = normalized_y - self.impulse_y
                impulse_distance = max(0.035, math.hypot(impulse_dx, impulse_dy))
                impulse_envelope = self.impulse * math.exp(-(impulse_distance / 0.16) ** 2)
                next_flow_x[index] = clamp(
                    -impulse_dy / impulse_distance * impulse_envelope * 0.18
                    + swirl
                    + circulation_x
                    + cooling_split,
                    -0.22,
                    0.22,
                )
                next_flow_y[index] = clamp(
                    -upward
                    + return_flow
                    + cooling_sink
                    + impulse_dx / impulse_distance * impulse_envelope * 0.18,
                    -0.34,
                    0.22,
                )

        advected = [0.0] * WAX_SIZE
        next_density = [0.0] * WAX_SIZE
        # One semi-Lagrangian density pass plus one fixed four-neighbor
        # surface-tension pass are enough for continuous topology changes.
        for y in range(WAX_HEIGHT):
            for x in range(WAX_WIDTH):
                index = y * WAX_WIDTH + x
                source_x = x - next_flow_x[index] * dt * WAX_WIDTH
                source_y = y - next_flow_y[index] * dt * WAX_HEIGHT
                advected[index] = _sample(self.density, source_x, source_y)
        # A slightly stronger fixed surface-tension blend keeps hot wax as
        # rounded, organic masses instead of a sharp density wedge.
        viscosity = clamp(0.070 + (1.0 - sustained_heat) * 0.060)
        cooling = 1.0 - sustained_heat
        for y in range(WAX_HEIGHT):
            for x in range(WAX_WIDTH):
                index = y * WAX_WIDTH + x
                left = advected[y * WAX_WIDTH + max(0, x - 1)]
                right = advected[y * WAX_WIDTH + min(WAX_WIDTH - 1, x + 1)]
                up = advected[max(0, y - 1) * WAX_WIDTH + x]
                down = advected[min(WAX_HEIGHT - 1, y + 1) * WAX_WIDTH + x]
                neighbor_mean = (left + right + up + down) * 0.25
                smoothed = lerp(advected[index], neighbor_mean, viscosity)
                # Cooling contracts thin connections first. This gentle
                # threshold sharpening is what lets a joined wax neck pinch
                # apart without tracking components or adding iterations.
                sharpened = clamp(0.34 + (smoothed - 0.34) * (1.0 + cooling * 0.24))
                contracted = lerp(smoothed, sharpened, cooling * 0.42)
                # At the cooled floor a broad connected mass develops a
                # narrow central pinch. Conservation below redistributes that
                # wax into its two return lobes rather than deleting it.
                floor = max(0.0, ((y + 0.5) / WAX_HEIGHT - 0.62) / 0.38)
                pinch = math.exp(-(((x + 0.5) / WAX_WIDTH - 0.5) / 0.075) ** 2)
                next_density[index] = clamp(
                    contracted * (1.0 - cooling * floor * pinch * 0.060)
                )

        mass = sum(next_density)
        if mass > 0.0001:
            correction = clamp(self.target_mass / mass, 0.70, 8.00)
            # Density is mass, not alpha: allowing a compact cell above one
            # keeps the fixed vessel conservative when cooled wax pinches.
            next_density = [value * correction for value in next_density]
        self.density = next_density
        self.heat = next_heat
        self.flow_x = next_flow_x
        self.flow_y = next_flow_y

    def density_at(self, x: float, y: float) -> float:
        return _sample(self.density, x * (WAX_WIDTH - 1), y * (WAX_HEIGHT - 1))

    def heat_at(self, x: float, y: float) -> float:
        return _sample(self.heat, x * (WAX_WIDTH - 1), y * (WAX_HEIGHT - 1))

    def occupied_bounds(self, threshold: float = 0.11) -> tuple[float, float, float, float] | None:
        occupied = [
            (index % WAX_WIDTH, index // WAX_WIDTH)
            for index, value in enumerate(self.density)
            if value >= threshold
        ]
        if not occupied:
            return None
        left = max(0, min(x for x, _ in occupied) - 1)
        right = min(WAX_WIDTH - 1, max(x for x, _ in occupied) + 1)
        top = max(0, min(y for _, y in occupied) - 1)
        bottom = min(WAX_HEIGHT - 1, max(y for _, y in occupied) + 1)
        return (
            left / WAX_WIDTH,
            top / WAX_HEIGHT,
            (right + 1) / WAX_WIDTH,
            (bottom + 1) / WAX_HEIGHT,
        )
