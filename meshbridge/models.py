"""Core data models for MeshBridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SenderInfo:
    """Information about the sender of a bridged message."""

    name: str | None = None
    display: str | None = None
    key: str | None = None
    key_prefix: str | None = None


@dataclass(slots=True)
class RouteInfo:
    """Routing information carried with a bridged message."""

    route_name: str | None = None
    mesh_channel: int | None = None
    discord_channel_id: int | None = None
    webhook_url: str | None = None
    target: str | None = None


@dataclass(slots=True)
class PathInfo:
    """Path and hop information for a bridged message."""

    raw_path: list[str] = field(default_factory=list)
    hop_count: int | None = None
    repeated: bool = False
    direct: bool = False


@dataclass(slots=True)
class RFInfo:
    """RF metadata for a bridged message."""

    snr: float | None = None
    rssi: float | None = None
    reachability: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BridgeMessage:
    """Unified in-memory message object used throughout the bridge."""

    message_id: str
    source: str
    kind: str
    created_at: int
    text: str

    sender: SenderInfo = field(default_factory=SenderInfo)
    route: RouteInfo = field(default_factory=RouteInfo)
    path: PathInfo = field(default_factory=PathInfo)
    rf: RFInfo = field(default_factory=RFInfo)

    metadata: dict[str, Any] = field(default_factory=dict)

    contains_url: bool = False
    contains_mass_mention: bool = False
    text_safe_for_log: str | None = None

    delivery_status: str | None = None
    drop_reason: str | None = None


@dataclass(slots=True)
class Route:
    """Configured route between one Mesh channel and one Discord channel."""

    name: str
    mesh_channel: int
    discord_channel_id: int
    webhook_url: str


@dataclass(slots=True)
class NeighborRecord:
    """Tracked information about a known or provisional mesh node."""

    key: str
    name: str | None = None
    last_seen: int = 0
    reachability: str | None = None
    hop_count: int | None = None
    snr: float | None = None
    rssi: float | None = None
    rf_source: str | None = None
    path: list[str] = field(default_factory=list)
    source: str | None = None


@dataclass(slots=True)
class NeighborCacheEntry:
    """Persisted on-disk neighbor cache entry."""

    name: str | None
    key: str
    last_seen: int
    rf: dict[str, Any]
