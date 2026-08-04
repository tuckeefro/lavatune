"""Pure mappings from semantic organism fields to terminal cells."""

from __future__ import annotations

import math

from .organism import FieldFrame
from .material_core import (
    AFTERGLOW_NAMES,
    DEFAULT_GLYPHS,
    EDGE_NAMES,
    MATERIAL_NAMES,
    WEIGHT_NAMES,
    _AFTERGLOW_GAIN,
    _EDGE_GAIN,
    _QUADRANT_GLYPHS,
    _WEIGHT_GAIN,
    MaterialCell,
    MaterialSpan,
    MaterialStyle,
    _sample_row,
    _semantic_sample,
    normalize_glyph_ramp,
    visual_shade,
)
from .signals import clamp
from .wax import WAX_HEIGHT, WAX_WIDTH, WaxState

# These names remain public through the historical ``materials`` façade even
# though their implementation now lives in material_core.py or a material file.
__all__ = [
    "AFTERGLOW_NAMES",
    "DEFAULT_GLYPHS",
    "EDGE_NAMES",
    "MATERIAL_NAMES",
    "WEIGHT_NAMES",
    "MaterialCell",
    "MaterialSpan",
    "MaterialStyle",
    "normalize_glyph_ramp",
    "visual_shade",
    "TextMaterial",
    "WaxMaterial",
    "FluidMaterial",
    "VolumeMaterial",
    "TEXT_MATERIAL",
    "FLUID_MATERIAL",
    "VOLUME_MATERIAL",
    "WAX_MATERIAL",
    "material_for",
]


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

# Imported after shared cells, styles, and text/wax helpers are available.
# Re-exporting preserves the original materials module contract.
from .fluid import FluidMaterial
from .volume import VolumeMaterial


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
