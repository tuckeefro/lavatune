from __future__ import annotations

import unittest

from lavatune.materials import (
    FLUID_MATERIAL,
    TEXT_MATERIAL,
    MaterialStyle,
    material_for,
    normalize_glyph_ramp,
)
from lavatune.organism import FieldFrame


def frame(
    mass: list[list[float]],
    surface: list[list[float]] | None = None,
    attention: list[list[float]] | None = None,
) -> FieldFrame:
    height = len(mass)
    width = len(mass[0])
    return FieldFrame(
        mass=mass,
        surface=surface or [[0.0] * width for _ in range(height)],
        attention=attention or [[0.0] * width for _ in range(height)],
    )


class GlyphRampTests(unittest.TestCase):
    def test_custom_ramp_rejects_controls_combining_and_wide_characters(self) -> None:
        ramp = normalize_glyph_ramp(".:\x1b\u0301界#")

        self.assertEqual(ramp, " .:#")

    def test_invalid_ramp_falls_back_to_canonical_text_material(self) -> None:
        self.assertEqual(normalize_glyph_ramp("   "), " .,:;~oO@")


class MaterialTests(unittest.TestCase):
    def test_text_material_uses_the_authored_glyph_ramp(self) -> None:
        semantic = frame([[0.0, 0.35, 0.72]])
        style = MaterialStyle(glyphs=" .x@")

        cells = [TEXT_MATERIAL.cell(semantic, x, 0, 3, 1, style, 0.0) for x in range(3)]

        self.assertEqual(cells[0].glyph, " ")
        self.assertTrue(all(cell.glyph in style.glyphs for cell in cells))
        self.assertNotEqual(cells[1].glyph, cells[2].glyph)

    def test_fluid_material_reserves_solid_cells_for_the_core(self) -> None:
        upper = frame([[0.45] * 3, [0.15] * 3, [0.0] * 3])
        lower = frame([[0.0] * 3, [0.15] * 3, [0.45] * 3])
        full = frame([[1.0] * 3] * 3)
        style = MaterialStyle()

        self.assertEqual(FLUID_MATERIAL.cell(upper, 1, 1, 3, 3, style, 0.0).glyph, "▀")
        self.assertEqual(FLUID_MATERIAL.cell(lower, 1, 1, 3, 3, style, 0.0).glyph, "▄")
        self.assertEqual(FLUID_MATERIAL.cell(full, 1, 1, 3, 3, style, 0.0).glyph, "█")

    def test_fluid_edges_use_less_than_a_full_terminal_cell(self) -> None:
        corner = frame(
            [
                [1.0, 1.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ]
        )

        cell = FLUID_MATERIAL.cell(corner, 1, 1, 3, 3, MaterialStyle(), 0.0)

        self.assertIn(cell.glyph, "▘▝▖▗▀▄▌▐▞▚▛▜▙▟")
        self.assertNotEqual(cell.glyph, "█")

    def test_semantic_controls_have_orthogonal_visual_effects(self) -> None:
        mass = frame([[0.34]])
        surface = frame([[0.0]], surface=[[0.8]])
        glow = frame([[0.0]], attention=[[0.8]])

        airy = TEXT_MATERIAL.cell(
            mass, 0, 0, 1, 1, MaterialStyle(weight="airy"), 0.0
        )
        full = TEXT_MATERIAL.cell(
            mass, 0, 0, 1, 1, MaterialStyle(weight="full"), 0.0
        )
        soft = TEXT_MATERIAL.cell(
            surface, 0, 0, 1, 1, MaterialStyle(edge="soft"), 0.0
        )
        defined = TEXT_MATERIAL.cell(
            surface, 0, 0, 1, 1, MaterialStyle(edge="defined"), 0.0
        )
        quiet = TEXT_MATERIAL.cell(
            glow, 0, 0, 1, 1, MaterialStyle(afterglow="quiet"), 0.0
        )
        present = TEXT_MATERIAL.cell(
            glow, 0, 0, 1, 1, MaterialStyle(afterglow="present"), 0.0
        )

        self.assertGreater(full.shade, airy.shade)
        self.assertGreater(defined.shade, soft.shade)
        self.assertGreater(present.shade, quiet.shade)

    def test_fluid_material_falls_back_to_text_without_unicode(self) -> None:
        self.assertIs(material_for("fluid", unicode_supported=False), TEXT_MATERIAL)
        self.assertIs(material_for("fluid", unicode_supported=True), FLUID_MATERIAL)


if __name__ == "__main__":
    unittest.main()
