from __future__ import annotations

import unittest
from unittest.mock import patch

from lavatune.config import AppConfig
from lavatune.kitty_v2 import PhotographicWaxRenderer, _blur, main
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

    def test_dark_room_background_has_strong_wax_contrast(self) -> None:
        state = WaxState()
        frame = PhotographicWaxRenderer().render(state, 120, 72)
        triplets = [
            frame.rgb[index : index + 3] for index in range(0, len(frame.rgb), 3)
        ]
        luminance = [sum(pixel) for pixel in triplets]

        # Keep the background genuinely dark while avoiding a brittle exact
        # black-level contract that would turn photographic tuning into test
        # chasing. The important invariant is strong subject/background
        # separation.
        self.assertLess(min(luminance), 100)
        self.assertGreater(max(luminance), 120)
        self.assertGreater(max(luminance) - min(luminance), 50)

    def test_standalone_launcher_uses_current_config_signature(self) -> None:
        config = AppConfig()
        with (
            patch("sys.argv", ["python -m lavatune.kitty_v2", "--demo"]),
            patch("lavatune.kitty_v2.preference_path", return_value="/tmp/preferences.json"),
            patch("lavatune.kitty_v2.load_config", return_value=config) as load_config,
            patch("lavatune.kitty_v2.run_photographic", return_value=17) as run_photographic,
        ):
            self.assertEqual(main(), 17)

        args, kwargs = load_config.call_args
        self.assertEqual(args, (None, None))
        self.assertEqual(kwargs["saved_preferences"], "/tmp/preferences.json")
        run_photographic.assert_called_once_with(config, True)


if __name__ == "__main__":
    unittest.main()
