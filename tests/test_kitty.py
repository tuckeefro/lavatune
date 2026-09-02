from __future__ import annotations

import io
import unittest

from lavatune.kitty import (
    ImplicitWaxRenderer,
    KittyGraphicsWriter,
    PixelFrame,
    _parse_cell_size_response,
    _render_size,
    _smooth_density,
    kitty_graphics_supported,
)
from lavatune.wax import WAX_WIDTH, WaxState


class KittyRendererTests(unittest.TestCase):
    def test_terminal_detection_is_explicit_and_forceable(self) -> None:
        self.assertTrue(kitty_graphics_supported({"TERM_PROGRAM": "ghostty"}))
        self.assertTrue(kitty_graphics_supported({"TERM": "xterm-kitty"}))
        self.assertTrue(kitty_graphics_supported({"LAVATUNE_KITTY_FORCE": "1"}))
        self.assertFalse(kitty_graphics_supported({"TERM": "xterm-256color"}))

    def test_renderer_produces_truecolor_pixels_from_conserved_wax(self) -> None:
        state = WaxState()
        frame = ImplicitWaxRenderer().render(state, 120, 72)

        self.assertEqual((frame.width, frame.height), (120, 72))
        self.assertEqual(len(frame.rgb), 120 * 72 * 3)
        triplets = [
            frame.rgb[index : index + 3] for index in range(0, len(frame.rgb), 3)
        ]
        self.assertLess(min(sum(pixel) for pixel in triplets), 60)
        self.assertGreater(max(sum(pixel) for pixel in triplets), 120)

    def test_renderer_smoothing_does_not_mutate_wax_state(self) -> None:
        state = WaxState()
        before = tuple(state.density)
        smoothed = _smooth_density(state)

        self.assertEqual(tuple(state.density), before)
        self.assertEqual(len(smoothed), len(state.density))
        self.assertNotEqual(tuple(smoothed), before)

    def test_xtwinops_cell_size_response_is_parsed_in_width_height_order(self) -> None:
        self.assertEqual(_parse_cell_size_response(b"\x1b[6;19;10t"), (10, 19))
        self.assertIsNone(_parse_cell_size_response(b"\x1b[8;40;120t"))

    def test_render_size_preserves_the_physical_terminal_grid_aspect(self) -> None:
        width, height = _render_size(120, 40, 10, 20)

        self.assertLessEqual(width, 320)
        self.assertLessEqual(height, 192)
        self.assertAlmostEqual(width / height, (120 * 10) / (40 * 20), delta=0.01)

    def test_renderer_maps_the_complete_wax_domain_across_the_framebuffer(self) -> None:
        renderer = ImplicitWaxRenderer()
        renderer._prepare_geometry(320, 192)

        self.assertEqual(renderer._projection_x, 1.0)
        self.assertIsNotNone(renderer._sample_x[0])
        self.assertIsNotNone(renderer._sample_x[-1])
        self.assertLess(float(renderer._sample_x[0]), 1.0)
        self.assertGreater(float(renderer._sample_x[-1]), WAX_WIDTH - 2.0)

    def test_protocol_writer_fills_grid_without_moving_terminal_cursor(self) -> None:
        stream = io.BytesIO()
        writer = KittyGraphicsWriter(stream)
        writer.display(PixelFrame(2, 1, b"\x10\x20\x30\x40\x50\x60"), 20, 8)
        payload = stream.getvalue()

        self.assertIn(b"\x1b_Ga=T,f=24,s=2,v=1,o=z,t=d", payload)
        self.assertIn(b"i=719,p=1,c=20,r=8", payload)
        self.assertIn(b"C=1,N=1,q=1", payload)
        self.assertTrue(payload.endswith(b"\x1b\\"))


if __name__ == "__main__":
    unittest.main()