from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lavatune.app import (
    FrameScheduler,
    UiState,
    _changed_cell_runs,
    _changed_sparse_runs,
    _compute_layout,
    _effective_cell_width,
    _effective_fps,
    _init_colors,
    _palette_attr,
    _should_draw_early,
)
from lavatune.audio import AudioFrame
from lavatune.organism import AffectiveState, AudioForces


def config(**render_values):
    return SimpleNamespace(render=SimpleNamespace(**render_values))


class LayoutTests(unittest.TestCase):
    def test_activity_driven_cadence_spends_frames_only_when_needed(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        silence = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 0.0)
        speech = AudioFrame(0.05, [0.08] * 8, 0.03, 0.05, 0.0)
        music = AudioFrame(0.18, [0.24] * 8, 0.04, 0.12, 0.0)
        transient = AudioFrame(0.20, [0.24] * 8, 0.30, 0.12, 0.0)

        self.assertEqual(_effective_fps(app_config, silence), 2.0)
        self.assertEqual(_effective_fps(app_config, speech), 4.0)
        self.assertEqual(_effective_fps(app_config, music), 8.0)
        self.assertEqual(_effective_fps(app_config, transient), 14.0)
        app_config.profile = "power-save"
        self.assertEqual(_effective_fps(app_config, transient), 6.0)

    def test_mapped_gesture_keeps_afterglow_at_an_active_cadence(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        silence = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 0.0)

        self.assertEqual(
            _effective_fps(app_config, silence, AudioForces(transient=0.30)),
            14.0,
        )

    def test_scheduler_holds_engaged_state_after_a_short_burst(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        scheduler = FrameScheduler(immediate=False)
        frame = AudioFrame(0.20, [0.24] * 8, 0.30, 0.12, 10.0)

        scheduler.observe(
            frame,
            AudioForces(transient=0.40, energy=0.50),
            AffectiveState(novelty=0.30),
            0.40,
            10.0,
        )

        self.assertEqual(scheduler.target_fps(app_config, 10.1), 14.0)
        self.assertEqual(scheduler.physics_fps(10.1), 8.0)
        self.assertEqual(scheduler.target_fps(app_config, 10.3), 8.0)
        self.assertTrue(scheduler.consume_immediate())
        self.assertEqual(scheduler.target_fps(app_config, 10.8), 2.0)

    def test_scheduler_treats_rapid_pattern_density_as_a_short_burst(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        scheduler = FrameScheduler(immediate=False)
        quiet = AudioFrame(0.02, [0.03] * 8, 0.0, 0.04, 10.0)

        scheduler.observe(
            quiet,
            AudioForces(rhythm_density=0.70, rhythm_impulse=0.55),
            AffectiveState(),
            0.55,
            10.0,
        )

        self.assertEqual(scheduler.target_fps(app_config, 10.1), 14.0)
        self.assertEqual(scheduler.physics_fps(10.1), 8.0)

    def test_confirmed_snap_starts_one_bounded_burst(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        scheduler = FrameScheduler(immediate=False)
        quiet = AudioFrame(0.02, [0.03] * 8, 0.0, 0.04, 10.0)

        scheduler.observe(quiet, AudioForces(), AffectiveState(snap=0.82), 0.0, 10.0)
        first_until = scheduler.burst_until
        scheduler.observe(quiet, AudioForces(), AffectiveState(snap=0.68), 0.0, 10.1)

        self.assertEqual(scheduler.target_fps(app_config, 10.1), 14.0)
        self.assertEqual(first_until, 10.22)
        self.assertEqual(scheduler.burst_until, first_until)

    def test_sustained_release_does_not_extend_burst_forever(self) -> None:
        app_config = SimpleNamespace(fps=22, profile="atlas")
        scheduler = FrameScheduler(immediate=False)
        quiet = AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, 10.0)

        scheduler.observe(quiet, AudioForces(), AffectiveState(release=0.30), 0.0, 10.0)
        scheduler.observe(quiet, AudioForces(), AffectiveState(release=0.28), 0.0, 10.2)
        scheduler.observe(quiet, AudioForces(), AffectiveState(release=0.24), 0.0, 10.4)

        self.assertEqual(scheduler.burst_until, 10.22)
        self.assertEqual(scheduler.target_fps(app_config, 10.5), 8.0)
        self.assertEqual(scheduler.target_fps(app_config, 10.8), 2.0)

    def test_faster_audio_cadence_can_wake_a_quiet_deadline(self) -> None:
        self.assertTrue(_should_draw_early(10.30, 10.0, 10.0))
        self.assertFalse(_should_draw_early(10.05, 10.0, 10.0))

    def test_dirty_cell_runs_skip_unchanged_terminal_content(self) -> None:
        previous = (("a", 1), ("b", 1), ("c", 2), ("d", 2))
        current = (("a", 1), ("B", 1), ("c", 3), (" ", 0))

        self.assertEqual(
            _changed_cell_runs(previous, current),
            [(1, "B", 1), (2, "c", 3), (3, " ", 0)],
        )

    def test_sparse_runs_clear_old_contours_without_scanning_blank_rows(self) -> None:
        previous = {(2, 3): ("█", 1), (2, 4): ("█", 1), (8, 9): ("▘", 2)}
        current = {(2, 4): ("█", 1), (2, 5): ("▐", 2)}

        self.assertEqual(
            _changed_sparse_runs(previous, current, 0),
            [(2, 3, " ", 0), (2, 5, "▐", 2), (8, 9, " ", 0)],
        )

    def test_palette_initialization_respects_terminal_pair_capacity(self) -> None:
        with (
            patch("lavatune.app.curses.start_color"),
            patch("lavatune.app.curses.use_default_colors"),
            patch("lavatune.app.curses.COLORS", 8, create=True),
            patch("lavatune.app.curses.COLOR_PAIRS", 5, create=True),
            patch("lavatune.app.curses.init_pair") as init_pair,
            patch("lavatune.app.curses.color_pair", side_effect=lambda pair_id: pair_id),
        ):
            _init_colors()

            self.assertEqual(init_pair.call_count, 4)
            self.assertEqual(_palette_attr("soft-afterglow", 3), 4)
            self.assertEqual(_palette_attr("oxide", 3), 4)

    def test_compact_side_layout_uses_available_tile_and_keeps_dock_adjacent(self) -> None:
        layout = _compute_layout(40, 120, True, config(compact=True))

        self.assertEqual(layout.vis_w, 82)
        self.assertEqual(layout.vis_h, 39)
        self.assertEqual(layout.dock_x, 82)
        self.assertEqual(layout.side, "right")

    def test_explicit_visual_limits_still_clamp_visual_and_dock_width(self) -> None:
        layout = _compute_layout(32, 80, True, config(compact=True, max_width=40, max_height=10))

        self.assertEqual(layout.vis_w, 40)
        self.assertEqual(layout.vis_h, 10)
        self.assertEqual(layout.dock_y, 10)
        self.assertEqual(layout.dock_w, 40)
        self.assertEqual(layout.side, "bottom")

    def test_regular_layout_still_uses_available_terminal(self) -> None:
        layout = _compute_layout(32, 80, True, config(compact=False))

        self.assertEqual(layout.vis_w, 80)
        self.assertEqual(layout.vis_h, 19)

    def test_compact_cell_width_autoscales_to_tile_area(self) -> None:
        self.assertEqual(_effective_cell_width(config(compact=True, scale=4), 44, 12), 1)
        self.assertEqual(_effective_cell_width(config(compact=True, scale=4), 82, 39), 4)
        self.assertEqual(_effective_cell_width(config(compact=False, scale=4), 82, 39), 4)

    def test_generic_environment_setting_controls_target_density(self) -> None:
        with patch.dict(os.environ, {"LAVATUNE_TARGET_CELLS": "180"}):
            self.assertEqual(_effective_cell_width(config(compact=True, scale=4), 82, 39), 5)

    def test_codexdeck_environment_setting_remains_compatible(self) -> None:
        with patch.dict(os.environ, {"CODEXDECK_LAVATUNE_TARGET_CELLS": "180"}):
            self.assertEqual(_effective_cell_width(config(compact=True, scale=4), 82, 39), 5)

    def test_short_hidden_dock_tile_uses_every_available_row(self) -> None:
        layout = _compute_layout(8, 20, False, config(compact=True))

        self.assertEqual(layout.vis_h, 7)
        self.assertEqual(layout.vis_w, 20)
        self.assertEqual(layout.dock_h, 0)
        self.assertEqual(layout.dock_w, 0)
        self.assertEqual(layout.side, "hidden")

    def test_controls_start_backstage(self) -> None:
        self.assertFalse(UiState().dock_open)

    def test_short_open_dock_collapses_to_preserve_visual(self) -> None:
        layout = _compute_layout(8, 20, True, config(compact=True))

        self.assertEqual(layout.vis_h, 6)
        self.assertEqual(layout.dock_h, 1)


if __name__ == "__main__":
    unittest.main()
