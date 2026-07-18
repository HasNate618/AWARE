from __future__ import annotations

import random
import time

from aware.app.perception.interface import Detection, PerceptionSnapshot

_OBJECTS = ["person", "cat", "dog", "car", "package"]
_SOUNDS = ["doorbell", "knock", "glass_break", "voice"]


class MockCamera:
    """Fake perception source for local testing."""

    def __init__(self, detect_prob: float = 0.3) -> None:
        self.detect_prob = detect_prob
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def snapshot(self) -> PerceptionSnapshot:
        detections: list[Detection] = []
        sounds: list[Detection] = []
        if random.random() < self.detect_prob:
            label = random.choice(_OBJECTS)
            conf = round(random.uniform(0.7, 0.99), 2)
            detections.append(Detection(label=label, confidence=conf))
        if random.random() < self.detect_prob * 0.5:
            label = random.choice(_SOUNDS)
            sounds.append(Detection(label=label, confidence=round(random.uniform(0.6, 0.95), 2)))
        return PerceptionSnapshot(
            detections=detections,
            sounds=sounds,
            source="mock_camera",
            timestamp=time.time(),
        )
