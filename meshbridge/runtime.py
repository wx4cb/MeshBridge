"""Runtime state helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class BridgeState:
    """Mutable bridge state."""

    started_at: int = field(default_factory=lambda: int(time.time()))
    global_paused: bool = False
    mesh_connected: bool = False
    reconnect_count: int = 0
