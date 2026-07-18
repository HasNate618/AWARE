from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Detection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class PerceptionSnapshot:
    detections: list[Detection] = field(default_factory=list)
    sounds: list[Detection] = field(default_factory=list)
    entered: list[str] = field(default_factory=list)   # labels newly present this frame
    exited: list[str] = field(default_factory=list)    # labels present last frame, gone now
    source: str = "unknown"
    timestamp: float = 0.0


@runtime_checkable
class PerceptionSource(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def snapshot(self) -> PerceptionSnapshot: ...
