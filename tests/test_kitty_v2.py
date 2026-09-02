from __future__ import annotations

import unittest

from lavatune.kitty_v2 import PhotographicWaxRenderer, _blur
from lavatune.wax import WaxState


class PhotographicWaxRendererTests(unittest.TestCase):
    def test_renderer_produces_rgb_without_mutating_wax(self) -> None:
        state = WaxState()
        before_density = tuple(state.density)
        before_heat = tuple(state.heat)

        frame = PhotographicWaxRenderer().render(state, 120, 72)

        self.assertEqual((frame.width, frame.height), (120, 72))
        self.assertEqual(len(frame.rgb), 120 * 72 * 3)
        self.assertEqual(tuple(state.density), before_density)
        self.assertEqual(tuple(state.heat), before_heat)

    def test_spatial_reconstruction_is_renderer_only(self) -> None:
        state = WaxState()
        before = tuple(state.density)
        blurred = _blur(state.density)

        self.assertEqual(tuple(state.density), before)
        self.assertEqual(len(blurred), len(state.density))
        self.assertNotEqual(tuple(blurred), before)

    def test_temporal_reconstruction_changes_display_history_not_wax(self) -> None:
        state = WaxState()
        renderer = PhotographicWaxRenderer()
        first = renderer.render(state, 120, 72)
        before = tuple(state.density)
        # Renderer history is allowed to settle independently of physics.
        second = renderer.render(state, 120, 72)

        self.assertEqual(tuple(state.density), before)
        self.assertEqual(len(first.rgb), len(second.rgb))

    def test_dark_room_background_remains_darker_than_wax(self) -> None:
        state = WaxState()
        frame = PhotographicWaxRenderer().render(state, 120, 72)
        triplets = [
            frame.rgb[index : index + 3] for index in range(0, len(frame.rgb), 3)
        ]
        luminance = [sum(pixel) for pixel in triplets]

        self.assertLess(min(luminance), 70)
        self.assertGreater(max(luminance), 120)


if __name__ == "__main__":
    unittest.main()
