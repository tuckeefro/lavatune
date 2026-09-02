from __future__ import annotations

import io
import unittest

from lavatune.kitty import (
    ImplicitWaxRenderer,
    KittyGraphicsWriter,
    PixelFrame,
    _smooth_density,
    kitty_graphics_supported,
)
from lavatune.wax import WaxState


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

    def test_protocol_writer_uses_compressed_rgb_and_one_fixed_placement(self) -> None:
        stream = io.BytesIO()
        writer = KittyGraphicsWriter(stream)
        writer.display(PixelFrame(2, 1, b"\x10\x20\x30\x40\x50\x60"), 20, 8)
        payload = stream.getvalue()

        self.assertIn(b"\x1b_Ga=T,f=24,s=2,v=1,o=z,t=d", payload)
        self.assertIn(b"i=719,p=1,c=20,r=8", payload)
        self.assertIn(b"N=1,q=1", payload)
        self.assertTrue(payload.endswith(b"\x1b\\"))


if __name__ == "__main__":
    unittest.main()
