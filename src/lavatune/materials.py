"""Pure mappings from semantic organism fields to terminal cells."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from .organism import AudioForces, Body, FieldFrame, clamp, tile_axis_scales


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


@dataclass(slots=True, frozen=True)
class MaterialSpan:
    start: int
    cells: tuple[MaterialCell, ...]


@dataclass(slots=True, frozen=True)
class _PreparedContour:
    center_x: float
    center_y: float
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


@dataclass(slots=True, frozen=True)
class MaterialStyle:
    glyphs: str = DEFAULT_GLYPHS
    weight: str = "balanced"
    edge: str = "soft"
    afterglow: str = "present"


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
                if _inside_intervals(upper, x - 0.24):
                    mask |= 1
                if _inside_intervals(upper, x + 0.24):
                    mask |= 2
                if _inside_intervals(lower, x - 0.24):
                    mask |= 4
                if _inside_intervals(lower, x + 0.24):
                    mask |= 8
                if not mask:
                    if run:
                        spans.append(MaterialSpan(run_start, tuple(run)))
                        run = []
                    continue
                attention = self._attention_at(
                    prepared,
                    x,
                    y,
                    width,
                    height,
                )
                attention = clamp(attention * (0.65 + glow_gain))
                coverage = mask.bit_count() / 4.0
                shade = clamp(
                    0.34
                    + coverage * 0.30
                    + forces.bass * 0.05
                    + forces.detail * edge_lift
                    + attention * 0.10
                )
                if not run:
                    run_start = x
                run.append(MaterialCell(_QUADRANT_GLYPHS[mask], shade, attention))
            if run:
                spans.append(MaterialSpan(run_start, tuple(run)))
            if spans:
                rows[y] = tuple(spans)
        self._span_cache_key = cache_key
        self._span_cache = rows
        return rows

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
                round(body.radius * min(width, height * cell_aspect) * 4),
                round(body.stretch_x * 16),
                round(body.stretch_y * 16),
                round(body.presence * 8),
                round(body.afterglow * 8),
                round(body.spike * 12),
                round(body.impact_angle * 6),
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
        for body in bodies:
            if body.presence < 0.01:
                continue
            radius = max(0.035, body.radius)
            local_band = forces.bands[body.band % len(forces.bands)] if forces.bands else 0.0
            local_hit = forces.hits[body.band % len(forces.hits)] if forces.hits else 0.0
            band_position = body.band / max(1, len(forces.bands) - 1)
            pitch_affinity = max(0.16, 1.0 - abs(band_position - forces.tone) * 1.7)
            breath = 1.0 + forces.bass * body.character.bass * 0.055 + local_band * 0.025
            radius_x = radius * axis_x * max(0.72, body.stretch_x) * breath
            radius_y = radius * axis_y * max(0.72, body.stretch_y) * breath
            active_extent = extent * math.sqrt(clamp(body.presence, 0.0, 1.0))
            detail_amplitude = (
                forces.detail
                * body.character.detail
                * body.character.deformation
                * (0.045 + forces.tone * 0.035)
                + local_band * pitch_affinity * body.character.deformation * 0.035
            )
            event = max(body.afterglow, local_hit)
            spike = body.spike
            impact_side = math.cos(body.impact_angle)
            impact_vertical = math.sin(body.impact_angle)
            attention_radius_x = max(0.012, body.radius * axis_x)
            attention_radius_y = max(0.012, body.radius * axis_y)
            prepared.append(
                _PreparedContour(
                    center_x=body.x * max(1, width - 1),
                    center_y=body.y,
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
                    pulse_amplitude=(
                        forces.pulse * (0.045 + pitch_affinity * 0.035)
                        + forces.rhythm_density
                        * body.character.detail
                        * (0.018 + pitch_affinity * 0.018)
                    ),
                    shear_gain=(
                        radius_x
                        * forces.voice
                        * body.character.voice
                        * body.character.deformation
                        * math.sin(body.phase + phase * (0.70 + forces.tempo * 0.55))
                        * 0.15
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
                    ),
                    attention_x=body.x + impact_side * attention_radius_x * 0.72,
                    attention_y=(
                        body.y + math.sin(body.impact_angle) * attention_radius_y * 0.72
                    ),
                    attention_scale_x=max(0.012, attention_radius_x * 0.42),
                    attention_scale_y=max(0.012, attention_radius_y * 0.42),
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
            dy = (normalized_y - body.center_y) / max(0.001, body.radius_y)
            vertical_extra = body.spike * abs(body.impact_vertical) * 0.32
            if abs(dy) >= body.active_extent + vertical_extra:
                continue
            if abs(dy) >= body.active_extent:
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
            ripple = 1.0 + math.sin(
                dy * body.detail_frequency + body.detail_phase
            ) * body.detail_amplitude
            ripple += math.sin(dy * 4.4 + body.pulse_phase) * body.pulse_amplitude
            half_width = body.radius_x * math.sqrt(
                body.active_extent * body.active_extent - dy * dy
            )
            half_width *= max(0.82, ripple)
            center = body.center_x + dy * body.shear_gain
            half = half_width * max(1, width - 1)
            left = center - half
            right = center + half

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


TEXT_MATERIAL = TextMaterial()
FLUID_MATERIAL = FluidMaterial()


def material_for(name: str, *, unicode_supported: bool = True) -> TextMaterial | FluidMaterial:
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
