from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from lavatune.app import (
    LavaField,
    PRODUCT_PRESETS,
    UiState,
    _apply_product_preset,
    _interpolated_row_value,
    _make_controls,
    _product_preset_name_for_config,
    _scene_name_for_config,
    _semantic_color_bucket,
    _visual_shade,
)
from lavatune.audio import AudioFrame
from lavatune.config import LavaConfig, apply_cli_overrides, load_config
from lavatune.materials import FLUID_MATERIAL, MATERIAL_NAMES, MaterialStyle, material_for
from lavatune.organism import (
    CELL_ASPECT,
    AcousticOrganism,
    AffectiveState,
    AffectiveTracker,
    AudioForceMapper,
    AudioForces,
    circulation_at,
    compose_tile,
    habitat_anchor,
    measure_field,
    tile_axis_scales,
)


SILENCE = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 0.0)
SPEECH = AudioFrame(0.24, [0.12, 0.18, 0.42, 0.58, 0.38, 0.18, 0.09, 0.05], 0.07, 0.08, 0.0)
BASS = AudioFrame(0.48, [0.92, 0.78, 0.35, 0.16, 0.09, 0.05, 0.03, 0.02], 0.18, 0.05, 0.0)
MUSIC = AudioFrame(0.38, [0.55, 0.47, 0.33, 0.42, 0.38, 0.29, 0.22, 0.16], 0.26, 0.13, 0.0)
TRANSIENT = AudioFrame(0.72, [0.82, 0.72, 0.64, 0.58, 0.70, 0.80, 0.94, 0.88], 0.92, 0.24, 0.0)


def settle(field: LavaField, frame: AudioFrame, mode: str, frames: int = 90) -> None:
    config = LavaConfig(blobs=6)
    for _ in range(frames):
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)


