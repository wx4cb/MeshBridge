"""Neighbor tracking and lightweight persistence."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from meshbridge.models import BridgeMessage, NeighborCacheEntry, NeighborRecord


def canonical_neighbor_id(full_key: str | None, key_prefix: str | None) -> str | None:
    """Return the canonical short neighbor ID."""
    source = full_key or key_prefix
    if not source:
        return None
    return str(source)[:8]


def provisional_neighbor_id(name: str | None) -> str | None:
    """Return a provisional in-memory neighbor ID for name-only messages."""
    if not name:
        return None
    cleaned = " ".join(str(name).split()).strip()
    if not cleaned or cleaned.lower() == "unknown":
        return None
    return f"name:{cleaned.lower()}"


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
        candidate_name = (msg.sender.name or msg.sender.display or "").strip()

        # Message-first path: no key yet, so create/update provisional name record.
        if not canonical_id:
            provisional_id = provisional_neighbor_id(candidate_name)
            if not provisional_id:
                return

            record = self._neighbors.get(provisional_id)
            if record is None:
                record = NeighborRecord(
                    key=provisional_id,
                    name=candidate_name,
                    last_seen=msg.created_at,
                    reachability=msg.rf.reachability,
                    hop_count=msg.path.hop_count,
                    snr=msg.rf.snr,
                    rssi=msg.rf.rssi,
                    path=list(msg.path.raw_path),
                    source=msg.metadata.get("mesh_event_type", "unknown"),
                )
                self._neighbors[provisional_id] = record
            else:
                self._merge_record_from_message(record, msg, candidate_name)

            self.save()
            return

        # Stable keyed record path.
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

        # Merge any same-name provisional record into the keyed record.
        provisional_id = provisional_neighbor_id(candidate_name)
        if provisional_id and provisional_id in self._neighbors and provisional_id != canonical_id:
            provisional = self._neighbors[provisional_id]
            self._merge_record_into_record(record, provisional)
            del self._neighbors[provisional_id]

        self._merge_record_from_message(record, msg, candidate_name)

        if msg.sender.key:
            record.key = msg.sender.key

        self.save()

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
            record = self._neighbors[canonical_id]
        else:
            record.name = cleaned
            if full_key:
                record.key = full_key

        # Merge matching provisional entry if present.
        provisional_id = provisional_neighbor_id(cleaned)
        if provisional_id and provisional_id in self._neighbors and provisional_id != canonical_id:
            provisional = self._neighbors[provisional_id]
            self._merge_record_into_record(record, provisional)
            del self._neighbors[provisional_id]

        self.save()

    def upgrade_recent_unnamed_neighbor(
        self,
        route_name: str | None,
        msg: BridgeMessage,
        max_age_seconds: int = 120,
    ) -> bool:
        """Heuristically upgrade the most recent unnamed keyed neighbor."""
        candidate_name = (msg.sender.name or msg.sender.display or "").strip()
        if not candidate_name or candidate_name.lower() == "unknown":
            return False

        now_ts = msg.created_at

        candidates: list[tuple[str, NeighborRecord]] = []
        for neighbor_id, record in self._neighbors.items():
            # Skip provisional records here; they already carry a name.
            if neighbor_id.startswith("name:"):
                continue
            if record.name:
                continue
            if record.last_seen <= 0:
                continue
            if now_ts - record.last_seen > max_age_seconds:
                continue
            if record.reachability not in (None, "direct"):
                continue
            candidates.append((neighbor_id, record))

        if not candidates:
            return False

        candidates.sort(key=lambda item: item[1].last_seen, reverse=True)
        _, record = candidates[0]

        self._merge_record_from_message(record, msg, candidate_name)
        self.save()
        return True

    def _merge_record_from_message(
        self,
        record: NeighborRecord,
        msg: BridgeMessage,
        candidate_name: str | None,
    ) -> None:
        """Merge message data into an existing record."""
        record.last_seen = msg.created_at
        record.source = msg.metadata.get("mesh_event_type", record.source)

        if candidate_name and candidate_name.lower() != "unknown":
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

    def _merge_record_into_record(self, target: NeighborRecord, source: NeighborRecord) -> None:
        """Merge one record into another, keeping the best-known values."""
        if source.name and not target.name:
            target.name = source.name

        if source.last_seen > target.last_seen:
            target.last_seen = source.last_seen

        if source.reachability and not target.reachability:
            target.reachability = source.reachability

        if source.hop_count is not None and target.hop_count is None:
            target.hop_count = source.hop_count

        if source.snr is not None and target.snr is None:
            target.snr = source.snr

        if source.rssi is not None and target.rssi is None:
            target.rssi = source.rssi

        if source.path and not target.path:
            target.path = list(source.path)

        if source.source and (not target.source or target.source == "unknown"):
            target.source = source.source

    def list_recent(self) -> list[NeighborRecord]:
        """Return neighbors sorted by most recently seen."""
        return sorted(self._neighbors.values(), key=lambda item: item.last_seen, reverse=True)

    def get(self, key_prefix: str) -> NeighborRecord | None:
        """Return a neighbor by canonical key prefix, full key prefix, or name."""
        needle = str(key_prefix).strip().lower()
        if not needle:
            return None

        for neighbor_id, value in self._neighbors.items():
            if neighbor_id.lower().startswith(needle):
                return value
            if value.key.lower().startswith(needle):
                return value
            if value.name and value.name.lower().startswith(needle):
                return value
        return None

    def save(self) -> None:
        """Persist a compact cache of the top stable neighbors.

        Provisional name-only records are intentionally not persisted.
        """
        stable_neighbors = [
            item for item in self.list_recent()
            if not item.key.startswith("name:")
        ]
        top = stable_neighbors[: self.cache_limit]

        payload = [
            asdict(
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
                )
            )
            for item in top
        ]

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self.cache_path)

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
