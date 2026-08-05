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
    apply_behavior_profile,
    behavior_for_context,
    NarrativeState,
    NarrativeTracker,
    MOTION_PROFILES,
    SharedPosture,
    adaptive_centroid_axis,
    circulation_at,
    compose_tile,
    habitat_anchor,
    measure_field,
    motion_cues,
    shared_posture,
    thermal_habitat_anchor,
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
    def test_shared_posture_keeps_the_acoustic_relationships_bounded(self) -> None:
        neutral = shared_posture(AffectiveState(), NarrativeState())
        tense = shared_posture(
            AffectiveState(tension=0.88, restraint=0.82, weight=0.66),
            NarrativeState(expectation=0.54),
        )
        released = shared_posture(
            AffectiveState(release=0.84, catharsis=0.80, openness=0.64),
            NarrativeState(resolution=0.58),
        )
        fractured = shared_posture(
            AffectiveState(snap=0.86, volatility=0.78),
            NarrativeState(interruption=0.90),
        )
        steady = shared_posture(
            AffectiveState(cohesion=0.90, intimacy=0.72), NarrativeState()
        )

        for posture in (neutral, tense, released, fractured, steady):
            self.assertIsInstance(posture, SharedPosture)
            self.assertTrue(
                all(
                    0.0 <= value <= 1.0
                    for value in (
                        posture.contraction,
                        posture.fracture,
                        posture.openness,
                        posture.stillness,
                        posture.synchrony,
                    )
                )
            )
        self.assertGreater(tense.contraction, neutral.contraction)
        self.assertGreater(released.openness, tense.openness)
        self.assertGreater(fractured.fracture, neutral.fracture)
        self.assertGreater(steady.synchrony, fractured.synchrony)
        phrase = shared_posture(
            AffectiveState(),
            NarrativeState(cadence=0.82, held_pressure=0.76, rupture=0.84, aftermath=0.70),
        )
        self.assertGreater(phrase.contraction, neutral.contraction)
        self.assertGreater(phrase.fracture, neutral.fracture)
        self.assertGreater(phrase.stillness, neutral.stillness)
        overdriven = shared_posture(
            AffectiveState(), NarrativeState(overdrive=0.90)
        )
        self.assertGreater(overdriven.fracture, neutral.fracture)
        self.assertLess(overdriven.synchrony, neutral.synchrony)

    def test_listening_contexts_map_the_same_forces_to_distinct_behavior(self) -> None:
        raw = AudioForces(
            bass=0.80,
            voice=0.70,
            detail=0.65,
            transient=0.90,
            tempo=0.75,
            pulse=0.85,
            flux=0.60,
            rhythm_density=0.70,
            rhythm_impulse=0.80,
            bands=(0.60,) * 8,
            hits=(0.80,) * 8,
            deviations=(0.70,) * 8,
        )
        mapped = {
            name: apply_behavior_profile(raw, behavior_for_context(name))
            for name in ("podcast", "radio", "music", "microphone")
        }

        self.assertEqual(behavior_for_context("podcast").active_bodies, 2)
        self.assertEqual(behavior_for_context("radio").active_bodies, 3)
        self.assertEqual(behavior_for_context("music").active_bodies, 4)
        self.assertEqual(behavior_for_context("microphone").active_bodies, 1)
        self.assertGreater(mapped["music"].transient, mapped["radio"].transient)
        self.assertGreater(mapped["radio"].transient, mapped["podcast"].transient)
        self.assertGreater(mapped["podcast"].voice, mapped["music"].voice * 0.95)
        self.assertLess(mapped["microphone"].bass, mapped["podcast"].bass)
        self.assertGreater(
            behavior_for_context("music").stab_gain,
            behavior_for_context("radio").stab_gain,
        )
        self.assertLess(
            abs(mapped["music"].detail - mapped["radio"].detail),
            0.10,
        )

    def test_organisms_keep_independent_rotational_momentum(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        forces = AudioForces(
            bass=0.76, voice=0.64, detail=0.70, transient=0.88, tempo=0.68,
            pulse=0.72, rhythm_impulse=0.80, bands=(0.65,) * 8, hits=(0.84,) * 8,
        )
        for _ in range(24):
            organism.update(1.0 / 22.0, forces, 60, 20, LavaConfig(blobs=4))

        momentum = [
            round(abs(body.angular_yaw) + abs(body.angular_pitch) + abs(body.angular_roll), 3)
            for body in organism.bodies[:4]
        ]
        poses = [
            (round(body.yaw, 2), round(body.pitch, 2), round(body.roll, 2))
            for body in organism.bodies[:4]
        ]
        self.assertEqual(len(set(momentum)), 4)
        self.assertEqual(len(set(poses)), 4)

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

    def test_restraint_saturates_so_ten_and_long_waits_snap_alike(self) -> None:
        calm = AudioForces(
            voice=0.28,
            detail=0.38,
            energy=0.20,
            level=0.20,
            bands=(0.12, 0.14, 0.18, 0.22, 0.20, 0.19, 0.16, 0.13),
        )
        attack = AudioForces(
            bass=0.82,
            voice=0.68,
            detail=0.74,
            transient=0.92,
            energy=0.94,
            level=0.94,
            pulse=0.84,
            flux=0.72,
            bands=(0.82, 0.78, 0.74, 0.86, 0.80, 0.88, 0.92, 0.84),
        )
        sustain = AudioForces(
            bass=0.78,
            voice=0.64,
            detail=0.68,
            energy=0.90,
            level=0.90,
            pulse=0.24,
            bands=(0.78, 0.74, 0.70, 0.82, 0.76, 0.84, 0.88, 0.80),
        )

        def snap_after(seconds: float) -> tuple[AffectiveState, AffectiveState]:
            tracker = AffectiveTracker()
            steps = round(seconds / 0.10)
            held = AffectiveState()
            for index in range(steps):
                held = tracker.update(calm, 1.0 + index * 0.10)
            tracker.update(attack, 1.0 + steps * 0.10)
            snapped = tracker.update(sustain, 1.1 + steps * 0.10)
            return held, snapped

        short_hold, early = snap_after(10.0)
        long_hold, late = snap_after(130.0)

        self.assertEqual(short_hold.restraint, 1.0)
        self.assertEqual(long_hold.restraint, 1.0)
        self.assertGreater(early.snap, 0.65)
        self.assertAlmostEqual(early.snap, late.snap, delta=0.04)
        self.assertAlmostEqual(early.catharsis, late.catharsis, delta=0.08)

    def test_brief_pause_does_not_earn_full_snap_choreography(self) -> None:
        tracker = AffectiveTracker()
        calm = AudioForces(energy=0.18, level=0.18, detail=0.32, bands=(0.14,) * 8)
        attack = AudioForces(
            energy=0.94,
            level=0.94,
            transient=0.92,
            pulse=0.82,
            flux=0.70,
            bands=(0.86,) * 8,
        )
        sustain = AudioForces(energy=0.90, level=0.90, bands=(0.82,) * 8)
        for index in range(20):
            tracker.update(calm, 1.0 + index * 0.10)

        tracker.update(attack, 3.0)
        snapped = tracker.update(sustain, 3.1)

        self.assertLess(snapped.restraint, 0.30)
        self.assertLess(snapped.snap, 0.30)

    def test_single_notification_after_restraint_stays_a_local_event(self) -> None:
        tracker = AffectiveTracker()
        calm = AudioForces(energy=0.18, level=0.18, detail=0.28, bands=(0.12,) * 8)
        notification = AudioForces(
            energy=0.92,
            level=0.92,
            transient=0.96,
            pulse=0.88,
            flux=0.76,
            bands=(0.88,) * 8,
        )
        for index in range(110):
            tracker.update(calm, 1.0 + index * 0.10)

        candidate = tracker.update(notification, 12.0)
        after = tracker.update(AudioForces(), 12.1)

        self.assertLess(candidate.snap, 0.10)
        self.assertLess(after.snap, 0.10)

    def test_gradual_crescendo_opens_without_false_snap(self) -> None:
        tracker = AffectiveTracker()
        calm_bands = (0.12,) * 8
        for index in range(110):
            tracker.update(
                AudioForces(energy=0.18, level=0.18, detail=0.26, bands=calm_bands),
                1.0 + index * 0.10,
            )

        peak_snap = 0.0
        for index in range(40):
            amount = index / 39.0
            state = tracker.update(
                AudioForces(
                    energy=0.18 + amount * 0.70,
                    level=0.18 + amount * 0.70,
                    detail=0.26 + amount * 0.34,
                    transient=0.015,
                    pulse=0.02,
                    bands=tuple(0.12 + amount * 0.66 for _ in range(8)),
                ),
                12.0 + index * 0.10,
            )
            peak_snap = max(peak_snap, state.snap)

        self.assertLess(peak_snap, 0.10)
        self.assertGreater(state.openness, 0.12)

    def test_already_loud_audio_cannot_prime_a_full_snap(self) -> None:
        tracker = AffectiveTracker()
        loud = AudioForces(
            energy=0.82,
            level=0.82,
            bass=0.64,
            detail=0.60,
            bands=(0.72,) * 8,
        )
        for index in range(120):
            tracker.update(loud, 1.0 + index * 0.10)
        tracker.update(
            AudioForces(
                energy=0.96,
                level=0.96,
                transient=0.90,
                pulse=0.82,
                flux=0.60,
                bands=(0.90,) * 8,
            ),
            13.0,
        )
        state = tracker.update(
            AudioForces(energy=0.92, level=0.92, bands=(0.86,) * 8), 13.1
        )

        self.assertLess(state.restraint, 0.10)
        self.assertLess(state.snap, 0.15)

    def test_mapped_quiet_to_loud_frames_preserve_snap_contrast(self) -> None:
        mapper = AudioForceMapper()
        tracker = AffectiveTracker()
        quiet_bands = [0.10, 0.11, 0.13, 0.15, 0.14, 0.12, 0.10, 0.09]
        for index in range(120):
            quiet = mapper.map(
                AudioFrame(0.08, quiet_bands, 0.0, 0.06, 1.0 + index * 0.10),
                "music",
                1.0,
            )
            held = tracker.update(quiet, 1.0 + index * 0.10)

        attack = mapper.map(
            AudioFrame(0.65, [0.80] * 8, 0.90, 0.18, 13.0),
            "music",
            1.0,
        )
        tracker.update(attack, 13.0)
        sustain = mapper.map(
            AudioFrame(0.58, [0.75] * 8, 0.02, 0.16, 13.1),
            "music",
            1.0,
        )
        snapped = tracker.update(sustain, 13.1)

        self.assertEqual(held.restraint, 1.0)
        self.assertGreater(snapped.snap, 0.60)

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

    def test_reaction_latch_accumulates_rapid_impulses_between_physics_steps(self) -> None:
        field = LavaField()

        for timestamp in (1.0, 1.05, 1.10):
            field.reactions.observe(
                AudioForces(rhythm_density=0.72, rhythm_impulse=0.24),
                AffectiveState(),
                timestamp,
            )
        retained = field.reactions.consume(AudioForces())

        self.assertGreater(retained.rhythm_impulse, 0.60)
        self.assertEqual(retained.rhythm_density, 0.72)
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

    def test_rapid_subdivisions_drive_density_without_starving_tempo(self) -> None:
        mapper = AudioForceMapper()
        bands = [0.42, 0.48, 0.56, 0.64, 0.52, 0.45, 0.38, 0.31]

        for index in range(18):
            mapped = mapper.map(
                AudioFrame(0.48, bands, 0.52, 0.16, 1.0 + index * 0.10),
                "music",
                1.0,
            )

        self.assertGreater(mapped.rhythm_density, 0.55)
        self.assertGreater(mapped.tempo, 0.45)
        self.assertGreater(mapped.rhythm_impulse, 0.20)

        for index in range(14):
            settled = mapper.map(
                AudioFrame(0.48, bands, 0.0, 0.16, 2.8 + index * 0.10),
                "music",
                1.0,
            )

        self.assertLess(settled.rhythm_density, 0.08)
        self.assertEqual(settled.rhythm_impulse, 0.0)

    def test_bright_attack_keeps_rhythm_without_becoming_a_full_body_impact(self) -> None:
        def map_hit(bands: list[float]) -> AudioForces:
            mapper = AudioForceMapper()
            for index in range(20):
                mapper.map(
                    AudioFrame(0.18, [0.18] * 8, 0.0, 0.08, 1.0 + index * 0.10),
                    "music",
                    1.0,
                )
            return mapper.map(
                AudioFrame(0.62, bands, 0.95, 0.28, 3.2), "music", 1.0
            )

        bright = map_hit([0.12, 0.14, 0.16, 0.18, 0.22, 0.82, 0.90, 0.96])
        kick = map_hit([0.96, 0.90, 0.82, 0.28, 0.20, 0.14, 0.10, 0.08])

        self.assertGreater(bright.detail, bright.bass)
        self.assertGreater(bright.rhythm_impulse, 0.50)
        self.assertGreater(kick.transient, bright.transient * 4.0)
        self.assertGreater(kick.pulse, bright.pulse * 4.0)

    def test_steady_compressed_audio_does_not_fake_rapid_density(self) -> None:
        mapper = AudioForceMapper()
        bands = [0.62] * 8

        for index in range(24):
            mapped = mapper.map(
                AudioFrame(0.62, bands, 0.0, 0.14, 1.0 + index * 0.05),
                "music",
                1.0,
            )

        self.assertLess(mapped.rhythm_density, 0.08)
        self.assertEqual(mapped.rhythm_impulse, 0.0)


class NarrativeTests(unittest.TestCase):
    def test_phrase_memory_turns_held_cadence_into_rupture_then_aftermath(self) -> None:
        tracker = NarrativeTracker()
        tense = AffectiveState(tension=0.75, cohesion=0.80, volatility=0.05)
        steady = AudioForces(
            rhythm_impulse=0.55,
            tempo=0.70,
            energy=0.65,
            level=0.65,
            tone=0.18,
            transient=0.08,
            bands=(0.50,) * 8,
        )
        timestamp = 1.0
        for _ in range(16):
            held = tracker.update(steady, tense, timestamp)
            timestamp += 0.40

        breaker = AudioForces(
            rhythm_impulse=0.70,
            tempo=0.45,
            energy=0.70,
            level=0.70,
            tone=0.50,
            transient=0.50,
            deviations=(0.85,) * 8,
            bands=(0.70,) * 8,
        )
        ruptured = tracker.update(
            breaker,
            AffectiveState(tension=0.75, snap=0.40, cohesion=0.80, volatility=0.50),
            timestamp + 0.75,
        )
        quiet = AudioForces(level=0.02, energy=0.02)
        for _ in range(4):
            timestamp += 0.20
            aftermath = tracker.update(quiet, AffectiveState(weight=0.65), timestamp + 0.75)

        fresh = NarrativeTracker().update(
            breaker,
            AffectiveState(tension=0.75, snap=0.40, cohesion=0.80, volatility=0.50),
            1.0,
        )
        silent = NarrativeTracker()
        for index in range(12):
            empty = silent.update(quiet, AffectiveState(), 1.0 + index * 0.20)

        self.assertGreater(held.cadence, 0.80)
        self.assertGreater(held.held_pressure, 0.80)
        self.assertGreater(ruptured.rupture, fresh.rupture + 0.35)
        self.assertGreater(aftermath.aftermath, 0.45)
        self.assertLess(empty.held_pressure, 0.01)
        self.assertLess(empty.rupture, 0.01)
        self.assertLess(empty.aftermath, 0.01)

    def test_dense_peak_enters_overdrive_without_a_cadence_break(self) -> None:
        tracker = NarrativeTracker()
        dense_peak = AudioForces(
            energy=0.92,
            level=0.82,
            detail=0.84,
            tempo=0.72,
            transient=0.64,
            pulse=0.78,
            rhythm_density=0.86,
            rhythm_impulse=0.74,
        )
        quiet = AudioForces(energy=0.18, level=0.18, detail=0.12)
        for index in range(12):
            peak = tracker.update(dense_peak, AffectiveState(agitation=0.70), 1.0 + index * 0.10)
        for index in range(20):
            settled = tracker.update(quiet, AffectiveState(), 2.3 + index * 0.10)

        self.assertGreater(peak.overdrive, 0.55)
        self.assertLess(settled.overdrive, peak.overdrive * 0.15)

    def test_predictable_motion_builds_expectation(self) -> None:
        tracker = NarrativeTracker()
        predictable = AudioForces(tempo=0.68, energy=0.46, flux=0.03)
        stable = AffectiveState(volatility=0.08)

        for index in range(60):
            state = tracker.update(predictable, stable, 1.0 + index * 0.10)

        self.assertGreater(state.expectation, 0.65)
        self.assertLess(state.interruption, 0.05)

    def test_expectation_gives_the_same_surprise_more_context(self) -> None:
        predictable = AudioForces(tempo=0.68, energy=0.46, flux=0.03)
        stable = AffectiveState(volatility=0.08)
        surprise = AudioForces(
            transient=0.90,
            energy=0.84,
            flux=0.82,
            deviations=(0.78,) * 8,
        )

        primed = NarrativeTracker()
        for index in range(60):
            primed.update(predictable, stable, 1.0 + index * 0.10)
        contextual = primed.update(surprise, AffectiveState(volatility=0.82), 7.0)

        fresh = NarrativeTracker()
        isolated = fresh.update(surprise, AffectiveState(volatility=0.82), 7.0)

        self.assertGreater(contextual.interruption, 0.55)
        self.assertGreater(contextual.interruption, isolated.interruption * 8.0)

    def test_resolution_requires_prior_tension_and_release(self) -> None:
        forces = AudioForces(energy=0.24, flux=0.02)
        tracker = NarrativeTracker()

        resolved = tracker.update(
            forces,
            AffectiveState(tension=0.82, release=0.78, catharsis=0.62),
            1.0,
        )
        unearned = NarrativeTracker().update(
            forces,
            AffectiveState(tension=0.04, release=0.78, catharsis=0.62),
            1.0,
        )

        self.assertGreater(resolved.resolution, 0.55)
        self.assertLess(unearned.resolution, 0.05)

    def test_silence_does_not_prime_a_notification_as_narrative_interruption(self) -> None:
        tracker = NarrativeTracker()
        for index in range(100):
            quiet = tracker.update(
                AudioForces(level=0.0),
                AffectiveState(),
                1.0 + index * 0.10,
            )

        notification = tracker.update(
            AudioForces(
                level=0.92,
                transient=0.96,
                flux=0.82,
                deviations=(0.84,) * 8,
            ),
            AffectiveState(volatility=0.90),
            11.0,
        )

        self.assertLess(quiet.expectation, 0.05)
        self.assertLess(notification.interruption, 0.10)


class CompositionTests(unittest.TestCase):
    def test_motion_cues_split_tempo_float_from_high_tone_chop(self) -> None:
        slow = motion_cues(AudioForces(tempo=0.12, energy=0.60), 0.0, 0.0)
        fast = motion_cues(AudioForces(tempo=0.88, energy=0.60), 0.0, 0.0)
        scream = motion_cues(
            AudioForces(detail=0.92, tone=0.94, flux=0.82, rhythm_density=0.40),
            0.0,
            0.0,
        )

        self.assertGreater(fast.float_drive, slow.float_drive * 5.0)
        self.assertGreater(scream.chop_drive, 0.80)
        self.assertLess(slow.chop_drive, 0.05)

    def test_music_stabs_are_separate_from_radio_motion(self) -> None:
        strike = AudioForces(transient=0.70, pulse=0.62, rhythm_impulse=0.54)
        music = motion_cues(
            strike,
            0.0,
            0.0,
            behavior_for_context("music").stab_gain,
        )
        radio = motion_cues(
            strike,
            0.0,
            0.0,
            behavior_for_context("radio").stab_gain,
        )

        self.assertGreater(music.stab_drive, 0.30)
        self.assertEqual(radio.stab_drive, 0.0)

    def test_lavalamp_slows_planar_action_without_suppressing_inner_response(self) -> None:
        config = LavaConfig(blobs=4, drift=0.22, viscosity=0.95)
        forces = AudioForces(
            bass=0.72,
            detail=0.76,
            transient=0.82,
            energy=0.70,
            tempo=0.64,
            pulse=0.66,
            bands=(0.72, 0.64, 0.48, 0.38, 0.32, 0.42, 0.68, 0.76),
        )
        buoyant = AcousticOrganism(body_limit=4)
        lavalamp = AcousticOrganism(body_limit=4)
        buoyant.seed_for_tile(44, 18, 4)
        lavalamp.seed_for_tile(44, 18, 4)
        starts = [(body.x, body.y) for body in lavalamp.bodies[:4]]
        initial_radii = [body.radius for body in lavalamp.bodies[:4]]

        for _ in range(60):
            buoyant.update(1.0 / 22.0, forces, 44, 18, config, "buoyant")
            lavalamp.update(1.0 / 22.0, forces, 44, 18, config, "lavalamp")

        buoyant_travel = sum(
            math.hypot(body.x - start_x, body.y - start_y)
            for body, (start_x, start_y) in zip(buoyant.bodies[:4], starts)
        )
        lavalamp_travel = sum(
            math.hypot(body.x - start_x, body.y - start_y)
            for body, (start_x, start_y) in zip(lavalamp.bodies[:4], starts)
        )

        self.assertLess(lavalamp_travel, buoyant_travel * 0.72)
        self.assertGreater(max(body.afterglow for body in lavalamp.bodies[:4]), 0.70)
        self.assertGreater(
            max(
                abs(body.radius - initial_radius)
                for body, initial_radius in zip(lavalamp.bodies[:4], initial_radii)
            ),
            0.01,
        )
        self.assertLess(MOTION_PROFILES["lavalamp"].planar_gain, 0.70)
        self.assertGreater(MOTION_PROFILES["lavalamp"].surface_motion, 0.70)

    def test_lavalamp_planar_force_eases_into_a_new_direction(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        organism.seed_for_tile(44, 18, 4)
        config = LavaConfig(blobs=4, drift=0.22, viscosity=0.95)
        strong = AudioForces(bass=0.82, energy=0.76, tempo=0.68, detail=0.54)

        organism.update(1.0 / 22.0, strong, 44, 18, config, "lavalamp")
        body = organism.bodies[0]
        previous_force = (body.planar_force_x, body.planar_force_y)
        organism.update(1.0 / 22.0, AudioForces(), 44, 18, config, "lavalamp")

        current_force = (body.planar_force_x, body.planar_force_y)
        self.assertGreater(math.hypot(*current_force), 0.0)
        self.assertLess(
            math.dist(previous_force, current_force),
            math.hypot(*previous_force) * 0.45,
        )

    def test_volume_scars_persist_until_a_new_stable_pattern_earns_recovery(self) -> None:
        config = LavaConfig(blobs=4)
        organism = AcousticOrganism(body_limit=4)
        organism.seed_for_tile(44, 18, 4)
        rupture = NarrativeState(rupture=0.90, held_pressure=0.80)
        organism.update(
            1.0 / 22.0,
            AudioForces(),
            44,
            18,
            config,
            "buoyant",
            CELL_ASPECT,
            AffectiveState(volatility=0.60),
            rupture,
            embody_posture=True,
        )
        marked = [body.scar for body in organism.bodies[:4]]
        for _ in range(80):
            organism.update(
                1.0 / 22.0,
                AudioForces(),
                44,
                18,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(volatility=0.60),
                NarrativeState(overdrive=0.40),
                embody_posture=True,
            )
        held = [body.scar for body in organism.bodies[:4]]
        for _ in range(130):
            organism.update(
                1.0 / 22.0,
                AudioForces(energy=0.20, level=0.20),
                44,
                18,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(openness=0.50, volatility=0.10),
                NarrativeState(cadence=0.90, resolution=0.40),
                embody_posture=True,
            )
        recovered = [body.scar for body in organism.bodies[:4]]

        self.assertGreater(organism.scar_state.shared, 0.0)
        self.assertEqual(held, marked)
        self.assertGreater(marked[2], marked[0])  # glint fractures first
        self.assertGreater(len({round(value, 3) for value in marked}), 3)
        self.assertTrue(all(after < before * 0.80 for before, after in zip(held, recovered)))

    def test_volume_scars_require_a_credible_rupture_not_any_interruption(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        organism.update(
            1.0 / 22.0,
            AudioForces(energy=0.45, level=0.45),
            44,
            18,
            LavaConfig(blobs=4),
            "buoyant",
            CELL_ASPECT,
            AffectiveState(volatility=0.70),
            NarrativeState(interruption=0.95, held_pressure=0.80),
            embody_posture=True,
        )

        self.assertEqual(organism.scar_state.shared, 0.0)
        self.assertEqual([body.scar for body in organism.bodies[:4]], [0.0] * 4)

    def test_fluid_path_does_not_create_volume_scars(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        organism.update(
            1.0 / 22.0,
            AudioForces(),
            44,
            18,
            LavaConfig(blobs=4),
            "buoyant",
            CELL_ASPECT,
            AffectiveState(volatility=0.70),
            NarrativeState(rupture=0.90, held_pressure=0.80),
        )

        self.assertEqual(organism.scar_state.shared, 0.0)
        self.assertEqual([body.scar for body in organism.bodies[:4]], [0.0] * 4)

    def test_volume_posture_embodies_group_space_and_independent_roles(self) -> None:
        config = LavaConfig(blobs=4)

        def run(affect: AffectiveState, story: NarrativeState = NarrativeState()):
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            for _ in range(80):
                organism.update(
                    1.0 / 22.0,
                    AudioForces(energy=0.25),
                    44,
                    18,
                    config,
                    "buoyant",
                    CELL_ASPECT,
                    affect,
                    story,
                    embody_posture=True,
                )
            center_x, center_y = organism.center_of_mass(4)
            spread = sum(
                math.hypot(body.x - center_x, body.y - center_y)
                for body in organism.bodies[:4]
            ) / 4.0
            radial = [math.hypot(body.x - center_x, body.y - center_y) for body in organism.bodies[:4]]
            angular = [
                abs(body.angular_yaw) + abs(body.angular_pitch) + abs(body.angular_roll)
                for body in organism.bodies[:4]
            ]
            return organism, spread, radial, angular

        neutral, neutral_spread, neutral_radial, _ = run(AffectiveState())
        tense, tense_spread, _, _ = run(
            AffectiveState(tension=0.85, restraint=0.80, weight=0.70),
            NarrativeState(expectation=0.50),
        )
        released, release_spread, release_radial, _ = run(
            AffectiveState(release=0.85, catharsis=0.82, openness=0.65),
            NarrativeState(resolution=0.60),
        )
        fractured, _, _, fracture_angular = run(
            AffectiveState(snap=0.90, volatility=0.80),
            NarrativeState(interruption=0.90),
        )

        # Shared weather changes the social space.
        self.assertLess(tense_spread, neutral_spread * 0.82)
        self.assertGreater(release_spread, tense_spread * 1.80)
        # The roles do not become aliases of one another.
        self.assertLess(tense.bodies[0].z, neutral.bodies[0].z)
        self.assertGreater(release_radial[3], neutral_radial[3] * 1.45)
        self.assertGreater(fracture_angular[2], fracture_angular[0] * 1.6)
        self.assertGreater(len({round(value, 3) for value in fracture_angular}), 3)
        self.assertTrue(all(0.08 <= body.z <= 0.92 for body in fractured.bodies[:4]))

    def test_bodies_keep_bounded_independent_depth_motion(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        starts = [body.z for body in organism.bodies]
        forces = AudioForces(bass=0.74, voice=0.62, energy=0.70, tempo=0.66)
        for _ in range(80):
            organism.update(
                1.0 / 22.0, forces, 44, 18, LavaConfig(blobs=4), "buoyant"
            )

        depths = [body.z for body in organism.bodies]
        self.assertTrue(all(0.08 <= depth <= 0.92 for depth in depths))
        self.assertTrue(any(abs(depth - start) > 0.015 for depth, start in zip(depths, starts)))
        self.assertGreater(len({round(depth, 3) for depth in depths}), 1)

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

    def test_confirmed_snap_breaks_the_group_open_without_spending_attention(self) -> None:
        config = LavaConfig(blobs=4)

        def run(affect: AffectiveState) -> tuple[float, list[float]]:
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            for _ in range(48):
                organism.update(
                    1.0 / 22.0,
                    AudioForces(energy=0.72),
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
            return spread, [body.spike for body in organism.bodies[:4]]

        ordinary_spread, _ = run(AffectiveState())
        snap_spread, spikes = run(AffectiveState(snap=0.86, catharsis=0.78))

        self.assertGreater(snap_spread, ordinary_spread * 1.25)
        self.assertEqual(spikes, [0.0] * 4)

    def test_narrative_context_reuses_contraction_and_release_motion(self) -> None:
        config = LavaConfig(blobs=4)

        def spread(narrative: NarrativeState) -> float:
            organism = AcousticOrganism(body_limit=4)
            organism.seed_for_tile(44, 18, 4)
            for _ in range(80):
                organism.update(
                    1.0 / 22.0,
                    AudioForces(energy=0.46),
                    44,
                    18,
                    config,
                    "buoyant",
                    CELL_ASPECT,
                    AffectiveState(),
                    narrative,
                )
            center_x, center_y = organism.center_of_mass(4)
            return sum(
                math.hypot(body.x - center_x, body.y - center_y)
                for body in organism.bodies[:4]
            ) / 4.0

        expected = spread(NarrativeState(expectation=0.88))
        interrupted = spread(NarrativeState(interruption=0.86, resolution=0.62))

        self.assertGreater(interrupted, expected * 1.35)

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

    def test_rapid_density_adds_flutter_without_spending_directional_spikes(self) -> None:
        config = LavaConfig(blobs=4)
        steady = AcousticOrganism(body_limit=4)
        rapid = AcousticOrganism(body_limit=4)
        steady.seed_for_tile(44, 18, 4)
        rapid.seed_for_tile(44, 18, 4)

        for index in range(36):
            steady.update(
                1.0 / 22.0,
                AudioForces(energy=0.62, tempo=0.72),
                44,
                18,
                config,
                "buoyant",
            )
            rapid.update(
                1.0 / 22.0,
                AudioForces(
                    energy=0.62,
                    tempo=0.72,
                    rhythm_density=0.82,
                    rhythm_impulse=0.48 if index % 3 == 0 else 0.0,
                ),
                44,
                18,
                config,
                "buoyant",
            )

        pose_delta = sum(
            abs(dense.x - plain.x)
            + abs(dense.y - plain.y)
            + abs(dense.stretch_x - plain.stretch_x)
            + abs(dense.stretch_y - plain.stretch_y)
            for plain, dense in zip(steady.bodies[:4], rapid.bodies[:4])
        )

        self.assertGreater(pose_delta, 0.08)
        self.assertEqual([body.spike for body in rapid.bodies[:4]], [0.0] * 4)

    def test_tile_composition_changes_topology_instead_of_only_scale(self) -> None:
        self.assertEqual(compose_tile(24, 10, 8).active_bodies, 3)
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
        self.assertEqual(field.composition.active_bodies, 3)
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

    def test_adaptive_centroid_leaves_middle_motion_free_and_bleeds_outward_momentum(self) -> None:
        self.assertEqual(adaptive_centroid_axis(0.66, 0.5, 0.12, 0.20), 0.0)
        self.assertEqual(adaptive_centroid_axis(0.34, 0.5, -0.12, 0.20), 0.0)

        right_outward = adaptive_centroid_axis(0.86, 0.5, 0.12, 0.20)
        right_inward = adaptive_centroid_axis(0.86, 0.5, -0.12, 0.20)
        left_outward = adaptive_centroid_axis(0.14, 0.5, -0.12, 0.20)

        self.assertLess(right_outward, right_inward)
        self.assertLess(right_inward, 0.0)
        self.assertAlmostEqual(left_outward, -right_outward)

    def test_wide_current_returns_as_a_group_after_sustained_edge_dwell(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        organism.seed_for_tile(90, 12, 4)
        for body in organism.bodies[:4]:
            body.x = min(0.90, max(0.66, body.x + 0.34))
            body.y = min(0.82, max(0.58, body.y + 0.18))
            body.vx = 0.12
            body.vy = 0.07
            body.presence = 1.0
        before_spacing = math.hypot(
            organism.bodies[0].x - organism.bodies[1].x,
            organism.bodies[0].y - organism.bodies[1].y,
        )

        sustained = AudioForces(
            bass=0.72,
            voice=0.48,
            energy=0.76,
            tempo=0.72,
            pulse=0.38,
            rhythm_density=0.66,
        )
        for _ in range(12):
            organism.update(1.0 / 22.0, sustained, 90, 12, config, "buoyant")
        brief_x, brief_y = organism.center_of_mass(4)

        for _ in range(648):
            organism.update(1.0 / 22.0, sustained, 90, 12, config, "buoyant")
        returned_x, returned_y = organism.center_of_mass(4)
        after_spacing = math.hypot(
            organism.bodies[0].x - organism.bodies[1].x,
            organism.bodies[0].y - organism.bodies[1].y,
        )

        self.assertGreater(brief_x, 0.70)
        self.assertGreater(brief_y, 0.66)
        self.assertLess(abs(returned_x - 0.5), abs(brief_x - 0.5))
        self.assertLess(abs(returned_y - 0.53), abs(brief_y - 0.53))
        self.assertLess(abs(returned_x - 0.5), 0.22)
        self.assertLess(abs(returned_y - 0.53), 0.22)
        self.assertGreater(after_spacing, before_spacing * 0.50)

    def test_first_viewport_seeds_the_cast_in_its_actual_habitat(self) -> None:
        field = LavaField()
        field.resize(18, 8)

        center_x, center_y = field.organism.center_of_mass(3)

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
                        if material_name == "volume":
                            rows = material.render(
                                field.bodies,
                                field.forces,
                                width,
                                height,
                                style,
                                field.phase,
                                CELL_ASPECT,
                            )
                            cells = [cell for row in rows for cell in row]
                        elif material_name == "wax":
                            rows = material.render(
                                field.wax,
                                width,
                                height,
                                style,
                                field.phase,
                                CELL_ASPECT,
                            )
                            cells = [cell for row in rows for cell in row]
                        else:
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

    def test_rotating_surface_faces_use_the_ordinary_palette_colors(self) -> None:
        self.assertEqual(_semantic_color_bucket(0.50, 0.0, 4, 0.10), 1)
        self.assertEqual(_semantic_color_bucket(0.50, 0.0, 4, 0.90), 2)
        self.assertEqual(_semantic_color_bucket(0.50, 0.20, 4, 0.10), 3)

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

    def test_listening_control_changes_context_without_resetting_bodies(self) -> None:
        config = load_config(None, None, "atlas")
        controls = _make_controls(config)
        ui = UiState()
        listening = controls["Listening"][0]

        message = listening.adjust(config, 1, ui)

        self.assertEqual(message, "listening: microphone")
        self.assertEqual(config.listening_context, "microphone")
        self.assertEqual(config.audio.capture_route, "microphone")
        self.assertFalse(ui.reset_lava)

    def test_compact_defaults_resolve_to_selected_direction(self) -> None:
        config = load_config(None, None, "atlas")
        config.content_mode = "speech"
        config.audio.analysis = "bands"
        config.audio.sample_rate = 22050
        config.audio.frame_size = 1024
        config = apply_cli_overrides(config, compact_tile=True, hide_stats=True)

        self.assertEqual(LavaField().motion_profile, "lavalamp")
        self.assertEqual(_scene_name_for_config(config), "soft-afterglow")
        self.assertEqual(_product_preset_name_for_config(config), "speech")
        self.assertEqual(config.lava.reactivity, 1.0)
        self.assertEqual(config.fps, 22)


class ThermalVolumeTests(unittest.TestCase):
    @staticmethod
    def _run_thermal_pass(
        forces: AudioForces, story: NarrativeState, *, bodies: int = 1
    ) -> AcousticOrganism:
        organism = AcousticOrganism(body_limit=bodies)
        for index, body in enumerate(organism.bodies[:bodies]):
            body.x = 0.45 + index * 0.10
            body.y = 0.58
            body.vx = body.vy = 0.0
            body.presence = 1.0
        config = LavaConfig(blobs=bodies, drift=0.12, viscosity=0.90)
        for _ in range(72):
            organism.update(
                1.0 / 12.0,
                forces,
                80,
                24,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(cohesion=0.90),
                story,
                None,
                True,
            )
        return organism

    def test_sustained_pressure_warms_and_lifts_volume_wax_above_cold_wax(self) -> None:
        cold = self._run_thermal_pass(AudioForces(), NarrativeState())
        hot = self._run_thermal_pass(
            AudioForces(bass=0.90, energy=0.80, bands=(0.70,) * 8),
            NarrativeState(held_pressure=0.80, cadence=0.60),
        )
        cold_body = cold.bodies[0]
        hot_body = hot.bodies[0]

        self.assertTrue(hot_body.thermal_active)
        self.assertGreater(hot_body.thermal_heat, cold_body.thermal_heat + 0.50)
        self.assertLess(hot_body.thermal_viscosity, cold_body.thermal_viscosity)
        self.assertLess(hot_body.y, cold_body.y - 0.10)

    def test_nearby_warm_volume_bodies_form_a_bounded_mutual_bridge(self) -> None:
        organism = self._run_thermal_pass(
            AudioForces(bass=0.90, energy=0.80, bands=(0.70,) * 8),
            NarrativeState(held_pressure=0.80, cadence=0.70),
            bodies=2,
        )
        first, second = organism.bodies[:2]

        self.assertGreater(first.bridge_strength, 0.35)
        self.assertGreater(second.bridge_strength, 0.35)
        self.assertGreater(first.adhesion, 0.35)
        self.assertGreater(second.adhesion, 0.35)
        self.assertLessEqual(first.bridge_strength, 1.0)
        self.assertLessEqual(second.bridge_strength, 1.0)
        self.assertAlmostEqual(
            abs(math.sin(first.bridge_angle - second.bridge_angle)), 0.0, places=3
        )

    def test_thermal_anchors_compress_each_role_into_the_central_vessel(self) -> None:
        composition = compose_tile(80, 24, 4)
        organism = AcousticOrganism(body_limit=4)
        compression = []
        anchors = {}
        for index, body in enumerate(organism.bodies[:4]):
            broad = habitat_anchor(composition, index, 0.0)
            thermal = thermal_habitat_anchor(
                composition, index, 0.0, body.character.name
            )
            broad_distance = math.hypot(broad[0] - 0.5, broad[1] - 0.52)
            thermal_distance = math.hypot(thermal[0] - 0.5, thermal[1] - 0.52)
            compression.append(thermal_distance / broad_distance)
            anchors[body.character.name] = thermal

        self.assertTrue(all(0.80 <= ratio <= 0.90 for ratio in compression))
        self.assertTrue(0.82 <= sum(compression) / len(compression) <= 0.88)
        self.assertGreater(anchors["ballast"][1], anchors["listener"][1] + 0.12)
        self.assertLess(anchors["glint"][1], 0.47)
        self.assertGreater(abs(anchors["glint"][0] - 0.5), 0.16)
        listener_distance = math.hypot(
            anchors["listener"][0] - 0.5, anchors["listener"][1] - 0.52
        )
        self.assertEqual(
            listener_distance,
            min(math.hypot(x - 0.5, y - 0.52) for x, y in anchors.values()),
        )
        later_drifter = thermal_habitat_anchor(composition, 3, 4.0, "drifter")
        self.assertGreater(math.dist(anchors["drifter"], later_drifter), 0.015)

    def test_cooling_thickens_settles_and_releases_pressure_history(self) -> None:
        organism = self._run_thermal_pass(
            AudioForces(bass=0.90, energy=0.80, bands=(0.70,) * 8),
            NarrativeState(held_pressure=0.80, cadence=0.60),
        )
        body = organism.bodies[0]
        warm_y = body.y
        warm_heat = body.thermal_heat
        warm_viscosity = body.thermal_viscosity
        warm_pressure = body.pressure_memory
        config = LavaConfig(blobs=1, drift=0.12, viscosity=0.90)

        for _ in range(120):
            organism.update(
                1.0 / 12.0,
                AudioForces(),
                80,
                24,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(),
                NarrativeState(),
                None,
                True,
            )

        self.assertLess(body.thermal_heat, warm_heat - 0.60)
        self.assertGreater(body.thermal_viscosity, warm_viscosity + 0.20)
        self.assertGreater(body.y, warm_y + 0.035)
        self.assertGreater(warm_pressure, 0.10)
        self.assertLess(body.pressure_memory, warm_pressure * 0.02)

    def test_fast_volume_hit_disturbs_only_its_authored_target(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        strike = AudioForces(
            transient=0.92,
            tone=0.92,
            hits=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.96),
        )

        organism.update(
            1.0 / 22.0,
            strike,
            80,
            24,
            config,
            "buoyant",
            CELL_ASPECT,
            AffectiveState(),
            NarrativeState(),
            None,
            True,
        )

        disturbed = [body for body in organism.bodies[:4] if body.afterglow >= 0.80]
        self.assertEqual(len(disturbed), 1)
        self.assertLess(
            max(body.thermal_heat for body in organism.bodies[:4])
            - min(body.thermal_heat for body in organism.bodies[:4]),
            0.001,
        )

    def test_volume_keeps_nonbridged_cores_separated_during_sustained_heat(self) -> None:
        organism = self._run_thermal_pass(
            AudioForces(bass=0.90, energy=0.80, bands=(0.70,) * 8),
            NarrativeState(held_pressure=0.80, cadence=0.70),
            bodies=4,
        )
        axis_x, axis_y = tile_axis_scales(80, 24, CELL_ASPECT)
        bridge = organism.dominant_bridge

        for left in range(4):
            for right in range(left + 1, 4):
                if bridge == (left, right):
                    continue
                first = organism.bodies[left]
                second = organism.bodies[right]
                distance = math.hypot(
                    (second.x - first.x) / axis_x,
                    (second.y - first.y) / axis_y,
                )
                readable = (first.radius + second.radius) * 1.04 * 0.90
                self.assertGreaterEqual(distance, readable)

    def test_volume_preserves_authored_identity_phase_and_independent_motion(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        names = tuple(body.character.name for body in organism.bodies[:4])
        phases = tuple(body.phase for body in organism.bodies[:4])
        config = LavaConfig(blobs=4, drift=0.12, viscosity=0.90)
        forces = AudioForces(bass=0.78, voice=0.55, energy=0.66, bands=(0.48,) * 8)

        for _ in range(96):
            organism.update(
                1.0 / 22.0,
                forces,
                80,
                24,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(cohesion=0.72),
                NarrativeState(held_pressure=0.62, cadence=0.50),
                None,
                True,
            )

        self.assertEqual(tuple(body.character.name for body in organism.bodies[:4]), names)
        self.assertEqual(tuple(body.phase for body in organism.bodies[:4]), phases)
        motion = {
            (round(body.vx, 4), round(body.vy, 4), round(body.z, 3))
            for body in organism.bodies[:4]
        }
        self.assertEqual(len(motion), 4)

    def test_volume_caps_pairwise_cast_without_changing_fluid_population(self) -> None:
        volume = AcousticOrganism(body_limit=8)
        volume_composition = volume.update(
            1.0 / 22.0,
            AudioForces(),
            120,
            40,
            LavaConfig(blobs=8),
            embody_posture=True,
        )
        fluid = AcousticOrganism(body_limit=8)
        fluid_composition = fluid.update(
            1.0 / 22.0,
            AudioForces(),
            120,
            40,
            LavaConfig(blobs=8),
            embody_posture=False,
        )

        self.assertEqual(volume_composition.active_bodies, 4)
        self.assertEqual(fluid_composition.active_bodies, 6)

    def test_only_one_warm_bridge_pair_is_active_and_cooling_releases_it(self) -> None:
        organism = self._run_thermal_pass(
            AudioForces(bass=0.90, energy=0.80, bands=(0.70,) * 8),
            NarrativeState(held_pressure=0.80, cadence=0.70),
            bodies=4,
        )
        bridged = [body for body in organism.bodies[:4] if body.bridge_strength >= 0.08]

        self.assertIsNotNone(organism.dominant_bridge)
        self.assertEqual(len(bridged), 2)

        config = LavaConfig(blobs=4, drift=0.12, viscosity=0.90)
        for _ in range(72):
            organism.update(
                1.0 / 12.0,
                AudioForces(),
                80,
                24,
                config,
                "buoyant",
                CELL_ASPECT,
                AffectiveState(),
                NarrativeState(),
                None,
                True,
            )

        self.assertIsNone(organism.dominant_bridge)
        self.assertTrue(
            all(body.bridge_strength < 0.02 for body in organism.bodies[:4])
        )

    def test_volume_selects_the_strongest_nearby_warm_bridge_pair(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        positions = ((0.40, 0.50), (0.51, 0.50), (0.68, 0.50), (0.78, 0.72))
        heats = (0.95, 0.95, 0.68, 0.18)
        for body, (x, y), heat in zip(organism.bodies[:4], positions, heats):
            body.x = x
            body.y = y
            body.radius = body.base_radius = 0.09
            body.thermal_heat = heat

        organism.update(
            1.0 / 120.0,
            AudioForces(),
            80,
            24,
            LavaConfig(blobs=4),
            embody_posture=True,
        )

        self.assertEqual(organism.dominant_bridge, (0, 1))
        bridged = [
            index
            for index, body in enumerate(organism.bodies[:4])
            if body.bridge_strength > 0.0
        ]
        self.assertEqual(bridged, [0, 1])

    def test_thermal_state_is_inactive_for_the_existing_fluid_text_physics_path(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        organism.update(
            1.0 / 12.0,
            AudioForces(bass=0.90, energy=0.80, transient=0.90, bands=(0.70,) * 8),
            80,
            24,
            config,
            "buoyant",
            CELL_ASPECT,
            AffectiveState(),
            NarrativeState(held_pressure=0.80),
            None,
            False,
        )

        self.assertIsNone(organism.dominant_bridge)
        self.assertTrue(all(not body.thermal_active for body in organism.bodies[:4]))
        self.assertTrue(
            all(body.flow_memory_x == body.flow_memory_y == 0.0 for body in organism.bodies[:4])
        )


class RadioSpeechEmbodimentTests(unittest.TestCase):
    @staticmethod
    def _advance(
        organism: AcousticOrganism, forces: AudioForces, frames: int
    ) -> None:
        for _ in range(frames):
            organism.update(
                1.0 / 12.0,
                forces,
                80,
                24,
                LavaConfig(blobs=3),
                "buoyant",
                CELL_ASPECT,
                AffectiveState(),
                NarrativeState(),
                behavior_for_context("radio"),
            )

    def test_radio_assigns_one_stable_speaker_while_other_bodies_listen(self) -> None:
        organism = AcousticOrganism(body_limit=3)
        speech = AudioForces(
            voice=0.82,
            detail=0.42,
            tone=0.43,
            bands=(0.05, 0.12, 0.62, 0.85, 0.70, 0.18, 0.06, 0.03),
        )
        self._advance(organism, speech, 36)
        speaker = organism.speech_state.speaker_index
        bodies = organism.bodies[:3]

        self.assertEqual(speaker, 1)
        self.assertGreater(bodies[speaker].speech_flow, 0.65)
        self.assertTrue(
            all(
                body.listening > 0.45
                for index, body in enumerate(bodies)
                if index != speaker
            )
        )
        self.assertGreater(
            bodies[speaker].stretch_x,
            bodies[0].stretch_x,
        )

    def test_radio_requires_sustained_timbre_change_before_a_speaker_handoff(self) -> None:
        organism = AcousticOrganism(body_limit=3)
        listener_voice = AudioForces(voice=0.80, tone=0.43, bands=(0.10, 0.20, 0.60, 0.82, 0.68, 0.18, 0.04, 0.02))
        glint_voice = AudioForces(voice=0.80, tone=0.88, bands=(0.05, 0.08, 0.16, 0.28, 0.44, 0.66, 0.88, 0.70))
        self._advance(organism, listener_voice, 24)
        self.assertEqual(organism.speech_state.speaker_index, 1)

        self._advance(organism, glint_voice, 20)
        self.assertEqual(organism.speech_state.speaker_index, 1)
        self._advance(organism, glint_voice, 8)
        self.assertEqual(organism.speech_state.speaker_index, 2)

    def test_radio_pause_releases_the_speaking_body_without_a_global_hit(self) -> None:
        organism = AcousticOrganism(body_limit=3)
        speech = AudioForces(voice=0.82, detail=0.42, tone=0.43, bands=(0.05, 0.12, 0.62, 0.85, 0.70, 0.18, 0.06, 0.03))
        self._advance(organism, speech, 24)
        speaker = organism.speech_state.speaker_index
        self._advance(organism, AudioForces(), 8)

        self.assertGreater(organism.speech_state.pause_release, 0.20)
        self.assertLess(organism.speech_state.voice_flow, 0.10)
        self.assertLess(organism.bodies[speaker].speech_flow, 0.45)
        self.assertTrue(all(body.spike == 0.0 for body in organism.bodies[:3]))


class FluidSurfaceRippleTests(unittest.TestCase):
    def test_hit_injects_a_surface_wave_that_coasts_without_moving_the_cast(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        config = LavaConfig(blobs=4)
        impact = AudioForces(
            transient=0.94,
            rhythm_impulse=0.80,
            tone=0.35,
            bands=(0.82, 0.64, 0.34, 0.22, 0.14, 0.08, 0.04, 0.02),
            hits=(0.92, 0.56, 0.18, 0.08, 0.04, 0.02, 0.01, 0.01),
        )
        organism.update(
            1.0 / 22.0,
            impact,
            44,
            18,
            config,
            "buoyant",
            surface_ripples=True,
        )
        wave_body = max(organism.bodies[:4], key=lambda body: body.surface_ripple)
        before_phase = wave_body.surface_ripple_phase
        before_wave = wave_body.surface_ripple
        before_position = (wave_body.x, wave_body.y)

        organism.update(
            1.0 / 22.0,
            AudioForces(),
            44,
            18,
            config,
            "buoyant",
            surface_ripples=True,
        )

        self.assertTrue(wave_body.surface_ripples_active)
        self.assertLessEqual(wave_body.spike, 0.10)
        self.assertGreater(wave_body.surface_ripple_phase, before_phase)
        self.assertGreater(wave_body.surface_ripple, 0.0)
        self.assertLess(wave_body.surface_ripple, before_wave)
        self.assertLess(math.dist(before_position, (wave_body.x, wave_body.y)), 0.015)


if __name__ == "__main__":
    unittest.main()
