from __future__ import annotations

import unittest

from lavatune.app import (
    LavaField,
    PRODUCT_PRESETS,
    _apply_product_preset,
    _interpolated_row_value,
    _product_preset_name_for_config,
    _scene_name_for_config,
    _semantic_color_bucket,
    _visual_shade,
)
from lavatune.audio import AudioFrame
from lavatune.config import LavaConfig, apply_cli_overrides, load_config
from lavatune.organism import (
    AcousticOrganism,
    AudioForceMapper,
    AudioForces,
    compose_tile,
    habitat_anchor,
    measure_field,
)


SILENCE = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 0.0)
SPEECH = AudioFrame(0.24, [0.12, 0.18, 0.42, 0.58, 0.38, 0.18, 0.09, 0.05], 0.07, 0.08, 0.0)
BASS = AudioFrame(0.48, [0.92, 0.78, 0.35, 0.16, 0.09, 0.05, 0.03, 0.02], 0.18, 0.05, 0.0)
TRANSIENT = AudioFrame(0.72, [0.82, 0.72, 0.64, 0.58, 0.70, 0.80, 0.94, 0.88], 0.92, 0.24, 0.0)


def settle(field: LavaField, frame: AudioFrame, mode: str, frames: int = 90) -> None:
    config = LavaConfig(blobs=6)
    for _ in range(frames):
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)


class AudioForceTests(unittest.TestCase):
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

        for _ in range(36):
            organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "buoyant")
        self.assertLess(organism.bodies[2].afterglow, 0.05)


class RenderingBudgetTests(unittest.TestCase):
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

    def test_operating_modes_do_not_replace_the_canonical_appearance(self) -> None:
        for preset in PRODUCT_PRESETS:
            with self.subTest(preset=preset):
                config = load_config(None, None, "atlas")
                _apply_product_preset(config, preset)
                self.assertEqual(_scene_name_for_config(config), "soft-afterglow")

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
