from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lavatune.app import (
    UiState,
    _compute_layout,
    _effective_cell_width,
    _init_colors,
    _palette_attr,
)


def config(**render_values):
    return SimpleNamespace(render=SimpleNamespace(**render_values))


class LayoutTests(unittest.TestCase):
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
