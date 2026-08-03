"""Pure mappings from semantic organism fields to terminal cells."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from .organism import Body, FieldFrame, tile_axis_scales
from .signals import AudioForces, clamp
from .wax import WAX_HEIGHT, WAX_WIDTH, WaxState


# The daily in-app material control remains deliberately limited to its
# portable modes. Volume and Wax are opt-in TOML experiments.
MATERIAL_NAMES = ("text", "fluid")
WEIGHT_NAMES = ("airy", "balanced", "full")
EDGE_NAMES = ("soft", "defined")
AFTERGLOW_NAMES = ("quiet", "present")
DEFAULT_GLYPHS = " .,:;~oO@"

_WEIGHT_GAIN = {"airy": 0.82, "balanced": 1.0, "full": 1.12}
_EDGE_GAIN = {"soft": 0.17, "defined": 0.27}
_AFTERGLOW_GAIN = {"quiet": 0.22, "present": 0.34}

# A quadrant mask gives Fluid a 2x2 drawing surface inside each terminal cell.
# Bit order is upper-left, upper-right, lower-left, lower-right.
_QUADRANT_GLYPHS = (
    " ",
    "▘",
    "▝",
    "▀",
    "▖",
    "▌",
    "▞",
    "▛",
    "▗",
    "▚",
    "▐",
    "▜",
    "▄",
    "▙",
    "▟",
    "█",
)
_FLUID_OCCUPANCY = 0.18


@dataclass(slots=True, frozen=True)
class MaterialCell:
    glyph: str
    shade: float
    attention: float
    # Fluid supplies a surface-facing value for terminal palettes with two
    # ordinary body colors. Text leaves it unset and retains shade mapping.
    face: float | None = None


@dataclass(slots=True, frozen=True)
class MaterialSpan:
    start: int
    cells: tuple[MaterialCell, ...]


@dataclass(slots=True, frozen=True)
class _PreparedContour:
    center_x: float
    center_y: float
    depth: float
    tilt: float
    spin: float
    radius_x: float
    radius_y: float
    active_extent: float
    detail_frequency: float
    detail_phase: float
    detail_amplitude: float
    pulse_phase: float
    pulse_amplitude: float
    shear_gain: float
    event: float
    spike: float
    impact_y: float
    impact_side: float
    impact_vertical: float
    extension_scale: float
    attention_x: float
    attention_y: float
    attention_scale_x: float
    attention_scale_y: float
    surface_ripple: float
    surface_ripple_angle: float
    surface_ripple_phase: float


@dataclass(slots=True, frozen=True)
class MaterialStyle:
    glyphs: str = DEFAULT_GLYPHS
    weight: str = "balanced"
    edge: str = "soft"
    afterglow: str = "present"


@dataclass(slots=True, frozen=True)
class _VolumeProjection:
    """Body geometry shared by every fixed subcell sample in one frame."""

    body: Body
    cosine: float
    sine: float
    lobe_cosine: float
    lobe_sine: float
    organic_cosine: float
    organic_sine: float
    main: tuple[float, float, float, float, float, float, str]
    lobe: tuple[float, float, float, float, float, float, str]
    impact_x: float
    impact_y: float
    thermal_leader: bool


def normalize_glyph_ramp(value: object) -> str:
    """Keep only printable, non-combining characters with one terminal column."""

    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = "".join(str(part) for part in value)
    else:
        text = str(value)

    accepted = []
    for character in text:
        category = unicodedata.category(character)
        if character != " " and (category.startswith(("C", "M")) or not character.isprintable()):
            continue
        if unicodedata.east_asian_width(character) in {"W", "F"}:
            continue
        accepted.append(character)
    ramp = "".join(accepted)
    if " " not in ramp:
        ramp = " " + ramp
    if len(set(ramp)) < 2:
        return DEFAULT_GLYPHS
    return ramp


def visual_shade(value: float, texture: float = 0.0) -> float:
    visible_cutoff = 0.055
    if value <= visible_cutoff:
        return 0.0
    shade = clamp(((value - visible_cutoff) / (1.0 - visible_cutoff)) ** 0.82)
    return clamp(shade + texture * shade * (1.0 - shade))


def _sample(grid: list[list[float]], x: float, y: float, width: int, height: int) -> float:
    if not grid or not grid[0]:
        return 0.0
    source_height = len(grid)
    source_width = len(grid[0])
    grid_x = clamp(x, 0.0, max(0.0, width - 1.0)) * (source_width - 1) / max(1, width - 1)
    grid_y = clamp(y, 0.0, max(0.0, height - 1.0)) * (source_height - 1) / max(1, height - 1)
    left = int(grid_x)
    right = min(source_width - 1, left + 1)
    top = int(grid_y)
    bottom = min(source_height - 1, top + 1)
    mix_x = grid_x - left
    mix_y = grid_y - top
    upper = grid[top][left] * (1.0 - mix_x) + grid[top][right] * mix_x
    lower = grid[bottom][left] * (1.0 - mix_x) + grid[bottom][right] * mix_x
    return upper * (1.0 - mix_y) + lower * mix_y


def _grid_gradient(
    grid: list[list[float]], x: float, y: float, width: int, height: int
) -> tuple[float, float]:
    """Estimate a field slope in output-cell coordinates without extra interpolation."""

    if not grid or not grid[0]:
        return 0.0, 0.0
    source_height = len(grid)
    source_width = len(grid[0])
    grid_x = clamp(x, 0.0, max(0.0, width - 1.0)) * (source_width - 1) / max(1, width - 1)
    grid_y = clamp(y, 0.0, max(0.0, height - 1.0)) * (source_height - 1) / max(1, height - 1)
    column = int(round(grid_x))
    row = int(round(grid_y))
    left = max(0, column - 1)
    right = min(source_width - 1, column + 1)
    top = max(0, row - 1)
    bottom = min(source_height - 1, row + 1)
    scale_x = (source_width - 1) / max(1, width - 1)
    scale_y = (source_height - 1) / max(1, height - 1)
    gradient_x = (grid[row][right] - grid[row][left]) / max(1, right - left) * scale_x
    gradient_y = (grid[bottom][column] - grid[top][column]) / max(1, bottom - top) * scale_y
    return gradient_x, gradient_y


def _semantic_sample(
    frame: FieldFrame,
    x: float,
    y: float,
    width: int,
    height: int,
    style: MaterialStyle,
) -> tuple[float, float]:
    mass = _sample(frame.mass, x, y, width, height)
    surface = _sample(frame.surface, x, y, width, height)
    attention = _sample(frame.attention, x, y, width, height)
    mass_gain = _WEIGHT_GAIN.get(style.weight, _WEIGHT_GAIN["balanced"])
    edge_gain = _EDGE_GAIN.get(style.edge, _EDGE_GAIN["soft"])
    afterglow_gain = _AFTERGLOW_GAIN.get(style.afterglow, _AFTERGLOW_GAIN["present"])
    value = clamp(
        mass * mass_gain
        + surface * edge_gain
        + min(afterglow_gain, attention * afterglow_gain)
    )
    return value, attention


class TextMaterial:
    name = "text"

    def render(
        self,
        frame: FieldFrame,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
    ) -> list[list[MaterialCell]]:
        """Prepare semantic rows once, then interpolate only across terminal columns."""

        width = max(1, width)
        height = max(1, height)
        if not frame.mass or not frame.mass[0]:
            empty = MaterialCell(" ", 0.0, 0.0)
            return [[empty] * width for _ in range(height)]
        mass_gain = _WEIGHT_GAIN.get(style.weight, _WEIGHT_GAIN["balanced"])
        edge_gain = _EDGE_GAIN.get(style.edge, _EDGE_GAIN["soft"])
        glow_gain = _AFTERGLOW_GAIN.get(
            style.afterglow, _AFTERGLOW_GAIN["present"]
        )
        semantic_rows = [
            [
                clamp(mass * mass_gain + surface * edge_gain + attention * glow_gain)
                for mass, surface, attention in zip(mass_row, surface_row, attention_row)
            ]
            for mass_row, surface_row, attention_row in zip(
                frame.mass, frame.surface, frame.attention
            )
        ]
        glyphs = style.glyphs if len(set(style.glyphs)) >= 2 else DEFAULT_GLYPHS
        rows = []
        for y in range(height):
            source_y = round(y * (len(semantic_rows) - 1) / max(1, height - 1))
            semantic_row = semantic_rows[source_y]
            attention_row = frame.attention[source_y]
            cells = []
            for x in range(width):
                value = _sample_row(semantic_row, x, width)
                attention = _sample_row(attention_row, x, width)
                texture = math.sin(x * 1.73 + y * 2.31 + phase * 3.2) * 0.035
                shade = clamp(visual_shade(value, texture) + attention * 0.10)
                level = int(shade * (len(glyphs) - 1))
                if shade > 0.0:
                    level = max(1, level)
                cells.append(MaterialCell(glyphs[level] if level else " ", shade, attention))
            rows.append(cells)
        return rows

    def cell(
        self,
        frame: FieldFrame,
        x: int,
        y: int,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
    ) -> MaterialCell:
        value, attention = _semantic_sample(frame, x, y, width, height, style)
        texture = math.sin(x * 1.73 + y * 2.31 + phase * 3.2) * 0.035
        shade = clamp(visual_shade(value, texture) + attention * 0.10)
        glyphs = style.glyphs if len(set(style.glyphs)) >= 2 else DEFAULT_GLYPHS
        level = int(shade * (len(glyphs) - 1))
        if shade > 0.0:
            level = max(1, level)
        return MaterialCell(glyphs[level] if level else " ", shade, attention)


class FluidMaterial:
    name = "fluid"

    def __init__(self) -> None:
        self._span_cache_key: tuple[object, ...] | None = None
        self._span_cache: dict[int, tuple[MaterialSpan, ...]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._mask_memory_key: tuple[object, ...] | None = None
        self._mask_memory: dict[tuple[int, int], int] = {}

    def reset_cache_metrics(self) -> None:
        self._cache_hits = 0
        self._cache_misses = 0

    def cache_metrics(self) -> tuple[int, int]:
        return self._cache_hits, self._cache_misses

    def render(
        self,
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> list[list[MaterialCell]]:
        """Expand sparse spans for compatibility with snapshots and callers."""

        width = max(1, width)
        height = max(1, height)
        empty = MaterialCell(" ", 0.0, 0.0)
        rows = [[empty] * width for _ in range(height)]
        for y, spans in self.render_spans(
            bodies, forces, width, height, style, phase, cell_aspect
        ).items():
            for span in spans:
                rows[y][span.start : span.start + len(span.cells)] = span.cells
        return rows

    def render_spans(
        self,
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> dict[int, tuple[MaterialSpan, ...]]:
        """Return occupied contour runs without allocating blank screen cells."""

        width = max(1, width)
        height = max(1, height)
        cache_key = self._cache_key(
            bodies, forces, width, height, style, phase, cell_aspect
        )
        if cache_key == self._span_cache_key:
            self._cache_hits += 1
            return self._span_cache
        self._cache_misses += 1
        axis_x, axis_y = tile_axis_scales(width, height, cell_aspect)
        weight_extent = {"airy": 1.08, "balanced": 1.16, "full": 1.23}.get(
            style.weight, 1.16
        )
        edge_lift = {"soft": 0.0, "defined": 0.08}.get(style.edge, 0.0)
        glow_gain = _AFTERGLOW_GAIN.get(
            style.afterglow, _AFTERGLOW_GAIN["present"]
        )
        prepared = self._prepare_bodies(
            bodies,
            forces,
            width,
            height,
            phase,
            axis_x,
            axis_y,
            weight_extent,
        )
        use_surface_memory = any(body.surface_ripple > 0.005 for body in prepared)
        memory_key = (width, height, style, round(cell_aspect * 20))
        if use_surface_memory and memory_key != self._mask_memory_key:
            self._mask_memory_key = memory_key
            self._mask_memory = {}
        next_mask_memory: dict[tuple[int, int], int] = {}

        rows: dict[int, tuple[MaterialSpan, ...]] = {}
        for y in range(height):
            upper = self._intervals_at(
                prepared,
                y - 0.27,
                width,
                height,
            )
            lower = self._intervals_at(
                prepared,
                y + 0.27,
                width,
                height,
            )
            if not upper and not lower:
                continue
            left = max(0, int(math.floor(min(item[0] for item in upper + lower))) - 1)
            right = min(width - 1, int(math.ceil(max(item[1] for item in upper + lower))) + 1)
            spans: list[MaterialSpan] = []
            run_start = 0
            run: list[MaterialCell] = []
            for x in range(left, right + 1):
                mask = 0
                previous_mask = self._mask_memory.get((x, y), 0) if use_surface_memory else 0
                if self._surface_bit(upper, x - 0.24, previous_mask & 1):
                    mask |= 1
                if self._surface_bit(upper, x + 0.24, previous_mask & 2):
                    mask |= 2
                if self._surface_bit(lower, x - 0.24, previous_mask & 4):
                    mask |= 4
                if self._surface_bit(lower, x + 0.24, previous_mask & 8):
                    mask |= 8
                if not mask:
                    if run:
                        spans.append(MaterialSpan(run_start, tuple(run)))
                        run = []
                    continue
                if use_surface_memory:
                    next_mask_memory[(x, y)] = mask
                attention = self._attention_at(
                    prepared,
                    x,
                    y,
                    width,
                    height,
                )
                attention = clamp(attention * (0.65 + glow_gain))
                depth, face = self._surface_at(prepared, x, y, width, height)
                coverage = mask.bit_count() / 4.0
                shade = clamp(
                    0.34
                    + coverage * 0.30
                    + forces.bass * 0.05
                    + forces.detail * edge_lift
                    + attention * 0.10
                )
                # In an overlap, the nearest contour gets a little more of
                # the existing color budget. This makes occlusion legible
                # without allocating terminal background color pairs.
                shade *= 0.82 + depth * 0.18
                if not run:
                    run_start = x
                run.append(MaterialCell(_QUADRANT_GLYPHS[mask], shade, attention, face))
            if run:
                spans.append(MaterialSpan(run_start, tuple(run)))
            if spans:
                rows[y] = tuple(spans)
        self._span_cache_key = cache_key
        self._span_cache = rows
        if use_surface_memory:
            self._mask_memory = next_mask_memory
        return rows

    @staticmethod
    def _surface_bit(
        intervals: list[tuple[float, float]], position: float, was_inside: int
    ) -> bool:
        """Quantize a moving contour with a narrow, one-cell edge cushion."""

        margin = max(
            (min(position - left, right - position) for left, right in intervals),
            default=-1.0,
        )
        return margin >= (0.055 if not was_inside else -0.095)

    @staticmethod
    def _cache_key(
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> tuple[object, ...]:
        body_pose = tuple(
            (
                round(body.x * width * 2),
                round(body.y * height * 2),
                round(body.z * 16),
                round(body.radius * min(width, height * cell_aspect) * 4),
                round(body.stretch_x * 16),
                round(body.stretch_y * 16),
                round(body.presence * 8),
                round(body.afterglow * 8),
                round(body.spike * 12),
                round(body.impact_angle * 6),
                round(body.surface_ripple * 12),
                round(body.surface_ripple_angle * 6),
                round(body.surface_ripple_phase * 8),
            )
            for body in bodies
            if body.presence >= 0.01
        )
        force_pose = tuple(
            round(value * 10)
            for value in (
                forces.bass,
                forces.voice,
                forces.detail,
                forces.transient,
                forces.energy,
                forces.tone,
                forces.tempo,
                forces.pulse,
                forces.flux,
                forces.rhythm_density,
                forces.rhythm_impulse,
                *forces.bands,
                *forces.hits,
                *forces.deviations,
            )
        )
        return (
            width,
            height,
            style,
            round(cell_aspect * 20),
            round(phase * 8),
            body_pose,
            force_pose,
        )

    @staticmethod
    def _prepare_bodies(
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        phase: float,
        axis_x: float,
        axis_y: float,
        extent: float,
    ) -> tuple[_PreparedContour, ...]:
        prepared = []
        # This is a camera drift, not a second simulation. It projects the
        # persistent z axis into a small opposing foreground/background shift.
        camera_x = math.sin(phase * 0.19) * 0.018
        camera_y = math.cos(phase * 0.15) * 0.012
        for body in bodies:
            if body.presence < 0.01:
                continue
            radius = max(0.035, body.radius)
            depth = clamp(body.z)
            depth_scale = 0.78 + depth * 0.36
            parallax = 0.5 - depth
            spin = (
                phase * (0.62 + forces.tempo * 2.8 + forces.rhythm_density * 0.80)
                + body.phase * 1.9
            )
            # A turn changes the projected width as an oblong body goes
            # side-on, while tilt makes that turn legible in the silhouette.
            turn_scale = 0.76 + abs(math.cos(spin)) * 0.24
            tilt = math.sin(spin) * (0.18 + body.character.deformation * 0.36)
            local_band = forces.bands[body.band % len(forces.bands)] if forces.bands else 0.0
            local_hit = forces.hits[body.band % len(forces.hits)] if forces.hits else 0.0
            band_position = body.band / max(1, len(forces.bands) - 1)
            pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
            breath = 1.0 + forces.bass * body.character.bass * 0.055 + local_band * 0.025
            radius_x = (
                radius
                * axis_x
                * max(0.72, body.stretch_x)
                * breath
                * depth_scale
                * turn_scale
            )
            radius_y = radius * axis_y * max(0.72, body.stretch_y) * breath * depth_scale
            active_extent = extent * math.sqrt(clamp(body.presence, 0.0, 1.0))
            detail_amplitude = (
                forces.detail
                * body.character.detail
                * body.character.deformation
                * (0.045 + forces.tone * 0.035)
                + local_band * pitch_affinity * body.character.deformation * 0.035
            )
            if body.surface_ripples_active:
                # Leave room for the persistent wave below; otherwise the
                # immediate detail contour reads as a jumpy second animation.
                detail_amplitude *= 0.28
            pulse_amplitude = (
                forces.pulse * (0.045 + pitch_affinity * 0.035)
                + forces.rhythm_density
                * body.character.detail
                * (0.018 + pitch_affinity * 0.018)
            )
            if body.surface_ripples_active:
                pulse_amplitude *= 0.26
            event = max(body.afterglow, local_hit)
            spike = body.spike
            impact_side = math.cos(body.impact_angle)
            impact_vertical = math.sin(body.impact_angle)
            attention_radius_x = max(0.012, body.radius * axis_x)
            attention_radius_y = max(0.012, body.radius * axis_y)
            prepared.append(
                _PreparedContour(
                    center_x=clamp(body.x + camera_x * parallax) * max(1, width - 1),
                    center_y=clamp(body.y + camera_y * parallax),
                    depth=depth,
                    tilt=tilt,
                    spin=spin,
                    radius_x=radius_x,
                    radius_y=radius_y,
                    active_extent=active_extent,
                    detail_frequency=3.2 + forces.tone * 2.4,
                    detail_phase=(
                        phase
                        * (1.15 + forces.tempo * 2.6 + forces.rhythm_density * 4.0)
                        + body.phase
                    ),
                    detail_amplitude=detail_amplitude,
                    pulse_phase=-phase * (1.4 + forces.tempo * 3.2) + body.phase * 1.3,
                    pulse_amplitude=pulse_amplitude,
                    shear_gain=(
                        radius_x
                        * forces.voice
                        * body.character.voice
                        * body.character.deformation
                        * math.sin(body.phase + phase * (0.70 + forces.tempo * 0.55))
                        * (0.055 if body.surface_ripples_active else 0.15)
                        * max(1, width - 1)
                    ),
                    event=event,
                    spike=spike,
                    impact_y=math.sin(body.impact_angle) * active_extent * 0.72,
                    impact_side=impact_side,
                    impact_vertical=impact_vertical,
                    extension_scale=(
                        radius_x
                        * max(1, width - 1)
                        * spike
                        * body.character.deformation
                        * (0.16 + abs(impact_side) * 0.38)
                        * 1.70
                    ),
                    attention_x=clamp(
                        body.x
                        + camera_x * parallax
                        + impact_side * attention_radius_x * depth_scale * 0.72
                    ),
                    attention_y=(
                        clamp(
                            body.y
                            + camera_y * parallax
                            + math.sin(body.impact_angle)
                            * attention_radius_y
                            * depth_scale
                            * 0.72
                        )
                    ),
                    attention_scale_x=max(0.012, attention_radius_x * depth_scale * 0.42),
                    attention_scale_y=max(0.012, attention_radius_y * depth_scale * 0.42),
                    surface_ripple=body.surface_ripple if body.surface_ripples_active else 0.0,
                    surface_ripple_angle=body.surface_ripple_angle,
                    surface_ripple_phase=body.surface_ripple_phase,
                )
            )
        return tuple(prepared)

    @staticmethod
    def _intervals_at(
        bodies: tuple[_PreparedContour, ...],
        sample_y: float,
        width: int,
        height: int,
    ) -> list[tuple[float, float]]:
        normalized_y = sample_y / max(1, height - 1)
        intervals: list[tuple[float, float]] = []
        for body in bodies:
            relative_y = normalized_y - body.center_y
            dy = relative_y / max(0.001, body.radius_y)
            vertical_extra = body.spike * abs(body.impact_vertical) * 0.32
            cosine = math.cos(body.tilt)
            sine = math.sin(body.tilt)
            inverse_x2 = 1.0 / max(0.001, body.radius_x) ** 2
            inverse_y2 = 1.0 / max(0.001, body.radius_y) ** 2
            quadratic_x = cosine * cosine * inverse_x2 + sine * sine * inverse_y2
            quadratic_xy = 2.0 * cosine * sine * (inverse_x2 - inverse_y2)
            quadratic_y = sine * sine * inverse_x2 + cosine * cosine * inverse_y2
            discriminant = (quadratic_xy * relative_y) ** 2 - 4.0 * quadratic_x * (
                quadratic_y * relative_y * relative_y - body.active_extent**2
            )
            if discriminant <= 0.0:
                if abs(dy) >= body.active_extent + vertical_extra:
                    continue
                if vertical_extra <= 0.001 or dy * body.impact_vertical <= 0.0:
                    continue
                progress = (abs(dy) - body.active_extent) / vertical_extra
                half = (
                    body.radius_x
                    * max(1, width - 1)
                    * body.spike
                    * 0.22
                    * max(0.0, 1.0 - progress)
                )
                center = body.center_x + body.impact_side * body.extension_scale * progress * 0.28
                intervals.append((center - half, center + half))
                continue
            root = math.sqrt(discriminant)
            lower_x = (-quadratic_xy * relative_y - root) / (2.0 * quadratic_x)
            upper_x = (-quadratic_xy * relative_y + root) / (2.0 * quadratic_x)
            ripple = 1.0 + math.sin(
                dy * body.detail_frequency + body.detail_phase
            ) * body.detail_amplitude
            ripple += math.sin(dy * 4.4 + body.pulse_phase) * body.pulse_amplitude
            center = body.center_x + (lower_x + upper_x) * 0.5 * max(1, width - 1)
            center += dy * body.shear_gain
            half = (upper_x - lower_x) * 0.5 * max(1, width - 1)
            half *= max(0.82, ripple)
            left = center - half
            right = center + half

            if body.surface_ripple >= 0.015:
                # The two intersections of this scanline correspond to two
                # different points on the ellipse's perimeter.  A localized
                # travelling bulge visits them in turn, so the silhouette
                # moves continuously around the organism rather than jumping
                # between unrelated terminal cells.
                edge_angle = math.asin(clamp(dy / max(0.001, body.active_extent), -1.0, 1.0))
                wave_angle = body.surface_ripple_angle + body.surface_ripple_phase

                def travelling_bulge(perimeter_angle: float) -> float:
                    delta = math.atan2(
                        math.sin(perimeter_angle - wave_angle),
                        math.cos(perimeter_angle - wave_angle),
                    )
                    envelope = math.exp(-((delta / 0.62) ** 2))
                    return body.surface_ripple * envelope * (0.42 + 0.58 * math.cos(delta * 3.2))

                left_bulge = travelling_bulge(math.pi - edge_angle)
                right_bulge = travelling_bulge(edge_angle)
                # This is still a fraction of the local radius, but needs to
                # clear one quadrant sample at ordinary 60-column widths so
                # a listener can actually perceive the wave travelling.
                edge_scale = half * 0.30
                left -= edge_scale * left_bulge
                right += edge_scale * right_bulge

            # A fast event forms one directional point plus smaller nearby
            # teeth. Afterglow remains a slower, independent color memory.
            if body.spike >= 0.02:
                impact_nearby = math.exp(-((dy - body.impact_y) / 0.17) ** 2)
                teeth_envelope = math.exp(-((dy - body.impact_y) / 0.68) ** 2)
                teeth = max(0.0, math.sin((dy - body.impact_y) * 13.0 + 0.7)) ** 6
                extension = body.extension_scale * (
                    impact_nearby + teeth * teeth_envelope * 0.28
                )
                if body.impact_side > 0.18:
                    right += extension
                elif body.impact_side < -0.18:
                    left -= extension
                else:
                    left -= extension * 0.55
                    right += extension * 0.55
            intervals.append((left, right))
        return _merge_intervals(intervals)

    @staticmethod
    def _attention_at(
        bodies: tuple[_PreparedContour, ...],
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> float:
        nx = x / max(1, width - 1)
        ny = y / max(1, height - 1)
        attention = 0.0
        for body in bodies:
            if body.event < 0.02:
                continue
            dx = (nx - body.attention_x) / body.attention_scale_x
            dy = (ny - body.attention_y) / body.attention_scale_y
            attention = max(
                attention,
                body.event * math.exp(-(dx * dx + dy * dy) * 1.8),
            )
        return clamp(attention)

    @staticmethod
    def _surface_at(
        bodies: tuple[_PreparedContour, ...],
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> tuple[float, float | None]:
        """Return nearest visible surface depth and its rotating face color."""

        projected_x = x / max(1, width - 1)
        normalized_y = y / max(1, height - 1)
        nearest = 0.0
        face: float | None = None
        for body in bodies:
            dx = projected_x - body.center_x / max(1, width - 1)
            dy = normalized_y - body.center_y
            cosine = math.cos(body.tilt)
            sine = math.sin(body.tilt)
            local_x = cosine * dx + sine * dy
            local_y = -sine * dx + cosine * dy
            normal_x = local_x / max(0.001, body.radius_x * body.active_extent)
            normal_y = local_y / max(0.001, body.radius_y * body.active_extent)
            radius2 = normal_x * normal_x + normal_y * normal_y
            if radius2 <= 1.0 and body.depth >= nearest:
                nearest = max(nearest, body.depth)
                normal_z = math.sqrt(max(0.0, 1.0 - radius2))
                light_x = math.sin(body.spin)
                light_y = math.cos(body.spin) * 0.38
                surface = normal_x * light_x + normal_y * light_y + normal_z * 0.70
                face = clamp(0.5 + surface / 2.54)
        return nearest, face

    def cell(
        self,
        frame: FieldFrame,
        x: int,
        y: int,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
    ) -> MaterialCell:
        value, attention = _semantic_sample(frame, x, y, width, height, style)
        gradient_x, gradient_y = _grid_gradient(frame.mass, x, y, width, height)
        mass_gain = _WEIGHT_GAIN.get(style.weight, _WEIGHT_GAIN["balanced"])
        occupancy = max(0.11, _FLUID_OCCUPANCY - attention * 0.035)
        samples = []
        mask = 0
        for offset_x, offset_y, bit in (
            (-0.26, -0.28, 1),
            (0.26, -0.28, 2),
            (-0.26, 0.28, 4),
            (0.26, 0.28, 8),
        ):
            sample_value = value + mass_gain * (
                gradient_x * offset_x + gradient_y * offset_y
            )
            sample_shade = visual_shade(clamp(sample_value))
            samples.append((bit, sample_shade))
            if sample_shade >= occupancy:
                mask |= bit
        if not mask:
            return MaterialCell(" ", 0.0, attention)

        occupied = [
            sample_shade
            for bit, sample_shade in samples
            if mask & bit
        ]
        # Average coverage keeps small edge fragments quiet. Attention can still
        # briefly lift them without turning the whole body into a bright slab.
        shade = clamp(sum(occupied) / len(occupied) * 0.92 + attention * 0.08)
        return MaterialCell(_QUADRANT_GLYPHS[mask], shade, attention)


class VolumeMaterial:
    """Sparse software projection of rotating asymmetric body volumes.

    It evaluates only the terminal cells covered by a body's projected bounds.
    Every quadrant retains its nearest surface depth, providing real occlusion
    without a screen-wide scalar field or a GPU dependency.
    """

    name = "volume"
    # Keep the solid 2x2 quadrant surface that gives Volume its fluid mass.
    # Geometry is still depth-tested and sparse; changing it into Braille
    # dots made the edge finer but broke the organism's continuous body.
    # (offset_x, offset_y, storage slot, quadrant bit)
    _SAMPLES = (
        (-0.26, -0.28, 0, 0x01),
        (0.26, -0.28, 1, 0x02),
        (-0.26, 0.28, 2, 0x04),
        (0.26, 0.28, 3, 0x08),
    )

    def render(
        self,
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> list[list[MaterialCell]]:
        width = max(1, width)
        height = max(1, height)
        empty = MaterialCell(" ", 0.0, 0.0)
        rows = [[empty] * width for _ in range(height)]
        for y, spans in self.render_spans(
            bodies, forces, width, height, style, phase, cell_aspect
        ).items():
            for span in spans:
                rows[y][span.start : span.start + len(span.cells)] = span.cells
        return rows

    def render_spans(
        self,
        bodies: list[Body],
        forces: AudioForces,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> dict[int, tuple[MaterialSpan, ...]]:
        width = max(1, width)
        height = max(1, height)
        axis_x, axis_y = tile_axis_scales(width, height, cell_aspect)
        # A cell holds four (depth, face, shade, attention) samples. Entries
        # appear only inside projected bounds, which keeps idle CPU bounded.
        buffer: dict[tuple[int, int], list[tuple[float, float, float, float] | None]] = {}
        visible_bodies = tuple(body for body in bodies[:4] if body.presence >= 0.01)
        thermal_leader = max(
            (body for body in visible_bodies if body.thermal_active),
            key=lambda body: body.thermal_heat * 0.68 + clamp(body.z) * 0.32,
            default=None,
        )
        for body in visible_bodies:
            radius = max(0.035, body.radius)
            depth_scale = 0.78 + clamp(body.z) * 0.36
            # The same forces that move the body also alter its projected
            # volume. Keep the response within the idle bounds so music does
            # not turn a stronger visual into a larger sampling workload.
            # The core is the organism's persistent mass. It may breathe a
            # little through its own physics, but loudness alone cannot turn
            # it into a different blob; sharp events get their own lobe.
            core_stretch_x = clamp(body.stretch_x, 0.92, 1.08)
            core_stretch_y = clamp(body.stretch_y, 0.92, 1.08)
            squeeze = 0.78 + abs(math.cos(body.yaw)) * 0.22
            a = (
                radius
                * axis_x
                * core_stretch_x
                * depth_scale
                * squeeze
                * body.character.volume_width
            )
            b = (
                radius
                * axis_y
                * core_stretch_y
                * depth_scale
                * body.character.volume_height
            )
            center_x = body.x * max(1, width - 1)
            center_y = body.y * max(1, height - 1)
            extent_x = int(math.ceil((a * 1.65) * width + 2))
            extent_y = int(math.ceil((b * 1.65) * height + 2))
            projection = self._projection_for(
                body,
                a,
                b,
                forces,
                thermal_leader=body is thermal_leader,
            )
            left = max(0, int(center_x) - extent_x)
            right = min(width - 1, int(center_x) + extent_x)
            top = max(0, int(center_y) - extent_y)
            bottom = min(height - 1, int(center_y) + extent_y)
            for y in range(top, bottom + 1):
                for x in range(left, right + 1):
                    key = (y, x)
                    samples = buffer.setdefault(key, [None] * len(self._SAMPLES))
                    for offset_x, offset_y, slot, _ in self._SAMPLES:
                        hit = self._surface_at(
                            projection,
                            (x + offset_x) / max(1, width - 1),
                            (y + offset_y) / max(1, height - 1),
                        )
                        if hit is None:
                            continue
                        previous = samples[slot]
                        if previous is None or hit[0] > previous[0]:
                            samples[slot] = hit

        rows: dict[int, tuple[MaterialSpan, ...]] = {}
        for y in range(height):
            spans: list[MaterialSpan] = []
            run_start = 0
            run: list[MaterialCell] = []
            for x in range(width):
                samples = buffer.get((y, x))
                if samples is None or not any(samples):
                    if run:
                        spans.append(MaterialSpan(run_start, tuple(run)))
                        run = []
                    continue
                mask = sum(
                    quadrant_bit
                    for sample, (_, _, _, quadrant_bit) in zip(samples, self._SAMPLES)
                    if sample is not None
                )
                visible = [sample for sample in samples if sample is not None]
                assert visible
                shade = clamp(sum(sample[2] for sample in visible) / len(visible))
                attention = clamp(max(sample[3] for sample in visible))
                face = sum(sample[1] for sample in visible) / len(visible)
                if style.edge == "defined":
                    # A partial quadrant cell is the terminal equivalent of
                    # a contour pixel.  Lift only those boundary fragments so
                    # the 2x2 solid surface reads sharper without adding
                    # samples, a screen pass, or dot/Braille glyphs.
                    edge_fraction = 1.0 - len(visible) / len(self._SAMPLES)
                    shade = clamp(shade + edge_fraction * 0.14)
                if not run:
                    run_start = x
                run.append(MaterialCell(_QUADRANT_GLYPHS[mask], shade, attention, face))
            if run:
                spans.append(MaterialSpan(run_start, tuple(run)))
            if spans:
                rows[y] = tuple(spans)
        return rows

    @staticmethod
    def _projection_for(
        body: Body,
        axis_x: float,
        axis_y: float,
        forces: AudioForces,
        *,
        thermal_leader: bool = False,
    ) -> _VolumeProjection:
        """Prepare the two fixed surfaces once instead of once per dot."""

        cosine = math.cos(body.roll)
        sine = math.sin(body.roll)
        organic_cosine = math.cos(body.phase * 1.19)
        organic_sine = math.sin(body.phase * 1.19)
        # Volume treats a raw hit as a bounded ripple. A persistent thermal
        # bridge gets priority and turns the existing lobe toward its neighbor.
        if body.thermal_active:
            spike = clamp(
                body.spike * 0.78 + forces.transient * 0.34 + forces.pulse * 0.14
            )
        else:
            spike = clamp(body.spike + forces.transient * 0.65 + forces.pulse * 0.25)
        bridge = clamp(body.bridge_strength * (0.42 + body.thermal_heat * 0.58))
        spike_distance = 0.42 if body.thermal_active else 0.68
        spike_scale = 0.14 if body.thermal_active else 0.24
        spike_depth = 0.012 if body.thermal_active else 0.025
        spike_radius = 0.012 if body.thermal_active else 0.018
        lobe_heading = body.yaw + math.sin(body.impact_angle - body.yaw) * spike
        lobe_heading += math.sin(body.bridge_angle - lobe_heading) * bridge * 0.86
        lobe_cosine = math.cos(lobe_heading)
        lobe_sine = math.sin(lobe_heading)
        lobe_distance = axis_x * (
            body.character.volume_lobe_offset
            - forces.bass * 0.05
            + spike * spike_distance
            - bridge * 0.20
        )
        lobe_scale = (
            body.character.volume_lobe_size * (1.0 + spike * spike_scale + bridge * 0.50)
        )
        return _VolumeProjection(
            body=body,
            cosine=cosine,
            sine=sine,
            lobe_cosine=lobe_cosine,
            lobe_sine=lobe_sine,
            organic_cosine=organic_cosine,
            organic_sine=organic_sine,
            main=(
                body.x,
                body.y,
                body.z,
                axis_x,
                axis_y,
                0.15,
                body.character.volume_core_shape,
            ),
            lobe=(
                body.x + lobe_cosine * lobe_distance,
                body.y + lobe_sine * lobe_distance,
                body.z + math.cos(lobe_heading) * 0.13 + spike * spike_depth,
                axis_x * lobe_scale,
                axis_y * lobe_scale,
                0.09 + spike * spike_radius + bridge * 0.008,
                (
                    "bridge"
                    if bridge >= 0.12
                    else "spike"
                    if spike >= 0.12
                    else body.character.volume_lobe_shape
                ),
            ),
            impact_x=body.x + math.cos(body.impact_angle) * axis_x * 0.72,
            impact_y=body.y + math.sin(body.impact_angle) * axis_y * 0.72,
            thermal_leader=thermal_leader,
        )

    @staticmethod
    def _surface_at(
        projection: _VolumeProjection,
        sample_x: float,
        sample_y: float,
    ) -> tuple[float, float, float, float] | None:
        """Intersect a sample with a rotated ellipsoid plus an offset lobe."""

        body = projection.body

        def ellipsoid(
            surface: tuple[float, float, float, float, float, float, str],
            cosine: float,
            sine: float,
        ) -> tuple[float, float, float] | None:
            center_x, center_y, center_z, radius_x, radius_y, radius_z, shape = surface
            dx = sample_x - center_x
            dy = sample_y - center_y
            local_x = cosine * dx + sine * dy
            local_y = -sine * dx + cosine * dy
            nx = local_x / radius_x
            ny = local_y / radius_y
            if shape == "organic":
                # A soft, persistent shoulder plus two low-order harmonic
                # lobes makes a living contour. These are polynomial terms,
                # not a scalar-field pass or a variable tessellation budget.
                organic_x = projection.organic_cosine * nx - projection.organic_sine * ny
                organic_y = projection.organic_sine * nx + projection.organic_cosine * ny
                two_lobe = 2.0 * organic_x * organic_y
                three_lobe = organic_x * (
                    organic_x * organic_x - 3.0 * organic_y * organic_y
                )
                contour_scale = clamp(1.0 + two_lobe * 0.055 + three_lobe * 0.040, 0.88, 1.12)
                radius2 = max(
                    0.0,
                    (nx * nx + ny * ny) / (contour_scale * contour_scale)
                    + nx * (1.0 - min(1.0, abs(ny))) * 0.10,
                )
            elif shape == "spike":
                # This is not a new surface. It turns the existing lobe into
                # a bounded tip aligned with the body that actually heard a
                # hit, preserving the core instead of inflating the blob.
                radius2 = nx * nx + ny * ny + max(0.0, nx) * 0.58
            elif shape == "bridge":
                # A low, broad extension reaches toward the nearby body. It
                # remains the same lobe surface and fixed samples as before.
                radius2 = (nx / 1.34) ** 2 + (ny / 0.80) ** 2 + max(0.0, nx) * 0.06
            else:
                radius2 = nx * nx + ny * ny
            if radius2 > 1.0:
                return None
            nz = math.sqrt(1.0 - radius2)
            depth = center_z + nz * radius_z
            light = nx * math.sin(body.yaw) + ny * math.cos(body.pitch) * 0.38 + nz * 0.70
            return depth, clamp(0.5 + light / 2.54), nz

        main = ellipsoid(projection.main, projection.cosine, projection.sine)
        # The prepared lobe moves from the visible front through the body and
        # behind it over a yaw cycle, making a flip observable at dot scale.
        lobe = ellipsoid(
            projection.lobe, projection.lobe_cosine, projection.lobe_sine
        )
        surface = max((candidate for candidate in (main, lobe) if candidate is not None), default=None)
        if surface is None:
            return None
        depth, face, normal_z = surface
        core_visible = main is not None and (lobe is None or main[0] >= lobe[0])
        attention = max(body.afterglow, body.spike * 0.55) * math.exp(
            -(((sample_x - projection.impact_x) / max(0.012, projection.main[3] * 0.42)) ** 2
              + ((sample_y - projection.impact_y) / max(0.012, projection.main[4] * 0.42)) ** 2)
            * 1.8
        )
        # The main body keeps a quiet shade advantage over its moving lobe.
        # That makes a recognizable core survive loud passages without adding
        # another surface, cell pass, or palette state.
        core_lift = 0.055 if core_visible else -0.018
        thermal_lead = body.thermal_heat * 0.012 if body.thermal_active else 0.0
        if projection.thermal_leader:
            thermal_lead += body.thermal_heat * (0.028 + body.z * 0.018)
        if body.thermal_active:
            # Heat biases only ordinary surface colors and body luminance. The
            # final palette step is still reserved for attention in app.py.
            face = clamp(face + (body.thermal_heat - 0.50) * 0.10)
        shade = clamp(
            0.32 + normal_z * 0.36 + body.z * 0.16 + attention * 0.12 + core_lift + thermal_lead
        )
        return depth, face, shade, attention


class WaxMaterial:
    """Sparse terminal projection of a fixed-size continuous wax vessel."""

    name = "wax"
    _SAMPLES = (
        (-0.26, -0.28, 0x01),
        (0.26, -0.28, 0x02),
        (-0.26, 0.28, 0x04),
        (0.26, 0.28, 0x08),
    )

    @staticmethod
    def _components(state: WaxState) -> tuple[tuple[float, float, float, float, float], ...]:
        """Reduce fixed wax topology to softly irregular renderable masses."""

        threshold = 0.16
        seen: set[int] = set()
        components = []
        for index, density in enumerate(state.density):
            if density < threshold or index in seen:
                continue
            pending = [index]
            seen.add(index)
            cells = []
            while pending:
                current = pending.pop()
                x = current % WAX_WIDTH
                y = current // WAX_WIDTH
                value = state.density[current]
                cells.append((x, y, value))
                for neighbor in (
                    current - 1 if x else -1,
                    current + 1 if x < WAX_WIDTH - 1 else -1,
                    current - WAX_WIDTH if y else -1,
                    current + WAX_WIDTH if y < WAX_HEIGHT - 1 else -1,
                ):
                    if (
                        neighbor >= 0
                        and neighbor not in seen
                        and state.density[neighbor] >= threshold
                    ):
                        seen.add(neighbor)
                        pending.append(neighbor)
            mass = sum(value for _, _, value in cells)
            if mass < 1.2:
                continue
            center_x = sum((x + 0.5) * value for x, _, value in cells) / mass / WAX_WIDTH
            center_y = sum((y + 0.5) * value for _, y, value in cells) / mass / WAX_HEIGHT
            # Mass supplies the stable body size; phase contributes a tiny,
            # persistent asymmetry so wax reads organic rather than geometric.
            radius = math.sqrt(mass / (WAX_WIDTH * WAX_HEIGHT * math.pi)) * 1.52
            organic = math.sin(state.phase * 1.7 + center_x * 9.0 + center_y * 5.0) * 0.075
            components.append(
                (
                    center_x,
                    center_y,
                    radius * (1.0 + organic),
                    radius * (1.0 - organic * 0.72),
                    mass,
                )
            )
        return tuple(components)

    def render(
        self,
        state: WaxState,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> list[list[MaterialCell]]:
        width = max(1, width)
        height = max(1, height)
        empty = MaterialCell(" ", 0.0, 0.0)
        rows = [[empty] * width for _ in range(height)]
        for y, spans in self.render_spans(
            state, width, height, style, phase, cell_aspect
        ).items():
            for span in spans:
                rows[y][span.start : span.start + len(span.cells)] = span.cells
        return rows

    def render_spans(
        self,
        state: WaxState,
        width: int,
        height: int,
        style: MaterialStyle,
        phase: float,
        cell_aspect: float,
    ) -> dict[int, tuple[MaterialSpan, ...]]:
        del phase  # State already holds the fixed physical phase.
        width = max(1, width)
        height = max(1, height)
        components = self._components(state)
        if not components:
            return {}
        # Wax lives in a square physical lattice; a terminal cell is much
        # wider than it is tall. Project through that aspect so a round wax
        # mass remains round on screen instead of becoming a wide mountain.
        # A square physical correction makes the simulated mass too tiny in
        # a text grid. A square-root correction keeps it visibly round while
        # retaining enough terminal area for an organic silhouette.
        projection_x = clamp(
            math.sqrt(width * cell_aspect / max(1, height)), 1.0, 4.0
        )
        state_left = min(center_x - radius_x for center_x, _, radius_x, _, _ in components)
        state_right = max(center_x + radius_x for center_x, _, radius_x, _, _ in components)
        state_top = min(center_y - radius_y for _, center_y, _, radius_y, _ in components)
        state_bottom = max(center_y + radius_y for _, center_y, _, radius_y, _ in components)
        projected_left = 0.5 + (state_left - 0.5) / projection_x
        projected_right = 0.5 + (state_right - 0.5) / projection_x
        left = max(0, int(projected_left * width) - 1)
        right = min(width - 1, int(math.ceil(projected_right * width)) + 1)
        top = max(0, int(state_top * height) - 1)
        bottom = min(height - 1, int(math.ceil(state_bottom * height)) + 1)
        rows: dict[int, tuple[MaterialSpan, ...]] = {}
        for y in range(top, bottom + 1):
            spans: list[MaterialSpan] = []
            run_start = 0
            run: list[MaterialCell] = []
            for x in range(left, right + 1):
                mask = 0
                occupied: list[tuple[float, float, float, float]] = []
                for offset_x, offset_y, bit in self._SAMPLES:
                    screen_x = (x + offset_x) / max(1, width - 1)
                    sample_x = 0.5 + (screen_x - 0.5) * projection_x
                    sample_y = (y + offset_y) / max(1, height - 1)
                    if not 0.0 <= sample_x <= 1.0:
                        continue
                    density = 0.0
                    gradient_x = 0.0
                    gradient_y = 0.0
                    for center_x, center_y, radius_x, radius_y, _ in components:
                        local_x = (sample_x - center_x) / max(0.001, radius_x)
                        local_y = (sample_y - center_y) / max(0.001, radius_y)
                        distance = math.hypot(local_x, local_y)
                        if distance >= 1.0:
                            continue
                        component_density = (1.0 - distance) ** 0.42
                        if component_density > density:
                            density = component_density
                            gradient_x = -local_x
                            gradient_y = -local_y
                    if density < 0.34:
                        continue
                    heat = state.heat_at(sample_x, sample_y)
                    disturbance = state.impulse * math.exp(
                        -(
                            (sample_x - state.impulse_x) ** 2
                            + (sample_y - state.impulse_y) ** 2
                        )
                        / 0.018
                    )
                    mask |= bit
                    occupied.append((density, heat, gradient_x - gradient_y * 0.55, disturbance))
                if not mask:
                    if run:
                        spans.append(MaterialSpan(run_start, tuple(run)))
                        run = []
                    continue
                density = sum(sample[0] for sample in occupied) / len(occupied)
                heat = sum(sample[1] for sample in occupied) / len(occupied)
                gradient = sum(sample[2] for sample in occupied) / len(occupied)
                attention = clamp(max(sample[3] for sample in occupied))
                face = clamp(0.50 + gradient * 1.8 + heat * 0.12)
                shade = clamp(0.30 + density * 0.38 + heat * 0.24 + attention * 0.10)
                if style.edge == "defined" and mask != 0x0F:
                    shade = clamp(shade + (1.0 - mask.bit_count() / 4.0) * 0.12)
                if not run:
                    run_start = x
                run.append(MaterialCell(_QUADRANT_GLYPHS[mask], shade, attention, face))
            if run:
                spans.append(MaterialSpan(run_start, tuple(run)))
            if spans:
                rows[y] = tuple(spans)
        return rows


TEXT_MATERIAL = TextMaterial()
FLUID_MATERIAL = FluidMaterial()
VOLUME_MATERIAL = VolumeMaterial()
WAX_MATERIAL = WaxMaterial()


def material_for(
    name: str, *, unicode_supported: bool = True
) -> TextMaterial | FluidMaterial | VolumeMaterial | WaxMaterial:
    if name == "wax" and unicode_supported:
        return WAX_MATERIAL
    if name == "volume" and unicode_supported:
        return VOLUME_MATERIAL
    if name == "fluid" and unicode_supported:
        return FLUID_MATERIAL
    return TEXT_MATERIAL


def _inside_intervals(intervals: list[tuple[float, float]], position: float) -> bool:
    return any(left <= position <= right for left, right in intervals)


def _sample_row(row: list[float], x: int, width: int) -> float:
    if not row:
        return 0.0
    position = x * (len(row) - 1) / max(1, width - 1)
    left = int(position)
    right = min(len(row) - 1, left + 1)
    mix = position - left
    return row[left] * (1.0 - mix) + row[right] * mix


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[tuple[float, float]] = []
    for left, right in sorted(intervals):
        if not merged or left > merged[-1][1] + 0.35:
            merged.append((left, right))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], right))
    return merged
