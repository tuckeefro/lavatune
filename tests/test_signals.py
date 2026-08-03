from __future__ import annotations

import unittest

from lavatune.organism import (
    AffectiveState,
    AffectiveTracker,
    AudioForceMapper,
    AudioForces,
    NarrativeState,
    NarrativeTracker,
)
from lavatune.signals import (
    AffectiveState as SignalAffectiveState,
    AffectiveTracker as SignalAffectiveTracker,
    AudioForceMapper as SignalAudioForceMapper,
    AudioForces as SignalAudioForces,
    NarrativeState as SignalNarrativeState,
    NarrativeTracker as SignalNarrativeTracker,
)


class SignalCompatibilityTests(unittest.TestCase):
    def test_organism_keeps_reexporting_the_signal_contract(self) -> None:
        self.assertIs(AudioForces, SignalAudioForces)
        self.assertIs(AffectiveState, SignalAffectiveState)
        self.assertIs(NarrativeState, SignalNarrativeState)
        self.assertIs(AudioForceMapper, SignalAudioForceMapper)
        self.assertIs(AffectiveTracker, SignalAffectiveTracker)
        self.assertIs(NarrativeTracker, SignalNarrativeTracker)


if __name__ == "__main__":
    unittest.main()
