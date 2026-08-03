from __future__ import annotations

import unittest

from lavatune.app import LavaField
from lavatune.organism import AudioForces
from lavatune.runtime import LavaField as RuntimeLavaField


class PresentationFrameTests(unittest.TestCase):
    def test_app_reexports_the_renderer_neutral_runtime_field(self) -> None:
        self.assertIs(LavaField, RuntimeLavaField)

    def test_lava_field_exposes_the_live_organism_world_as_one_read_only_frame(self) -> None:
        field = LavaField()
        field.resize(80, 24)
        field.render_forces = AudioForces(bass=0.42)
        field.phase = 1.25

        presentation = field.presentation_frame()

        self.assertIsInstance(presentation.bodies, tuple)
        self.assertEqual(presentation.bodies, tuple(field.bodies))
        self.assertEqual(presentation.forces.bass, 0.42)
        self.assertEqual(presentation.phase, 1.25)


if __name__ == "__main__":
    unittest.main()
