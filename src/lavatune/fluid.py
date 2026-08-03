"""Analytic, sparse terminal contours for Lavatune's Fluid material."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .material_core import (
    _AFTERGLOW_GAIN,
    _FLUID_OCCUPANCY,
    _QUADRANT_GLYPHS,
    _WEIGHT_GAIN,
    MaterialCell,
    MaterialSpan,
    MaterialStyle,
    _grid_gradient,
    _semantic_sample,
    visual_shade,
)
from .organism import Body, FieldFrame, tile_axis_scales
from .signals import AudioForces, clamp


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
