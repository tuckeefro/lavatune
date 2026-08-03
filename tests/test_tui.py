"""Presentation-boundary compatibility tests."""

from __future__ import annotations

import unittest

from lavatune.app import (
    Button,
    Control,
    Layout,
    UiState,
    VisualCache,
    _clamp_visual_size,
    _compact_layout,
    _compute_layout,
    _effective_cell_width,
    _safe_add,
    _visual_limits,
)
from lavatune.tui import (
    Button as TuiButton,
    Control as TuiControl,
    Layout as TuiLayout,
    UiState as TuiState,
    VisualCache as TuiVisualCache,
    clamp_visual_size,
    compact_layout,
    compute_layout,
    effective_cell_width,
    safe_add,
    visual_limits,
)


class TuiBoundaryTests(unittest.TestCase):
    def test_app_reexports_terminal_ui_contract(self) -> None:
        self.assertIs(Button, TuiButton)
        self.assertIs(Control, TuiControl)
        self.assertIs(Layout, TuiLayout)
        self.assertIs(UiState, TuiState)
        self.assertIs(VisualCache, TuiVisualCache)
        self.assertIs(_safe_add, safe_add)
        self.assertIs(_clamp_visual_size, clamp_visual_size)
        self.assertIs(_compact_layout, compact_layout)
        self.assertIs(_compute_layout, compute_layout)
        self.assertIs(_effective_cell_width, effective_cell_width)
        self.assertIs(_visual_limits, visual_limits)
