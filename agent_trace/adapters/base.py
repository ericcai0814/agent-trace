"""Abstract Adapter — agent-specific transcript parsers implement this.

See docs/PLANNING.md D2 for why the interface lands before the second
concrete implementation. Keep this surface minimal until the second
adapter forces it to grow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from agent_trace.core.events import NormalizedEvent


class Adapter(ABC):
    name: str

    @abstractmethod
    def parse(self, transcript_path: Path) -> Iterator[NormalizedEvent]:
        """Yield NormalizedEvent in source order for one transcript file."""
