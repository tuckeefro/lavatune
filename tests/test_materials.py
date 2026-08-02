from __future__ import annotations

import math
import unittest

from lavatune.materials import (
    FLUID_MATERIAL,
    TEXT_MATERIAL,
    MaterialStyle,
    material_for,
    normalize_glyph_ramp,
)
from lavatune.organism import AcousticOrganism, AudioForces, FieldFrame


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

    def test_text_row_renderer_interpolates_without_repeating_source_columns(self) -> None:
        semantic = frame([[0.0, 1.0]])

        row = TEXT_MATERIAL.render(
            semantic, 5, 1, MaterialStyle(glyphs=" .xO@"), 0.0
        )[0]

        self.assertGreater(len({cell.glyph for cell in row}), 3)
        self.assertEqual(row[0].glyph, " ")
        self.assertEqual(row[-1].glyph, "@")

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

    def test_contour_fluid_keeps_each_row_connected_instead_of_cloudy(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.20
        body.presence = 1.0

        rows = FLUID_MATERIAL.render(
            [body], AudioForces(), 48, 16, MaterialStyle(), 0.0, 1.85
        )

        visible_rows = 0
        for row in rows:
            occupied = [index for index, cell in enumerate(row) if cell.glyph != " "]
            if not occupied:
                continue
            visible_rows += 1
            self.assertEqual(occupied, list(range(min(occupied), max(occupied) + 1)))
        self.assertGreater(visible_rows, 4)
        self.assertTrue(any(cell.glyph == "█" for row in rows for cell in row))
        self.assertTrue(any(cell.glyph not in {" ", "█"} for row in rows for cell in row))

    def test_contour_fluid_keeps_afterglow_local_to_the_impacted_edge(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.22
        body.presence = 1.0
        body.afterglow = 1.0
        body.impact_angle = 0.0

        rows = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )
        visible = [cell for row in rows for cell in row if cell.glyph != " "]
        attended = [cell for cell in visible if cell.attention >= 0.08]

        self.assertGreater(len(attended), 0)
        self.assertLess(len(attended), len(visible) * 0.20)

    def test_contour_fluid_turns_a_fast_change_into_a_local_spike(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.22
        body.presence = 1.0
        body.impact_angle = 0.0

        soft = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )
        body.spike = 1.0
        sharp = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )

        def right_edge(rows) -> int:
            return max(
                x
                for row in rows
                for x, cell in enumerate(row)
                if cell.glyph != " "
            )

        self.assertGreaterEqual(right_edge(sharp), right_edge(soft) + 3)

        body.spike = 0.0
        body.impact_angle = -math.pi / 2.0
        soft_vertical = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )
        body.spike = 1.0
        sharp_vertical = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )

        def top_edge(rows) -> int:
            return min(
                y
                for y, row in enumerate(rows)
                if any(cell.glyph != " " for cell in row)
            )

        self.assertLess(top_edge(sharp_vertical), top_edge(soft_vertical))

    def test_contour_fluid_uses_audio_to_reshape_instead_of_only_recolor(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.22
        body.presence = 1.0
        quiet = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 1.2, 1.85
        )
        music = FLUID_MATERIAL.render(
            [body],
            AudioForces(
                bass=0.65,
                voice=0.70,
                detail=0.72,
                energy=0.70,
                tone=0.68,
                tempo=0.55,
                pulse=0.48,
                bands=(0.30, 0.65, 0.46, 0.72, 0.55, 0.48, 0.78, 0.62),
            ),
            60,
            18,
            MaterialStyle(),
            1.2,
            1.85,
        )
        quiet_shape = [[cell.glyph != " " for cell in row] for row in quiet]
        music_shape = [[cell.glyph != " " for cell in row] for row in music]
        changed = sum(
            before != after
            for quiet_row, music_row in zip(quiet_shape, music_shape)
            for before, after in zip(quiet_row, music_row)
        )
        quiet_area = sum(value for row in quiet_shape for value in row)
        music_area = sum(value for row in music_shape for value in row)

        self.assertGreater(changed, 10)
        self.assertLess(music_area, quiet_area * 1.35)

    def test_contour_spans_are_sparse_cached_and_expand_to_the_snapshot_api(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.presence = 1.0
        style = MaterialStyle()

        spans = FLUID_MATERIAL.render_spans(
            [body], AudioForces(), 80, 24, style, 0.5, 1.85
        )
        cached = FLUID_MATERIAL.render_spans(
            [body], AudioForces(), 80, 24, style, 0.5, 1.85
        )
        expanded = FLUID_MATERIAL.render(
            [body], AudioForces(), 80, 24, style, 0.5, 1.85
        )

        self.assertIs(spans, cached)
        self.assertLess(len(spans), 24)
        self.assertTrue(
            all(cell.glyph != " " for row in spans.values() for span in row for cell in span.cells)
        )
        self.assertEqual(
            sum(len(span.cells) for row in spans.values() for span in row),
            sum(cell.glyph != " " for row in expanded for cell in row),
        )


if __name__ == "__main__":
    unittest.main()
