"""Pure mappings from semantic organism fields to terminal cells."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from .organism import FieldFrame, clamp


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
