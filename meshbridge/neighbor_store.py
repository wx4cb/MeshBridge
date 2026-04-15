"""Neighbor tracking and lightweight persistence."""

from __future__ import annotations

import json
from pathlib import Path

from meshbridge.models import BridgeMessage, NeighborCacheEntry, NeighborRecord


def canonical_neighbor_id(full_key: str | None, key_prefix: str | None) -> str | None:
    """Return the canonical short neighbor ID."""
    source = full_key or key_prefix
    if not source:
        return None
    return str(source)[:8]


class NeighborStore:
    """Track mesh neighbors and persist a small cache."""

    def __init__(self, cache_file: str, cache_limit: int) -> None:
        self.cache_path = Path(cache_file)
        self.cache_limit = cache_limit
        self._neighbors: dict[str, NeighborRecord] = {}

    def update_from_message(self, msg: BridgeMessage) -> None:
        """Update neighbor state from a message object."""
        if msg.source != "mesh":
            return

        canonical_id = canonical_neighbor_id(msg.sender.key, msg.sender.key_prefix)
        if not canonical_id:
            return

        record = self._neighbors.get(canonical_id)
        if record is None:
            record = NeighborRecord(
                key=msg.sender.key or canonical_id,
                name=None,
                last_seen=msg.created_at,
                reachability=msg.rf.reachability,
                hop_count=msg.path.hop_count,
                snr=msg.rf.snr,
                rssi=msg.rf.rssi,
                path=list(msg.path.raw_path),
                source=msg.metadata.get("mesh_event_type", "unknown"),
            )
            self._neighbors[canonical_id] = record

        if msg.sender.key:
            record.key = msg.sender.key

        record.last_seen = msg.created_at
        record.source = msg.metadata.get("mesh_event_type", record.source)

        candidate_name = (msg.sender.name or msg.sender.display or "").strip()
        if candidate_name and candidate_name.lower() != "unknown" and candidate_name != canonical_id:
            record.name = candidate_name

        if msg.rf.reachability:
            record.reachability = msg.rf.reachability

        if msg.path.hop_count is not None:
            record.hop_count = msg.path.hop_count

        if msg.rf.snr is not None:
            record.snr = msg.rf.snr

        if msg.rf.rssi is not None:
            record.rssi = msg.rf.rssi

        if msg.path.raw_path:
            record.path = list(msg.path.raw_path)

    def upgrade_name(self, full_key: str | None, key_prefix: str | None, name: str | None) -> None:
        """Upgrade an existing neighbor with a newly learned name."""
        canonical_id = canonical_neighbor_id(full_key, key_prefix)
        if not canonical_id or not name:
            return

        cleaned = " ".join(str(name).split()).strip()
        if not cleaned or cleaned.lower() == "unknown":
            return

        record = self._neighbors.get(canonical_id)
        if record is None:
            self._neighbors[canonical_id] = NeighborRecord(
                key=full_key or canonical_id,
                name=cleaned,
                last_seen=0,
                reachability=None,
            )
            return

        record.name = cleaned
        if full_key:
            record.key = full_key

    def list_recent(self) -> list[NeighborRecord]:
        """Return neighbors sorted by most recently seen."""
        return sorted(self._neighbors.values(), key=lambda item: item.last_seen, reverse=True)

    def get(self, key_prefix: str) -> NeighborRecord | None:
        """Return a neighbor by canonical key prefix or full key prefix."""
        needle = str(key_prefix).strip().lower()
        if not needle:
            return None

        for canonical_id, value in self._neighbors.items():
            if canonical_id.lower().startswith(needle):
                return value
            if value.key.lower().startswith(needle):
                return value
        return None

    def save(self) -> None:
        """Persist a compact cache of the top neighbors."""
        top = self.list_recent()[: self.cache_limit]
        payload = [
            NeighborCacheEntry(
                name=item.name,
                key=item.key,
                last_seen=item.last_seen,
                rf={
                    "reachability": item.reachability,
                    "hop_count": item.hop_count,
                    "snr": item.snr,
                    "rssi": item.rssi,
                    "path": item.path,
                },
            ).__dict__
            for item in top
        ]
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        """Load neighbor cache if present."""
        if not self.cache_path.exists():
            return

        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return

        for entry in raw:
            try:
                full_key = str(entry["key"])
            except Exception:
                continue

            canonical_id = canonical_neighbor_id(full_key, full_key)
            if not canonical_id:
                continue

            rf = dict(entry.get("rf", {}))
            self._neighbors[canonical_id] = NeighborRecord(
                key=full_key,
                name=entry.get("name"),
                last_seen=int(entry.get("last_seen", 0)),
                reachability=rf.get("reachability"),
                hop_count=rf.get("hop_count"),
                snr=rf.get("snr"),
                rssi=rf.get("rssi"),
                path=list(rf.get("path", [])),
                source="cache",
            )
