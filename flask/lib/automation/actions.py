from dataclasses import dataclass
from typing import Optional


@dataclass
class ClearWatches:
    device: Optional[str] = None
