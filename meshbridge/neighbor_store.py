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


def reachability_rank(value: str | None) -> int:
    """Rank reachability so we keep the most useful observed state."""
    order = {
        None: 0,
        "unknown": 1,
        "multi_hop": 2,
        "direct": 3,
    }
    return order.get(value, 0)


class NeighborStore:
    """Track mesh neighbors and persist a small cache."""

    def __init__(self, cache_file: str, cache_limit: int) -> None:
        self.cache_path = Path(cache_file)
        self.cache_limit = cache_limit
        self._neighbors: dict[str, NeighborRecord] = {}
        self._dirty = False
        self._provisional_ids: set[str] = set()
        self._unnamed_keyed_ids: set[str] = set()
        self._sorted_cache: list[NeighborRecord] | None = None

    def is_dirty(self) -> bool:
        """Return True when neighbor state has changed since the last save."""
        return self._dirty

    def _mark_dirty(self) -> None:
        """Mark in-memory state as needing persistence."""
        self._dirty = True
        self._sorted_cache = None

    @staticmethod
    def _normalize_record_rf(record: NeighborRecord) -> None:
        """Keep persisted/displayed RF state internally consistent."""
        if record.path:
            # A concrete observed path is stronger evidence than a stale
            # reachability label from an earlier direct advert.
            record.hop_count = len(record.path)
            record.reachability = "multi_hop"
            return

        if record.hop_count is not None and record.hop_count > 0:
            record.reachability = "multi_hop"
            return

        if record.reachability == "direct":
            record.hop_count = 0

    def _reindex_record(self, neighbor_id: str, record: NeighborRecord) -> None:
        """Refresh helper indexes for one record."""
        self._normalize_record_rf(record)

        if neighbor_id.startswith("name:"):
            self._provisional_ids.add(neighbor_id)
            self._unnamed_keyed_ids.discard(neighbor_id)
            return

        self._provisional_ids.discard(neighbor_id)

        if record.name or record.last_seen <= 0 or record.reachability not in (None, "direct"):
            self._unnamed_keyed_ids.discard(neighbor_id)
            return

        self._unnamed_keyed_ids.add(neighbor_id)

    def _set_record(self, neighbor_id: str, record: NeighborRecord) -> None:
        """Insert or replace a neighbor record and refresh indexes."""
        self._neighbors[neighbor_id] = record
        self._reindex_record(neighbor_id, record)

    def _remove_record(self, neighbor_id: str) -> None:
        """Remove a neighbor record from storage and indexes."""
        self._neighbors.pop(neighbor_id, None)
        self._provisional_ids.discard(neighbor_id)
        self._unnamed_keyed_ids.discard(neighbor_id)

    def update_from_message(self, msg: BridgeMessage) -> None:
        """Update neighbor state from a message object."""
        if msg.source != "mesh":
            return

        # Only a true sender name counts as a real name.
        candidate_name = (msg.sender.name or "").strip()
        canonical_id = canonical_neighbor_id(msg.sender.key, msg.sender.key_prefix)

        # ------------------------------------------------------------------
        # Message-first path: no key yet, but we do have a real sender name.
        # ------------------------------------------------------------------
        if not canonical_id:
            existing_id, existing_record = self._find_keyed_record_by_name(candidate_name)
            if existing_id and existing_record:
                self._merge_record_from_message(existing_record, msg, candidate_name)
                self._reindex_record(existing_id, existing_record)
                self._mark_dirty()
                return

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
                    rf_source=msg.metadata.get("rf_source") or msg.metadata.get("mesh_event_type"),
                    path=list(msg.path.raw_path),
                    source=msg.metadata.get("mesh_event_type", "unknown"),
                )
                self._set_record(provisional_id, record)
            else:
                self._merge_record_from_message(record, msg, candidate_name)
                self._reindex_record(provisional_id, record)

            self._mark_dirty()
            return

        # ------------------------------------------------------------------
        # Stable keyed record path.
        # ------------------------------------------------------------------
        record = self._neighbors.get(canonical_id)
        created_new_keyed_record = record is None

        if record is None:
            record = NeighborRecord(
                key=msg.sender.key or canonical_id,
                name=None,
                last_seen=msg.created_at,
                reachability=msg.rf.reachability,
                hop_count=msg.path.hop_count,
                snr=msg.rf.snr,
                rssi=msg.rf.rssi,
                rf_source=msg.metadata.get("rf_source") or msg.metadata.get("mesh_event_type"),
                path=list(msg.path.raw_path),
                source=msg.metadata.get("mesh_event_type", "unknown"),
            )
            self._set_record(canonical_id, record)

        # ------------------------------------------------------------------
        # Preferred merge: if this keyed message also has a real name, merge
        # the same-name provisional record immediately.
        # ------------------------------------------------------------------
        provisional_id = provisional_neighbor_id(candidate_name)
        if provisional_id and provisional_id in self._neighbors and provisional_id != canonical_id:
            provisional = self._neighbors[provisional_id]
            self._merge_record_into_record(record, provisional)
            self._remove_record(provisional_id)

        # ------------------------------------------------------------------
        # Missing merge path fix:
        #
        # If a keyed record is being created from an advert/path event that has
        # no real name, try to absorb the most recent provisional direct record.
        #
        # This handles the common order:
        #   1. message heard first  -> provisional record
        #   2. advert heard later   -> keyed record
        # ------------------------------------------------------------------
        if created_new_keyed_record and not candidate_name:
            merged = self._merge_recent_provisional_into_keyed_record(
                target=record,
                now_ts=msg.created_at,
                max_age_seconds=180,
            )
            if merged:
                # Keep the keyed record's event source as the current event if it
                # already has one, but allow telemetry/name/path from provisional.
                pass

        self._merge_record_from_message(record, msg, candidate_name)
        self._reindex_record(canonical_id, record)

        if msg.sender.key:
            record.key = msg.sender.key

        self._mark_dirty()

    def upgrade_name(self, full_key: str | None, key_prefix: str | None, name: str | None) -> None:
        """Upgrade an existing neighbor with a newly learned real name."""
        canonical_id = canonical_neighbor_id(full_key, key_prefix)
        if not canonical_id or not name:
            return

        cleaned = " ".join(str(name).split()).strip()
        if not cleaned or cleaned.lower() == "unknown":
            return

        record = self._neighbors.get(canonical_id)
        if record is None:
            self._set_record(
                canonical_id,
                NeighborRecord(
                key=full_key or canonical_id,
                name=cleaned,
                last_seen=0,
                reachability=None,
                ),
            )
            record = self._neighbors[canonical_id]
        else:
            record.name = cleaned
            if full_key:
                record.key = full_key
            self._reindex_record(canonical_id, record)

        provisional_id = provisional_neighbor_id(cleaned)
        if provisional_id and provisional_id in self._neighbors and provisional_id != canonical_id:
            provisional = self._neighbors[provisional_id]
            self._merge_record_into_record(record, provisional)
            self._remove_record(provisional_id)
            self._reindex_record(canonical_id, record)

        self._mark_dirty()

    def _merge_recent_provisional_into_keyed_record(
        self,
        target: NeighborRecord,
        now_ts: int,
        max_age_seconds: int = 180,
    ) -> bool:
        """Merge the most recent provisional record into a keyed record.

        This is used when a keyed advert/path event arrives after a message-first
        provisional record was already created, but the keyed event itself does
        not carry a real name.

        Returns:
            True if a provisional record was merged.
        """
        candidates: list[tuple[str, NeighborRecord]] = []

        for neighbor_id in self._provisional_ids:
            record = self._neighbors.get(neighbor_id)
            if record is None:
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

        # If there are multiple plausible provisional candidates, do not guess.
        if len(candidates) > 1:
            return False

        provisional_id, provisional = candidates[0]
        self._merge_record_into_record(target, provisional)
        self._remove_record(provisional_id)
        return True

    def _find_keyed_record_by_name(self, candidate_name: str | None) -> tuple[str | None, NeighborRecord | None]:
        """Return the newest confirmed keyed record that matches a real name."""
        if not candidate_name:
            return None, None

        needle = candidate_name.strip().lower()
        if not needle or needle == "unknown":
            return None, None

        best_id: str | None = None
        best_record: NeighborRecord | None = None
        for neighbor_id, record in self._neighbors.items():
            if neighbor_id.startswith("name:"):
                continue
            if not record.name or record.name.strip().lower() != needle:
                continue
            if best_record is None or record.last_seen > best_record.last_seen:
                best_id = neighbor_id
                best_record = record

        return best_id, best_record

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

        if reachability_rank(msg.rf.reachability) >= reachability_rank(record.reachability):
            record.reachability = msg.rf.reachability

        if msg.path.hop_count is not None:
            record.hop_count = msg.path.hop_count

        if msg.rf.snr is not None:
            record.snr = msg.rf.snr

        if msg.rf.rssi is not None:
            record.rssi = msg.rf.rssi

        if msg.rf.snr is not None or msg.rf.rssi is not None:
            record.rf_source = msg.metadata.get("rf_source") or msg.metadata.get("mesh_event_type")

        if msg.path.raw_path:
            record.path = list(msg.path.raw_path)
        elif msg.rf.reachability == "direct":
            record.path = []

    def _merge_record_into_record(self, target: NeighborRecord, source: NeighborRecord) -> None:
        """Merge one record into another, keeping the best-known values."""
        source_rank = reachability_rank(source.reachability)
        target_rank = reachability_rank(target.reachability)

        if source.name and not target.name:
            target.name = source.name

        if source.last_seen > target.last_seen:
            target.last_seen = source.last_seen

        if source_rank > target_rank:
            target.reachability = source.reachability

        if (
            source.hop_count is not None
            and (
                target.hop_count is None
                or source_rank > target_rank
            )
        ):
            target.hop_count = source.hop_count

        if source.snr is not None and target.snr is None:
            target.snr = source.snr

        if source.rssi is not None and target.rssi is None:
            target.rssi = source.rssi

        if source.rf_source and not target.rf_source:
            target.rf_source = source.rf_source

        if source.path and (
            not target.path
            or source_rank > target_rank
        ):
            target.path = list(source.path)
        elif source.reachability == "direct" and source_rank > target_rank:
            target.path = []

        if source.source and (not target.source or target.source == "unknown"):
            target.source = source.source

    def list_recent(self, limit: int | None = None) -> list[NeighborRecord]:
        """Return neighbors sorted by newest first."""
        if self._sorted_cache is None:
            self._sorted_cache = sorted(
                self._neighbors.values(),
                key=lambda item: item.last_seen,
                reverse=True,
            )
        if limit is None:
            return list(self._sorted_cache)
        return list(self._sorted_cache[:limit])

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

    def save(self, force: bool = False) -> None:
        """Persist a compact cache of the top stable neighbors.

        Provisional name-only records are intentionally not persisted.
        """
        if not force and not self._dirty:
            return

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
                        "rf_source": item.rf_source,
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
        self._dirty = False

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
            self._set_record(
                canonical_id,
                NeighborRecord(
                    key=full_key,
                    name=entry.get("name"),
                    last_seen=int(entry.get("last_seen", 0)),
                    reachability=rf.get("reachability"),
                    hop_count=rf.get("hop_count"),
                    snr=rf.get("snr"),
                    rssi=rf.get("rssi"),
                    rf_source=rf.get("rf_source"),
                    path=list(rf.get("path", [])),
                    source="cache",
                ),
            )
        self._dirty = False
