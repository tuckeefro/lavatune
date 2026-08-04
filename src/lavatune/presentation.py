"""Small renderer-neutral view of the shared organism simulation.

Presentation backends read this frame but never advance or mutate the
organisms.  Keeping the hand-off this narrow lets the terminal UI remain the
product while an experimental pixel renderer can develop independently.
"""

from __future__ import annotations

from dataclasses import dataclass

from .organism import Body
from .signals import AffectiveState, AudioForces, NarrativeState


@dataclass(frozen=True, slots=True)
class PresentationFrame:
    """A single render tick from Lavatune's persistent organism world.

    ``bodies`` contains the live, simulation-owned bodies for this tick.  It
    is a tuple to make the renderer contract explicit: presentation code may
    inspect them, but must not change their state.
    """

    bodies: tuple[Body, ...]
    forces: AudioForces
    affect: AffectiveState
    narrative: NarrativeState
    phase: float
