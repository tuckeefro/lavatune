"""Fixed-work, depth-tested terminal projection for experimental Volume."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .material_core import _QUADRANT_GLYPHS, MaterialCell, MaterialSpan, MaterialStyle
from .organism import Body, tile_axis_scales
from .signals import AudioForces, clamp


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
            core_stretch_x = clamp(body.stretch_x, 0.84, 1.18)
            core_stretch_y = clamp(body.stretch_y, 0.84, 1.18)
            shape_breath = 1.0 + body.shape_pulse * (
                0.16 + body.character.deformation * 0.08
            )
            squeeze = 0.78 + abs(math.cos(body.yaw)) * 0.22
            a = (
                radius
                * axis_x
                * core_stretch_x
                * depth_scale
                * squeeze
                * shape_breath
                * body.character.volume_width
            )
            b = (
                radius
                * axis_y
                * core_stretch_y
                * depth_scale
                * shape_breath
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
