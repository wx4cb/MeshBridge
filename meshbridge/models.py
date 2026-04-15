"""Core data models used by MeshBridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class SenderInfo:
    """Sender identity information."""

    name: str | None = None
    key: str | None = None
    key_prefix: str | None = None
    display: str | None = None


@dataclass(slots=True)
class PathHop:
    """One hop in a mesh path."""

    key: str | None = None
    key_prefix: str | None = None
    name: str | None = None
    snr: float | None = None
    rssi: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PathInfo:
    """Routing/path details attached to a message."""

    hops: list[PathHop] = field(default_factory=list)
    hop_count: int | None = None
    repeated: bool = False
    direct: bool = False
    ingress_repeater: str | None = None
    egress_repeater: str | None = None
    raw_path: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RFInfo:
    """RF-related metrics attached to a message."""

    snr: float | None = None
    rssi: float | None = None
    reachability: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Route:
    """One configured bridge route."""

    name: str
    mesh_channel: int
    discord_channel_id: int
    webhook_url: str


@dataclass(slots=True)
class RouteInfo:
    """Resolved routing information on a message."""

    route_name: str | None = None
    discord_channel_id: int | None = None
    mesh_channel: int | None = None
    webhook_url: str | None = None
    target: Literal["discord", "mesh", "none"] = "none"


@dataclass(slots=True)
class PipelineStep:
    """One pipeline step note for a message."""

    stage: str
    at: int
    note: str | None = None


@dataclass(slots=True)
class BridgeMessage:
    """Canonical internal bridge message object."""

    message_id: str
    source: Literal["discord", "mesh"]
    kind: Literal["channel", "dm", "system"]
    created_at: int

    text: str = ""
    sender: SenderInfo = field(default_factory=SenderInfo)
    route: RouteInfo = field(default_factory=RouteInfo)
    path: PathInfo = field(default_factory=PathInfo)
    rf: RFInfo = field(default_factory=RFInfo)

    attachments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    history: list[PipelineStep] = field(default_factory=list)

    delivery_status: Literal["pending", "skipped", "sent", "failed"] = "pending"
    drop_reason: str | None = None
    contains_url: bool = False
    contains_mass_mention: bool = False
    text_safe_for_log: str = ""

    def note(self, stage: str, at: int, note: str | None = None) -> None:
        """Append one pipeline history record."""
        self.history.append(PipelineStep(stage=stage, at=at, note=note))


@dataclass(slots=True)
class NeighborRecord:
    """Current in-memory neighbor record."""

    key: str
    name: str | None
    last_seen: int
    reachability: str | None = None
    hop_count: int | None = None
    snr: float | None = None
    rssi: float | None = None
    path: list[str] = field(default_factory=list)
    source: str = "unknown"


@dataclass(slots=True)
class NeighborCacheEntry:
    """Small persisted neighbor cache entry."""

    name: str | None
    key: str
    last_seen: int
    rf: dict[str, object]
