from pathlib import Path
from typing import Protocol

from ..models import TopologySnapshot


class SavedSnapshotProvider(Protocol):
    def read(self, path: str | Path, canvas_name: str) -> TopologySnapshot:
        raise NotImplementedError