class AudioForceTests(unittest.TestCase):
    def test_time_based_mapping_is_consistent_across_capture_cadences(self) -> None:
        def map_for(step: float) -> AudioForces:
            mapper = AudioForceMapper()
            output = AudioForces()
            timestamp = step
            while timestamp <= 2.0 + 0.0001:
                output = mapper.map(
                    AudioFrame(
                        0.42,
                        [0.72, 0.62, 0.32, 0.15, 0.08, 0.04, 0.02, 0.01],
                        0.0,
                        0.04,
                        timestamp,
                    ),
                    "music",
                    1.0,
                )
                timestamp += step
            return output

        fast = map_for(0.05)
        slow = map_for(0.10)

        self.assertAlmostEqual(fast.bass, slow.bass, delta=0.08)
        self.assertAlmostEqual(fast.voice, slow.voice, delta=0.08)
        self.assertAlmostEqual(fast.detail, slow.detail, delta=0.08)

    def test_affective_state_builds_tension_then_recognizes_release(self) -> None:
        tracker = AffectiveTracker()
        tense = AudioForces(
            bass=0.55,
            voice=0.62,
            detail=0.70,
            transient=0.28,
            energy=0.82,
            tempo=0.58,
            pulse=0.42,
            flux=0.34,
            bands=(0.55, 0.62, 0.48, 0.72, 0.64, 0.58, 0.76, 0.68),
            hits=(0.12,) * 8,
        )
        for index in range(70):
            built = tracker.update(tense, 1.0 + index * 0.10)

        released = tracker.update(AudioForces(), 8.1)

        self.assertGreater(built.tension, 0.45)
        self.assertGreater(built.agitation, 0.28)
        self.assertGreater(released.release, 0.45)
        self.assertGreater(released.tension, 0.20)

    def test_midwest_emo_arc_moves_from_fragile_yearning_to_catharsis(self) -> None:
        tracker = AffectiveTracker()
        verse = AudioForces(
            voice=0.58,
            detail=0.72,
            energy=0.40,
            tone=0.68,
            bands=(0.12, 0.16, 0.28, 0.48, 0.44, 0.62, 0.78, 0.66),
        )
        for index in range(60):
            held = tracker.update(verse, 1.0 + index * 0.10)

        breaking_open = tracker.update(
            AudioForces(
                bass=0.72,
                voice=0.66,
                detail=0.78,
                transient=0.92,
                energy=0.94,
                pulse=0.82,
                flux=0.70,
                tone=0.62,
                bands=(0.78, 0.74, 0.68, 0.72, 0.70, 0.82, 0.90, 0.84),
            ),
            7.1,
        )

        self.assertGreater(held.fragility, 0.38)
        self.assertGreater(held.yearning, 0.34)
        self.assertGreater(breaking_open.catharsis, 0.35)

    def test_reaction_latch_keeps_an_attack_until_a_draw_consumes_it(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        field.observe(
            AudioFrame(0.12, [0.12] * 8, 0.02, 0.08, 1.0),
            "music",
            1.0,
        )
        field.observe(
            AudioFrame(0.65, [0.75] * 8, 0.80, 0.18, 1.06),
            "music",
            1.0,
        )
        peak = field.reactions.transient
        field.observe(
            AudioFrame(0.08, [0.08] * 8, 0.0, 0.04, 1.12),
            "music",
            1.0,
        )

        field.step(
            AudioFrame(0.08, [0.08] * 8, 0.0, 0.04, 1.12),
            "music",
            "atlas",
            1.0,
            LavaConfig(),
            rasterize=False,
        )

        self.assertGreater(peak, 0.20)
        self.assertGreaterEqual(field.render_forces.transient, peak)
        self.assertFalse(field.reactions.pending)

    def test_reaction_latch_keeps_a_deviation_until_physics_consumes_it(self) -> None:
        field = LavaField()
        deviation = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.86, 0.0)

        field.reactions.observe(
            AudioForces(deviations=deviation),
            AffectiveState(),
            1.0,
        )
        retained = field.reactions.consume(AudioForces())

        self.assertEqual(retained.deviations, deviation)
        self.assertFalse(field.reactions.pending)

    def test_capture_frames_are_mapped_between_lower_cadence_draws(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        first = AudioFrame(0.12, [0.12] * 8, 0.02, 0.08, 1.0)
        second = AudioFrame(0.42, [0.52] * 8, 0.32, 0.18, 1.06)

        with patch.object(field.mapper, "map", wraps=field.mapper.map) as mapper:
            field.observe(first, "music", 1.0)
            field.observe(second, "music", 1.0)
            field.step(second, "music", "atlas", 1.0, LavaConfig(), rasterize=False)

        self.assertEqual(mapper.call_count, 2)
        self.assertEqual(field.frames_seen, 2)
        self.assertGreater(field.forces.transient, 0.10)

    def test_frequency_ranges_map_to_distinct_physical_controls(self) -> None:
        bass_mapper = AudioForceMapper()
        speech_mapper = AudioForceMapper()

        for _ in range(40):
            bass = bass_mapper.map(BASS, "music", 1.0)
            speech = speech_mapper.map(SPEECH, "speech", 1.0)

        self.assertGreater(bass.bass, bass.voice)
        self.assertGreater(bass.bass, bass.detail)
        self.assertGreater(speech.voice, speech.bass)
        self.assertGreater(speech.voice, speech.detail)

    def test_transient_decays_without_changing_steady_energy(self) -> None:
        mapper = AudioForceMapper()
        peak = mapper.map(TRANSIENT, "music", 1.0)
        after = peak
        for _ in range(12):
            after = mapper.map(SILENCE, "music", 1.0)

        self.assertGreater(peak.transient, after.transient)
        self.assertLess(after.transient, 0.05)

    def test_spikes_require_a_band_to_deviate_from_its_recent_average(self) -> None:
        mapper = AudioForceMapper()
        baseline = [0.30] * 8
        steady = AudioForces()
        for index in range(40):
            steady = mapper.map(
                AudioFrame(0.35, baseline, 0.70, 0.08, 1.0 + index * 0.10),
                "music",
                1.0,
            )

        changed = baseline[:]
        changed[6] = 0.92
        surprise = mapper.map(
            AudioFrame(0.35, changed, 0.0, 0.16, 5.0),
            "music",
            1.0,
        )

        self.assertLess(max(steady.deviations), 0.03)
        self.assertGreater(surprise.deviations[6], 0.60)
        self.assertLess(max(surprise.deviations[:6]), 0.03)

    def test_spectral_centroid_distinguishes_low_and_high_tone(self) -> None:
        low_mapper = AudioForceMapper()
        high_mapper = AudioForceMapper()
        low_frame = AudioFrame(0.4, [0.9, 0.8, 0.5, 0.1, 0.03, 0.02, 0.01, 0.0], 0.0, 0.03, 1.0)
        high_frame = AudioFrame(0.4, [0.0, 0.01, 0.02, 0.03, 0.1, 0.5, 0.8, 0.9], 0.0, 0.24, 1.0)

        for _ in range(30):
            low = low_mapper.map(low_frame, "music", 1.0)
            high = high_mapper.map(high_frame, "music", 1.0)

        self.assertLess(low.tone, 0.30)
        self.assertGreater(high.tone, 0.70)

    def test_cadence_estimate_distinguishes_slow_and_fast_pulses(self) -> None:
        slow_mapper = AudioForceMapper()
        fast_mapper = AudioForceMapper()
        bands = [0.45] * 8

        for index in range(8):
            slow = slow_mapper.map(
                AudioFrame(0.45, bands, 0.55, 0.12, 1.0 + index * 0.8), "music", 1.0
            )
            fast = fast_mapper.map(
                AudioFrame(0.45, bands, 0.55, 0.12, 1.0 + index * 0.2), "music", 1.0
            )

        self.assertGreater(fast.tempo, slow.tempo + 0.25)


class CompositionTests(unittest.TestCase):
    def test_embodied_mirror_contracts_under_tension_and_opens_on_release(self) -> None:
        config = LavaConfig(blobs=4)

        def settled_spread(affect: AffectiveState) -> float:
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            for _ in range(120):
                organism.update(
                    1.0 / 22.0,
                    AudioForces(),
                    44,
                    18,
                    config,
                    "buoyant",
                    CELL_ASPECT,
                    affect,
                )
            center_x, center_y = organism.center_of_mass(4)
            return sum(
                math.hypot(body.x - center_x, body.y - center_y)
                for body in organism.bodies[:4]
            ) / 4.0

        contracted = settled_spread(
            AffectiveState(cohesion=0.90, intimacy=0.82, tension=0.78)
        )
        released = settled_spread(AffectiveState(openness=0.82, release=0.84))

        self.assertLess(contracted, 0.23)
        self.assertGreater(released, contracted * 1.55)

    def test_midwest_emo_posture_reaches_then_breaks_open(self) -> None:
        config = LavaConfig(blobs=4)

        def run(affect: AffectiveState) -> tuple[AcousticOrganism, float]:
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            forces = AudioForces(detail=0.45, energy=0.40)
            for _ in range(80):
                organism.update(
                    1.0 / 22.0,
                    forces,
                    44,
                    18,
                    config,
                    "buoyant",
                    CELL_ASPECT,
                    affect,
                )
            center_x, center_y = organism.center_of_mass(4)
            spread = sum(
                math.hypot(body.x - center_x, body.y - center_y)
                for body in organism.bodies[:4]
            ) / 4.0
            return organism, spread

        yearning, held_spread = run(
            AffectiveState(
                cohesion=0.80,
                tension=0.65,
                fragility=0.80,
                yearning=0.90,
            )
        )
        _, cathartic_spread = run(
            AffectiveState(catharsis=0.90, release=0.50, openness=0.40)
        )
        listener = yearning.bodies[1]

        self.assertGreater(listener.stretch_y, listener.stretch_x + 0.10)
        self.assertGreater(cathartic_spread, held_spread * 1.60)

    def test_sound_roles_disturb_their_authored_bodies_differently(self) -> None:
        config = LavaConfig(blobs=4)
        cases = {
            "silence": AudioForces(),
            "bass": AudioForces(
                bass=0.8,
                energy=0.6,
                tone=0.12,
                bands=(0.8, 0.7, 0.4, 0.1, 0.05, 0.02, 0.01, 0.0),
            ),
            "voice": AudioForces(
                voice=0.8,
                energy=0.5,
                tone=0.48,
                bands=(0.1, 0.2, 0.5, 0.8, 0.7, 0.3, 0.1, 0.05),
            ),
            "detail": AudioForces(
                detail=0.8,
                flux=0.3,
                energy=0.4,
                tone=0.82,
                bands=(0.0, 0.02, 0.05, 0.1, 0.2, 0.5, 0.8, 0.9),
            ),
        }
        results = {}
        for name, forces in cases.items():
            organism = AcousticOrganism(body_limit=4)
            starts = [(body.x, body.y) for body in organism.bodies]
            for _ in range(22):
                organism.update(1.0 / 22.0, forces, 44, 18, config, "buoyant")
            movement = [
                math.hypot(body.x - start_x, body.y - start_y)
                for body, (start_x, start_y) in zip(organism.bodies, starts)
            ]
            spread = [body.stretch_x + body.stretch_y for body in organism.bodies]
            results[name] = (movement, spread)

        self.assertGreater(results["bass"][0][0], results["silence"][0][0] * 2.0)
        self.assertGreater(results["voice"][0][1], results["silence"][0][1] * 1.20)
        self.assertEqual(results["detail"][1].index(max(results["detail"][1])), 2)

    def test_tempo_changes_each_body_and_the_casts_overall_motion(self) -> None:
        config = LavaConfig(blobs=4)

        def run(tempo: float) -> AcousticOrganism:
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            forces = AudioForces(tempo=tempo, energy=0.62)
            for _ in range(60):
                organism.update(1.0 / 22.0, forces, 44, 18, config, "buoyant")
            return organism

        slow = run(0.05)
        fast = run(0.92)
        slow_motion = sum(math.hypot(body.vx, body.vy) for body in slow.bodies[:4])
        fast_motion = sum(math.hypot(body.vx, body.vy) for body in fast.bodies[:4])
        shape_changes = [
            abs(fast_body.stretch_x - slow_body.stretch_x)
            + abs(fast_body.stretch_y - slow_body.stretch_y)
            for slow_body, fast_body in zip(slow.bodies[:4], fast.bodies[:4])
        ]

        self.assertGreater(fast_motion, slow_motion * 1.08)
        self.assertTrue(all(change > 0.008 for change in shape_changes))
        self.assertGreater(max(shape_changes) - min(shape_changes), 0.01)

    def test_tile_composition_changes_topology_instead_of_only_scale(self) -> None:
        self.assertEqual(compose_tile(24, 10, 8).active_bodies, 1)
        self.assertEqual(compose_tile(30, 24, 8).active_bodies, 3)
        self.assertEqual(compose_tile(44, 18, 8).active_bodies, 4)
        self.assertEqual(compose_tile(72, 32, 8).active_bodies, 6)
        self.assertEqual(compose_tile(18, 8, 8).habitat, "micro")
        self.assertEqual(compose_tile(20, 32, 8).habitat, "chimney")
        self.assertEqual(compose_tile(90, 12, 8).habitat, "current")
        self.assertEqual(compose_tile(44, 18, 8).habitat, "basin")

    def test_habitats_give_the_same_identities_different_home_regions(self) -> None:
        chimney = compose_tile(20, 32, 6)
        current = compose_tile(90, 12, 6)
        chimney_homes = [habitat_anchor(chimney, index, 0.0) for index in range(3)]
        current_homes = [habitat_anchor(current, index, 0.0) for index in range(3)]

        self.assertGreater(chimney_homes[0][1], chimney_homes[1][1])
        self.assertGreater(chimney_homes[1][1], chimney_homes[2][1])
        self.assertLess(current_homes[0][0], current_homes[1][0])
        self.assertLess(current_homes[1][0], current_homes[2][0])

    def test_tile_currents_form_return_lanes_instead_of_waypoint_motion(self) -> None:
        chimney = compose_tile(20, 32, 6)
        current = compose_tile(90, 12, 6)

        _, chimney_center = circulation_at(chimney, 0.5, 0.5, 0.0)
        _, chimney_wall = circulation_at(chimney, 0.05, 0.5, 0.0)
        current_center, _ = circulation_at(current, 0.5, 0.5, 0.0)
        current_edge, _ = circulation_at(current, 0.5, 0.05, 0.0)

        self.assertLess(chimney_center, 0.0)
        self.assertGreater(chimney_wall, 0.0)
        self.assertGreater(current_center, 0.0)
        self.assertLess(current_edge, 0.0)

    def test_body_scale_uses_physical_terminal_dimensions(self) -> None:
        for width, height in ((20, 32), (44, 18), (90, 12)):
            with self.subTest(width=width, height=height):
                scale_x, scale_y = tile_axis_scales(width, height)
                physical_x = scale_x * width
                physical_y = scale_y * height * CELL_ASPECT
                self.assertAlmostEqual(physical_x, physical_y)

    def test_resize_preserves_body_identity_position_and_momentum(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        settle(field, SPEECH, "speech", 30)
        before = [(id(body), body.x, body.y, body.vx, body.vy) for body in field.bodies]

        field.resize(24, 10)
        after = [(id(body), body.x, body.y, body.vx, body.vy) for body in field.bodies]

        self.assertEqual(before, after)
        self.assertEqual(field.composition.active_bodies, 4)
        settle(field, SILENCE, "book", 1)
        self.assertEqual(field.composition.active_bodies, 1)
        self.assertEqual([item[0] for item in before], [id(body) for body in field.bodies])

    def test_mass_weighted_group_recenters_without_collapsing_body_spacing(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        for body in organism.bodies[:4]:
            body.x -= 0.24
            body.presence = 1.0
        before_x, before_y = organism.center_of_mass(4)
        before_spacing = math.hypot(
            organism.bodies[0].x - organism.bodies[1].x,
            organism.bodies[0].y - organism.bodies[1].y,
        )

        for _ in range(90):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")

        after_x, after_y = organism.center_of_mass(4)
        after_spacing = math.hypot(
            organism.bodies[0].x - organism.bodies[1].x,
            organism.bodies[0].y - organism.bodies[1].y,
        )
        self.assertLess(
            math.hypot(after_x - 0.5, after_y - 0.52),
            math.hypot(before_x - 0.5, before_y - 0.52),
        )
        self.assertGreater(after_spacing, before_spacing * 0.55)

    def test_first_viewport_seeds_the_cast_in_its_actual_habitat(self) -> None:
        field = LavaField()
        field.resize(18, 8)

        center_x, center_y = field.organism.center_of_mass(1)

        self.assertAlmostEqual(center_x, 0.5, places=2)
        self.assertAlmostEqual(center_y, 0.52, places=2)

    def test_first_four_bodies_keep_authored_identities_and_silhouettes(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        settle(field, SILENCE, "book", 45)
        bodies = field.bodies[:4]

        self.assertEqual(
            [body.character.name for body in bodies],
            ["ballast", "listener", "glint", "drifter"],
        )
        self.assertGreater(bodies[0].radius, bodies[1].radius)
        self.assertGreater(bodies[1].radius, bodies[3].radius)
        self.assertGreater(bodies[3].radius, bodies[2].radius)

    def test_transient_selects_one_body_and_leaves_a_decaying_afterglow(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        strike = AudioForces(transient=1.0, tone=0.86)
        organism.update(1.0 / 22.0, strike, 44, 18, config, "buoyant")

        lit = [body for body in organism.bodies[:4] if body.afterglow > 0.50]
        self.assertEqual([body.character.name for body in lit], ["glint"])
        self.assertEqual([body.afterglow for body in organism.bodies[:2]], [0.0, 0.0])
        self.assertEqual(organism.bodies[3].afterglow, 0.0)
        self.assertEqual([body.spike for body in organism.bodies[:4]], [0.0] * 4)

        for _ in range(36):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")
        self.assertLess(organism.bodies[2].afterglow, 0.05)

    def test_fast_change_spikes_then_softens_before_afterglow_fades(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        strike = AudioForces(
            transient=1.0,
            tone=0.86,
            deviations=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        )

        organism.update(1.0 / 22.0, strike, 44, 18, config, "buoyant")
        body = organism.bodies[2]
        self.assertGreater(body.spike, 0.90)

        for _ in range(12):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")

        self.assertLess(body.spike, 0.02)
        self.assertGreater(body.afterglow, body.spike)

    def test_transient_pressure_crosses_the_tile_and_recovers(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        strike = AudioForces(transient=0.9, pulse=0.9, flux=0.7, energy=0.8, tone=0.72)

        organism.update(1.0 / 22.0, strike, 44, 18, config, "buoyant")
        for _ in range(12):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")

        pressures = [body.acoustic_pressure for body in organism.bodies[:4]]
        self.assertGreater(max(pressures), 0.10)
        self.assertGreater(max(pressures) - min(pressures), 0.05)

        for _ in range(60):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")
        self.assertLess(max(body.acoustic_pressure for body in organism.bodies[:4]), 0.05)
        self.assertEqual(organism.pressure_waves, [])

    def test_wall_contact_squashes_on_the_contact_axis(self) -> None:
        config = LavaConfig(blobs=4)

        side = AcousticOrganism(body_limit=4)
        side.bodies[0].x = 0.0
        side.bodies[0].y = 0.5
        side.bodies[0].vx = -0.2
        side.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")
        self.assertGreater(side.bodies[0].wall_pressure_x, 0.0)
        self.assertGreater(side.bodies[0].stretch_y, side.bodies[0].stretch_x)
        self.assertGreater(side.bodies[0].vx, 0.0)
        self.assertLess(side.bodies[0].vx, 0.03)

        ceiling = AcousticOrganism(body_limit=4)
        ceiling.bodies[0].x = 0.5
        ceiling.bodies[0].y = 0.0
        ceiling.bodies[0].vy = -0.2
        ceiling.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")
        self.assertGreater(ceiling.bodies[0].wall_pressure_y, 0.0)
        self.assertGreater(ceiling.bodies[0].stretch_x, ceiling.bodies[0].stretch_y)
        self.assertGreater(ceiling.bodies[0].vy, 0.0)
        self.assertLess(ceiling.bodies[0].vy, 0.03)


class RenderingBudgetTests(unittest.TestCase):
    def test_contour_fluid_step_skips_semantic_field_rasterization(self) -> None:
        field = LavaField()
        field.resize(44, 18)

        with patch.object(field.renderer, "render") as render:
            field.step(
                MUSIC,
                "music",
                "atlas",
                1.0,
                LavaConfig(blobs=4),
                rasterize=False,
            )

        render.assert_not_called()

    def test_low_display_cadence_preserves_elapsed_physics_time(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        field._last_step_at = 9.7
        phase_before = field.phase

        with patch("lavatune.app.time.monotonic", return_value=10.0):
            field.step(
                SILENCE,
                "book",
                "atlas",
                1.0,
                LavaConfig(blobs=4),
                rasterize=False,
            )

        self.assertGreater(field.phase - phase_before, 0.15)
        self.assertLess(field.phase - phase_before, 0.25)

    def test_audio_observation_does_not_require_a_physics_step(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        phase_before = field.phase

        field.step(
            TRANSIENT,
            "music",
            "atlas",
            1.0,
            LavaConfig(blobs=4),
            rasterize=False,
            advance_physics=False,
        )

        self.assertEqual(field.phase, phase_before)
        self.assertGreater(field.render_forces.transient, 0.0)

    def test_contour_fluid_stays_centered_and_bounded_across_review_matrix(self) -> None:
        habitats = ((18, 8), (20, 32), (44, 18), (90, 12))
        fixtures = (
            (SILENCE, "book"),
            (SPEECH, "speech"),
            (BASS, "music"),
            (MUSIC, "music"),
            (TRANSIENT, "music"),
        )
        config = LavaConfig(blobs=6)

        for width, height in habitats:
            for frame, mode in fixtures:
                with self.subTest(width=width, height=height, mode=mode, rms=frame.rms):
                    field = LavaField()
                    field.resize(width, height)
                    for _ in range(42):
                        field._last_step_at = None
                        field.step(
                            frame,
                            mode,
                            "atlas",
                            1.0,
                            config,
                            rasterize=False,
                        )
                    rows = FLUID_MATERIAL.render(
                        field.bodies,
                        field.forces,
                        width,
                        height,
                        MaterialStyle(),
                        field.phase,
                        CELL_ASPECT,
                    )
                    occupied = [
                        (x, y)
                        for y, row in enumerate(rows)
                        for x, cell in enumerate(row)
                        if cell.glyph != " "
                    ]
                    visible = len(occupied) / (width * height)
                    center_x = sum(x for x, _ in occupied) / len(occupied) / max(1, width - 1)
                    center_y = sum(y for _, y in occupied) / len(occupied) / max(1, height - 1)

                    self.assertGreater(visible, 0.04)
                    self.assertLess(visible, 0.55)
                    self.assertLess(abs(center_x - 0.5), 0.27)
                    self.assertLess(abs(center_y - 0.52), 0.30)

    def test_semantic_field_keeps_mass_surface_and_attention_separate(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        settle(field, TRANSIENT, "music", 16)

        self.assertIsNot(field.field_frame.mass, field.field_frame.surface)
        self.assertIs(field.attention_buffers, field.field_frame.attention)
        self.assertTrue(any(value > 0.0 for row in field.field_frame.mass for value in row))
        self.assertTrue(any(value > 0.0 for row in field.field_frame.surface for value in row))
        self.assertTrue(any(value > 0.0 for row in field.field_frame.attention for value in row))

    def test_review_sequence_stays_legible_in_every_tile_habitat(self) -> None:
        shapes = ((18, 8), (20, 32), (44, 18), (90, 12))
        fixtures = (
            (SILENCE, "book"),
            (SPEECH, "speech"),
            (BASS, "music"),
            (MUSIC, "music"),
            (TRANSIENT, "music"),
        )
        config = LavaConfig(blobs=6)

        for width, height in shapes:
            for frame, mode in fixtures:
                with self.subTest(width=width, height=height, mode=mode, rms=frame.rms):
                    field = LavaField()
                    field.resize(width, height)
                    for _ in range(42):
                        field._last_step_at = None
                        field.step(frame, mode, "atlas", 1.0, config)
                    metrics = measure_field(field.buffers)

                    self.assertGreater(metrics.visible, 0.05)
                    self.assertLess(metrics.visible, 0.48)
                    self.assertGreaterEqual(metrics.regions, 1)
                    self.assertLess(metrics.saturated, 0.02)

                    for material_name in MATERIAL_NAMES:
                        material = material_for(material_name)
                        style = MaterialStyle()
                        cells = [
                            material.cell(
                                field.field_frame,
                                x,
                                y,
                                width,
                                height,
                                style,
                                field.phase,
                            )
                            for y in range(height)
                            for x in range(width)
                        ]
                        visible = sum(cell.glyph != " " for cell in cells) / len(cells)
                        self.assertGreater(visible, 0.04)
                        self.assertLess(visible, 0.52)

    def test_silence_keeps_readable_bodies_and_negative_space(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        settle(field, SILENCE, "book")
        metrics = measure_field(field.buffers)

        self.assertGreater(metrics.visible, 0.12)
        self.assertLess(metrics.visible, 0.48)
        self.assertGreaterEqual(metrics.regions, 2)
        self.assertEqual(metrics.saturated, 0.0)

    def test_transient_attention_is_local_and_does_not_wash_out_field(self) -> None:
        field = LavaField()
        field.resize(44, 18)
        settle(field, SILENCE, "book", 24)
        settle(field, TRANSIENT, "music", 66)
        metrics = measure_field(field.buffers)

        self.assertLess(metrics.visible, 0.48)
        self.assertLess(metrics.bright, 0.08)
        self.assertLess(metrics.saturated, 0.02)

    def test_terminal_transfer_curve_reserves_peak_for_attention(self) -> None:
        self.assertEqual(_visual_shade(0.055), 0.0)
        self.assertLess(_visual_shade(0.72), 0.80)
        self.assertEqual(_visual_shade(1.0), 1.0)

    def test_attention_color_is_not_spent_on_ordinary_body_intensity(self) -> None:
        self.assertEqual(_semantic_color_bucket(0.90, 0.0, 4), 2)
        self.assertEqual(_semantic_color_bucket(0.35, 0.10, 4), 3)

    def test_terminal_columns_interpolate_instead_of_repeating_blocks(self) -> None:
        source = [0.0, 1.0]
        samples = [_interpolated_row_value(source, x, 5) for x in range(5)]

        self.assertEqual(samples, [0.0, 0.25, 0.5, 0.75, 1.0])


class SelectedDirectionTests(unittest.TestCase):
    def test_default_is_the_canonical_listening_posture(self) -> None:
        config = load_config(None, None, "atlas")

        self.assertEqual(_product_preset_name_for_config(config), "listen")
        self.assertEqual(_scene_name_for_config(config), "soft-afterglow")
        self.assertEqual(config.audio.analysis, "bands")
        self.assertEqual(config.audio.frame_size, 1024)

    def test_operating_modes_do_not_replace_the_canonical_appearance(self) -> None:
        for preset in PRODUCT_PRESETS:
            with self.subTest(preset=preset):
                config = load_config(None, None, "atlas")
                _apply_product_preset(config, preset)
                self.assertEqual(_scene_name_for_config(config), "soft-afterglow")

    def test_operating_modes_preserve_selected_semantic_material(self) -> None:
        for preset in PRODUCT_PRESETS:
            with self.subTest(preset=preset):
                config = load_config(None, None, "atlas")
                config.render.material = "fluid"
                config.render.weight = "airy"
                config.render.edge = "defined"
                config.render.afterglow = "quiet"

                _apply_product_preset(config, preset)

                self.assertEqual(config.render.material, "fluid")
                self.assertEqual(config.render.weight, "airy")
                self.assertEqual(config.render.edge, "defined")
                self.assertEqual(config.render.afterglow, "quiet")

    def test_material_control_does_not_request_an_organism_reset(self) -> None:
        config = load_config(None, None, "atlas")
        controls = _make_controls(config)
        ui = UiState()
        material = controls["Look"][0]

        message = material.adjust(config, 1, ui)

        self.assertEqual(message, "material: fluid")
        self.assertEqual(config.render.material, "fluid")
        self.assertFalse(ui.reset_lava)

    def test_compact_defaults_resolve_to_selected_direction(self) -> None:
        config = load_config(None, None, "atlas")
        config.content_mode = "speech"
        config.audio.analysis = "bands"
        config.audio.sample_rate = 22050
        config.audio.frame_size = 1024
        config = apply_cli_overrides(config, compact_tile=True, hide_stats=True)

        self.assertEqual(LavaField().motion_profile, "buoyant")
        self.assertEqual(_scene_name_for_config(config), "soft-afterglow")
        self.assertEqual(_product_preset_name_for_config(config), "speech")
        self.assertEqual(config.lava.reactivity, 1.0)
        self.assertEqual(config.fps, 22)


if __name__ == "__main__":
    unittest.main()
