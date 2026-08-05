from __future__ import annotations

import math
import unittest

from lavatune.fluid import FluidMaterial as ExtractedFluidMaterial
from lavatune.materials import (
    FLUID_MATERIAL,
    FluidMaterial,
    TEXT_MATERIAL,
    VOLUME_MATERIAL,
    WAX_MATERIAL,
    MaterialStyle,
    material_for,
    normalize_glyph_ramp,
)
from lavatune.organism import AcousticOrganism, AudioForces, FieldFrame, NarrativeState
from lavatune.volume import VolumeMaterial as ExtractedVolumeMaterial
from lavatune.wax import WaxState


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
    def test_materials_facade_reexports_the_extracted_renderers(self) -> None:
        self.assertIs(FluidMaterial, ExtractedFluidMaterial)
        self.assertIs(type(VOLUME_MATERIAL), ExtractedVolumeMaterial)

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
        self.assertIs(material_for("volume", unicode_supported=False), TEXT_MATERIAL)
        self.assertIs(material_for("volume", unicode_supported=True), VOLUME_MATERIAL)
        self.assertIs(material_for("wax", unicode_supported=False), TEXT_MATERIAL)
        self.assertIs(material_for("wax", unicode_supported=True), WAX_MATERIAL)

    def test_wax_material_renders_fixed_density_as_solid_quadrant_wax(self) -> None:
        state = WaxState()
        rows = WAX_MATERIAL.render(
            state, 64, 20, MaterialStyle(edge="defined"), 0.0, 1.85
        )
        glyphs = [cell.glyph for row in rows for cell in row if cell.glyph != " "]

        self.assertTrue(glyphs)
        self.assertTrue(all(glyph in "▘▝▀▖▌▞▛▗▚▐▜▄▙▟█" for glyph in glyphs))
        self.assertIn("█", glyphs)

    def test_wax_connected_mass_projects_as_a_round_body_not_a_density_wedge(self) -> None:
        state = WaxState()
        for _ in range(60):
            state.advance(
                1.0 / 12.0,
                AudioForces(bass=0.95, energy=0.85, tempo=0.50, bands=(0.70,) * 8),
                NarrativeState(held_pressure=0.90, cadence=0.70),
                "music",
            )
        rows = WAX_MATERIAL.render(
            state, 80, 24, MaterialStyle(edge="defined"), 0.0, 1.85
        )
        occupied = [
            (x, y)
            for y, row in enumerate(rows)
            for x, cell in enumerate(row)
            if cell.glyph != " "
        ]
        width = max(x for x, _ in occupied) - min(x for x, _ in occupied) + 1
        height = max(y for _, y in occupied) - min(y for _, y in occupied) + 1

        self.assertGreaterEqual(width, 7)
        self.assertGreaterEqual(height, 6)
        self.assertLess(width, height * 2)
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

    def test_contour_fluid_carries_a_hit_as_a_bounded_travelling_surface_wave(self) -> None:
        renderer = FluidMaterial()
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.24
        body.presence = 1.0
        body.surface_ripples_active = True
        body.surface_ripple = 0.92
        body.surface_ripple_angle = 0.0

        first = renderer.render([body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85)
        body.surface_ripple_phase = 1.25
        second = renderer.render([body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85)

        first_shape = [[cell.glyph != " " for cell in row] for row in first]
        second_shape = [[cell.glyph != " " for cell in row] for row in second]
        changed = sum(
            before != after
            for first_row, second_row in zip(first_shape, second_shape)
            for before, after in zip(first_row, second_row)
        )
        first_area = sum(map(sum, first_shape))
        second_area = sum(map(sum, second_shape))

        self.assertGreater(changed, 3)
        self.assertLess(abs(second_area - first_area), first_area * 0.28)
        for rows in (first, second):
            for row in rows:
                occupied = [x for x, cell in enumerate(row) if cell.glyph != " "]
                if occupied:
                    self.assertEqual(occupied, list(range(min(occupied), max(occupied) + 1)))

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

    def test_contour_fluid_expands_and_contracts_with_shape_pulse(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.18
        body.presence = 1.0

        quiet = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )
        body.shape_pulse = 0.92
        expanded = FLUID_MATERIAL.render(
            [body], AudioForces(), 60, 18, MaterialStyle(), 0.0, 1.85
        )

        quiet_area = sum(cell.glyph != " " for row in quiet for cell in row)
        expanded_area = sum(cell.glyph != " " for row in expanded for cell in row)
        self.assertGreater(expanded_area, quiet_area)

    def test_contour_depth_projects_near_bodies_larger_and_brighter(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.18
        body.presence = 1.0

        body.z = 0.08
        distant = FLUID_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        body.z = 0.92
        near = FLUID_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )

        distant_cells = [cell for row in distant for cell in row if cell.glyph != " "]
        near_cells = [cell for row in near for cell in row if cell.glyph != " "]

        self.assertGreater(len(near_cells), len(distant_cells))
        self.assertGreater(
            sum(cell.shade for cell in near_cells) / len(near_cells),
            sum(cell.shade for cell in distant_cells) / len(distant_cells),
        )

    def test_contour_spin_changes_its_outline_and_surface_faces(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.radius = 0.20
        body.presence = 1.0
        forces = AudioForces(tempo=0.60, voice=0.50)

        first = FLUID_MATERIAL.render([body], forces, 64, 20, MaterialStyle(), 0.10, 1.85)
        later = FLUID_MATERIAL.render([body], forces, 64, 20, MaterialStyle(), 1.80, 1.85)

        first_shape = [[cell.glyph != " " for cell in row] for row in first]
        later_shape = [[cell.glyph != " " for cell in row] for row in later]
        changed = sum(
            before != after
            for first_row, later_row in zip(first_shape, later_shape)
            for before, after in zip(first_row, later_row)
        )
        faces = [cell.face for row in first for cell in row if cell.face is not None]

        self.assertGreater(changed, 20)
        self.assertGreater(max(faces) - min(faces), 0.30)

    def test_volume_flip_moves_an_asymmetric_lobe_behind_the_main_body(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.22
        body.presence = 1.0
        body.roll = 0.0
        body.pitch = 0.0

        body.yaw = 0.0
        front = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        body.yaw = math.pi
        flipped = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )

        front_shape = [[cell.glyph != " " for cell in row] for row in front]
        flipped_shape = [[cell.glyph != " " for cell in row] for row in flipped]
        changed = sum(
            before != after
            for first_row, second_row in zip(front_shape, flipped_shape)
            for before, after in zip(first_row, second_row)
        )
        faces = [cell.face for row in front for cell in row if cell.face is not None]

        self.assertGreater(changed, 8)
        self.assertGreater(max(faces) - min(faces), 0.20)

    def test_volume_music_forces_change_the_projected_shape(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        body.yaw = 0.65

        quiet = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        loud = VOLUME_MATERIAL.render(
            [body],
            AudioForces(bass=0.88, energy=0.82, transient=0.90, pulse=0.78),
            64,
            20,
            MaterialStyle(),
            0.0,
            1.85,
        )

        quiet_shape = [[cell.glyph != " " for cell in row] for row in quiet]
        loud_shape = [[cell.glyph != " " for cell in row] for row in loud]
        changed = sum(
            before != after
            for quiet_row, loud_row in zip(quiet_shape, loud_shape)
            for before, after in zip(quiet_row, loud_row)
        )

        self.assertGreater(changed, 10)

    def test_volume_spike_aims_the_existing_lobe_in_the_impact_direction(self) -> None:
        def bounds(impact_angle: float) -> tuple[int, int, int, int]:
            organism = AcousticOrganism(body_limit=1)
            body = organism.bodies[0]
            body.x = 0.5
            body.y = 0.5
            body.z = 0.50
            body.radius = 0.20
            body.presence = 1.0
            body.yaw = 0.45
            body.roll = 0.10
            body.spike = 0.92
            body.impact_angle = impact_angle
            rows = VOLUME_MATERIAL.render(
                [body],
                AudioForces(transient=0.88, pulse=0.72),
                64,
                20,
                MaterialStyle(),
                0.0,
                1.85,
            )
            occupied = [
                (x, y)
                for y, row in enumerate(rows)
                for x, cell in enumerate(row)
                if cell.glyph != " "
            ]
            return (
                min(x for x, _ in occupied),
                max(x for x, _ in occupied),
                min(y for _, y in occupied),
                max(y for _, y in occupied),
            )

        right = bounds(0.0)
        down = bounds(math.pi / 2.0)

        self.assertGreater(right[1], down[1])
        self.assertGreater(down[3], right[3])

    def test_volume_organic_contour_has_stable_individual_asymmetry(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        body.yaw = 0.55
        body.pitch = 0.14
        body.roll = 0.15

        body.phase = 0.0
        first = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        body.phase = 1.4
        second = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        changed = sum(
            left.glyph != right.glyph
            for first_row, second_row in zip(first, second)
            for left, right in zip(first_row, second_row)
        )
        first_area = sum(cell.glyph != " " for row in first for cell in row)
        second_area = sum(cell.glyph != " " for row in second for cell in row)

        self.assertGreater(changed, 20)
        self.assertLess(abs(second_area - first_area), first_area * 0.16)

    def test_volume_keeps_the_first_four_organisms_visually_distinct(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        silhouettes = []
        for body in organism.bodies[:4]:
            body.x = 0.5
            body.y = 0.5
            body.z = 0.50
            body.radius = 0.20
            body.presence = 1.0
            body.yaw = 0.58
            body.pitch = 0.14
            body.roll = 0.0
            rows = VOLUME_MATERIAL.render(
                [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
            )
            silhouettes.append(tuple(cell.glyph != " " for row in rows for cell in row))

        self.assertEqual(len(set(silhouettes)), 4)

    def test_volume_roles_keep_iconic_core_proportions(self) -> None:
        organism = AcousticOrganism(body_limit=4)

        def extent(body) -> tuple[int, int, int]:
            body.x = 0.5
            body.y = 0.5
            body.z = 0.50
            body.radius = 0.20
            body.presence = 1.0
            body.yaw = 0.55
            body.pitch = 0.14
            body.roll = 0.15
            rows = VOLUME_MATERIAL.render(
                [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
            )
            occupied = [
                (x, y)
                for y, row in enumerate(rows)
                for x, cell in enumerate(row)
                if cell.glyph != " "
            ]
            return (
                max(x for x, _ in occupied) - min(x for x, _ in occupied) + 1,
                max(y for _, y in occupied) - min(y for _, y in occupied) + 1,
                len(occupied),
            )

        ballast, listener, glint, drifter = [extent(body) for body in organism.bodies[:4]]

        self.assertGreater(ballast[0], listener[0])  # broad, heavy soft core
        self.assertGreater(listener[1], ballast[1])  # upright, listening soft body
        self.assertLess(glint[2], drifter[2])  # compact bud against round body

    def test_volume_keeps_solid_quadrant_cells_for_fluid_mass(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        rows = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        glyphs = [cell.glyph for row in rows for cell in row if cell.glyph != " "]

        self.assertTrue(all(glyph in "▘▝▀▖▌▞▛▗▚▐▜▄▙▟█" for glyph in glyphs))
        self.assertIn("█", glyphs)

    def test_volume_defined_edge_sharpens_only_existing_quadrant_boundaries(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        soft = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(edge="soft"), 0.0, 1.85
        )
        defined = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(edge="defined"), 0.0, 1.85
        )
        soft_cells = [cell for row in soft for cell in row if cell.glyph != " "]
        defined_cells = [cell for row in defined for cell in row if cell.glyph != " "]
        soft_edges = [cell for cell in soft_cells if cell.glyph != "█"]
        defined_edges = [cell for cell in defined_cells if cell.glyph != "█"]
        soft_cores = [cell for cell in soft_cells if cell.glyph == "█"]
        defined_cores = [cell for cell in defined_cells if cell.glyph == "█"]

        self.assertEqual(
            [cell.glyph for cell in soft_cells], [cell.glyph for cell in defined_cells]
        )
        self.assertGreater(
            sum(cell.shade for cell in defined_edges) / len(defined_edges),
            sum(cell.shade for cell in soft_edges) / len(soft_edges),
        )
        self.assertEqual(
            [cell.shade for cell in soft_cores], [cell.shade for cell in defined_cores]
        )

    def test_volume_thermal_bridge_redirects_the_existing_lobe_without_new_glyphs(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        body.yaw = math.pi
        baseline = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )
        body.thermal_active = True
        body.thermal_heat = 0.85
        body.bridge_strength = 0.82
        body.bridge_angle = 0.0
        bridged = VOLUME_MATERIAL.render(
            [body], AudioForces(), 64, 20, MaterialStyle(), 0.0, 1.85
        )

        baseline_shape = [cell.glyph != " " for row in baseline for cell in row]
        bridged_shape = [cell.glyph != " " for row in bridged for cell in row]
        bridged_glyphs = [cell.glyph for row in bridged for cell in row if cell.glyph != " "]

        self.assertGreater(
            sum(left != right for left, right in zip(baseline_shape, bridged_shape)), 4
        )
        self.assertTrue(all(glyph in "▘▝▀▖▌▞▛▗▚▐▜▄▙▟█" for glyph in bridged_glyphs))

    def test_volume_warm_near_body_leads_without_spending_attention_color(self) -> None:
        organism = AcousticOrganism(body_limit=2)
        back, lead = organism.bodies[:2]
        for body, x in ((back, 0.28), (lead, 0.72)):
            body.x = x
            body.y = 0.50
            body.radius = 0.14
            body.presence = 1.0
            body.afterglow = 0.0
            body.spike = 0.0
            body.thermal_active = True
            body.phase = back.phase
            body.character = back.character
        back.z = 0.34
        back.thermal_heat = 0.48
        lead.z = 0.82
        lead.thermal_heat = 0.92

        rows = VOLUME_MATERIAL.render(
            [back, lead], AudioForces(), 80, 24, MaterialStyle(), 0.0, 1.85
        )
        left = [cell for row in rows for x, cell in enumerate(row) if x < 40 and cell.glyph != " "]
        right = [cell for row in rows for x, cell in enumerate(row) if x >= 40 and cell.glyph != " "]

        self.assertTrue(left and right)
        self.assertGreater(
            sum(cell.shade for cell in right) / len(right),
            sum(cell.shade for cell in left) / len(left) + 0.025,
        )
        self.assertTrue(all(cell.attention == 0.0 for row in rows for cell in row))

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
