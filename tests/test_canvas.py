from __future__ import annotations

import math
import unittest

from lavatune.canvas import (
    CORE_POINTS,
    LOBE_POINTS,
    project_organism,
    project_organisms,
    project_presentation,
)
from lavatune.organism import AcousticOrganism, AudioForces
from lavatune.presentation import PresentationFrame


class CanvasProjectionTests(unittest.TestCase):
    def _body(self):
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = 0.5
        body.y = 0.5
        body.z = 0.50
        body.radius = 0.20
        body.presence = 1.0
        body.yaw = 0.45
        body.roll = 0.10
        return body

    def test_canvas_projection_uses_two_fixed_local_surfaces(self) -> None:
        organism = AcousticOrganism(body_limit=4)
        for index, body in enumerate(organism.bodies[:4]):
            body.x = 0.20 + index * 0.18
            body.y = 0.5
            body.z = 0.20 + index * 0.18
            body.radius = 0.16
            body.presence = 1.0

        projected = project_organisms(organism.bodies, AudioForces(), 960, 640)

        self.assertEqual(len(projected), 4)
        self.assertEqual([item.depth for item in projected], sorted(item.depth for item in projected))
        self.assertTrue(all(len(item.core) == CORE_POINTS for item in projected))
        self.assertTrue(all(len(item.lobe) == LOBE_POINTS for item in projected))

    def test_canvas_spike_extends_toward_the_impact(self) -> None:
        def lobe_bounds(angle: float) -> tuple[float, float, float, float]:
            body = self._body()
            body.spike = 0.90
            body.impact_angle = angle
            projected = project_organism(
                body, AudioForces(transient=0.88, pulse=0.72), 960, 640
            )
            return (
                min(x for x, _ in projected.lobe),
                max(x for x, _ in projected.lobe),
                min(y for _, y in projected.lobe),
                max(y for _, y in projected.lobe),
            )

        right = lobe_bounds(0.0)
        down = lobe_bounds(math.pi / 2.0)

        self.assertGreater(right[1], down[1])
        self.assertGreater(down[3], right[3])

    def test_canvas_can_consume_the_renderer_neutral_presentation_frame(self) -> None:
        organism = AcousticOrganism(body_limit=1)
        body = organism.bodies[0]
        body.x = body.y = body.z = 0.5
        body.radius = body.presence = 0.2
        presentation = PresentationFrame(
            bodies=(body,),
            forces=AudioForces(transient=0.3),
            affect=object(),
            narrative=object(),
            phase=0.0,
        )

        projected = project_presentation(presentation, 960, 640)

        self.assertEqual(len(projected), 1)


if __name__ == "__main__":
    unittest.main()
