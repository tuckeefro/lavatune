from __future__ import annotations

import unittest

from lavatune.organism import AudioForces, NarrativeState
from lavatune.wax import WAX_HEIGHT, WAX_SIZE, WAX_WIDTH, WaxState


def _components(state: WaxState, threshold: float = 0.34) -> int:
    seen: set[int] = set()
    count = 0
    for index, density in enumerate(state.density):
        if density < threshold or index in seen:
            continue
        count += 1
        pending = [index]
        seen.add(index)
        while pending:
            current = pending.pop()
            x = current % WAX_WIDTH
            y = current // WAX_WIDTH
            for neighbor in (
                current - 1 if x else -1,
                current + 1 if x < WAX_WIDTH - 1 else -1,
                current - WAX_WIDTH if y else -1,
                current + WAX_WIDTH if y < WAX_HEIGHT - 1 else -1,
            ):
                if (
                    neighbor >= 0
                    and neighbor not in seen
                    and state.density[neighbor] >= threshold
                ):
                    seen.add(neighbor)
                    pending.append(neighbor)
    return count


def _center_y(state: WaxState) -> float:
    mass = sum(state.density)
    return sum(
        (index // WAX_WIDTH) * density for index, density in enumerate(state.density)
    ) / max(0.001, mass)


class WaxStateTests(unittest.TestCase):
    HOT = AudioForces(bass=0.95, energy=0.85, tempo=0.50, bands=(0.70,) * 8)
    HELD = NarrativeState(held_pressure=0.90, cadence=0.70)

    def test_wax_uses_fixed_memory_and_bounded_mass(self) -> None:
        state = WaxState()
        initial_mass = sum(state.density)
        for _ in range(80):
            state.advance(1.0 / 12.0, self.HOT, self.HELD, "music")

        self.assertEqual(len(state.density), WAX_SIZE)
        self.assertEqual(len(state.heat), WAX_SIZE)
        self.assertEqual(len(state.flow_x), WAX_SIZE)
        self.assertEqual(len(state.flow_y), WAX_SIZE)
        self.assertAlmostEqual(sum(state.density), initial_mass, delta=initial_mass * 0.02)

    def test_sustained_heat_merges_wax_then_cooling_returns_two_lobes(self) -> None:
        state = WaxState()
        self.assertEqual(_components(state), 3)
        for _ in range(60):
            state.advance(1.0 / 12.0, self.HOT, self.HELD, "music")
        self.assertEqual(_components(state), 1)

        for _ in range(190):
            state.advance(1.0 / 12.0, AudioForces(), NarrativeState(), "music")
        self.assertGreaterEqual(_components(state), 2)

    def test_heat_rises_above_a_cooling_vessel(self) -> None:
        hot = WaxState()
        cold = WaxState()
        for _ in range(60):
            hot.advance(1.0 / 12.0, self.HOT, self.HELD, "music")
            cold.advance(1.0 / 12.0, AudioForces(), NarrativeState(), "music")

        self.assertLess(_center_y(hot), _center_y(cold) - 3.0)

    def test_context_scales_the_same_audio_without_reinterpreting_it(self) -> None:
        music = WaxState()
        podcast = WaxState()
        for _ in range(30):
            music.advance(1.0 / 12.0, self.HOT, self.HELD, "music")
            podcast.advance(1.0 / 12.0, self.HOT, self.HELD, "podcast")

        self.assertGreater(max(music.heat), max(podcast.heat) + 0.20)

    def test_transient_creates_one_local_bounded_disturbance(self) -> None:
        state = WaxState()
        state.advance(
            1.0 / 12.0,
            AudioForces(transient=0.90, tone=0.72),
            NarrativeState(),
            "music",
        )

        self.assertGreater(state.impulse, 0.20)
        self.assertTrue(0.0 <= state.impulse_x <= 1.0)
        self.assertTrue(0.0 <= state.impulse_y <= 1.0)


if __name__ == "__main__":
    unittest.main()
