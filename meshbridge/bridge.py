"""Main bridge coordinator."""

from __future__ import annotations

import asyncio
import logging
import platform
import time
import uuid
from typing import Any

import psutil

from meshbridge.config import AppConfig
from meshbridge.history import MessageHistory
from meshbridge.memory_store import UnhandledEventStore
from meshbridge.mesh_adapter import MeshAdapter
from meshbridge.models import BridgeMessage, Route
from meshbridge.neighbor_store import NeighborStore
from meshbridge.rate_limit import SlidingWindowRateLimiter
from meshbridge.runtime import BridgeState
from meshbridge.security import (
    contains_mass_mention,
    detect_url,
    format_forwarded_text,
    normalize_sender_name,
    safe_log_text,
    split_for_mesh,
)
from meshbridge.webhook_sender import WebhookSender

system_log = logging.getLogger("meshbridge.system")
traffic_log = logging.getLogger("meshbridge.traffic")
rf_log = logging.getLogger("meshbridge.rf")

CONTROL_SUBTYPE_NAMES = {
    0x8: "DISCOVER_REQ",
    0x9: "DISCOVER_RESP",
}

DISCOVER_NODE_TYPE_NAMES = {
    0x1: "chat",
    0x2: "repeater",
    0x3: "room_server",
    0x4: "sensor",
}


def resolve_sender_display(msg: BridgeMessage) -> str:
    """Return the best available sender display name for a message."""
    return msg.sender.display or msg.sender.name or msg.sender.key_prefix or "unknown"


def extract_prefixed_sender(text: str) -> tuple[str | None, str]:
    """Try to split 'Sender Name: message text' into sender and body."""
    if not text or ": " not in text:
        return None, text

    sender, body = text.split(": ", 1)
    sender = " ".join(sender.split()).strip()
    body = body.strip()

    if not sender or len(sender) > 64:
        return None, text

    return sender, body


def extract_sender_name(payload: dict[str, Any]) -> str | None:
    """Extract the best human-readable sender name from a Mesh payload."""
    direct_candidates = [
        payload.get("adv_name"),
        payload.get("name"),
        payload.get("contact_name"),
        payload.get("sender_name"),
        payload.get("node_name"),
        payload.get("display_name"),
    ]

    for value in direct_candidates:
        if isinstance(value, str) and value.strip():
            return value

    nested_objects = [
        payload.get("contact"),
        payload.get("advert"),
        payload.get("self_info"),
        payload.get("node"),
        payload.get("from"),
        payload.get("sender"),
        payload.get("decoded"),
    ]

    for obj in nested_objects:
        if not isinstance(obj, dict):
            continue

        for key in ("adv_name", "name", "contact_name", "sender_name", "node_name", "display_name"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value

        app_data = obj.get("app_data")
        if isinstance(app_data, dict):
            value = app_data.get("name")
            if isinstance(value, str) and value.strip():
                return value

    return None


def extract_full_key(payload: dict[str, Any]) -> str | None:
    """Extract the full key when present."""
    direct_candidates = [
        payload.get("pubkey"),
        payload.get("public_key"),
        # Advert-style RF payloads often carry identity here instead of the
        # generic pubkey fields, so treat it as first-class keyed evidence.
        payload.get("adv_key"),
    ]
    for value in direct_candidates:
        if value is not None:
            return str(value)

    nested_objects = [
        payload.get("contact"),
        payload.get("advert"),
        payload.get("node"),
        payload.get("from"),
        payload.get("sender"),
        payload.get("decoded"),
    ]
    for obj in nested_objects:
        if not isinstance(obj, dict):
            continue
        for key in ("pubkey", "public_key", "adv_key"):
            value = obj.get(key)
            if value is not None:
                return str(value)

    return None


def extract_key_prefix(payload: dict[str, Any], full_key: str | None) -> str | None:
    """Extract or derive the display key prefix."""
    direct_candidates = [
        payload.get("pubkey_prefix"),
        payload.get("key_prefix"),
        # Keep parity with extract_full_key so advert-backed nodes do not linger
        # as provisional when the adapter only exposed advert-specific fields.
        payload.get("adv_key_prefix"),
    ]
    for value in direct_candidates:
        if value is not None:
            return str(value)[:8]

    nested_objects = [
        payload.get("contact"),
        payload.get("advert"),
        payload.get("node"),
        payload.get("from"),
        payload.get("sender"),
        payload.get("decoded"),
    ]
    for obj in nested_objects:
        if not isinstance(obj, dict):
            continue
        for key in ("pubkey_prefix", "key_prefix", "adv_key_prefix"):
            value = obj.get(key)
            if value is not None:
                return str(value)[:8]

    if full_key:
        return str(full_key)[:8]

    return None


def _coerce_int(value: Any) -> int | None:
    """Return a best-effort integer conversion."""
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def decode_mesh_path(payload: dict[str, Any]) -> tuple[list[str], int | None, bool, bool]:
    """Decode path metadata from MeshCore payload variants."""
    path = payload.get("path")
    route_typename = str(payload.get("route_typename") or "").upper()

    if isinstance(path, list):
        raw_path = [str(item) for item in path]
        hop_count = len(raw_path)
    elif isinstance(path, str):
        compact = path.strip()
        path_len = _coerce_int(payload.get("path_len"))
        hash_size = _coerce_int(payload.get("path_hash_size"))
        if compact and path_len is not None and hash_size is not None and hash_size > 0:
            # RX_LOG_DATA can expose path bytes as a hex string instead of a list.
            # Re-slice that string into hop hashes using the advertised hash width.
            width = hash_size * 2
            raw_path = [
                compact[index:index + width]
                for index in range(0, min(len(compact), path_len * width), width)
                if compact[index:index + width]
            ]
            hop_count = len(raw_path)
        else:
            raw_path = []
            # Direct zero-hop packets often report an empty string path rather than
            # an explicit hop list, so preserve that distinction for reachability.
            hop_count = 0 if route_typename == "DIRECT" else None
    else:
        hops = payload.get("hops")
        if isinstance(hops, list):
            raw_path = [str(item) for item in hops]
            hop_count = len(raw_path)
        else:
            raw_path = []
            hop_count = 0 if route_typename == "DIRECT" else None

    repeated = bool(hop_count and hop_count > 0)
    direct = route_typename == "DIRECT" and hop_count == 0
    return raw_path, hop_count, repeated, direct


def decode_control_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Decode unencrypted MeshCore CONTROL payloads when enough data is present."""
    if str(payload.get("payload_typename") or "").upper() != "CONTROL":
        return None

    pkt_payload = payload.get("pkt_payload")
    if isinstance(pkt_payload, str):
        try:
            pkt_payload = bytes.fromhex(pkt_payload)
        except ValueError:
            pkt_payload = None

    if not isinstance(pkt_payload, (bytes, bytearray)) or len(pkt_payload) < 1:
        return None

    frame = bytes(pkt_payload)
    flags = frame[0]
    # MeshCore CONTROL uses the upper nibble as the control subtype.
    subtype = (flags >> 4) & 0x0F
    decoded: dict[str, Any] = {
        "subtype": subtype,
        "subtype_name": CONTROL_SUBTYPE_NAMES.get(subtype, f"0x{subtype:X}"),
    }

    if subtype == 0x8 and len(frame) >= 6:
        # DISCOVER_REQ layout:
        # [flags][type_filter][tag:4][since?:4]
        decoded["prefix_only"] = bool(flags & 0x01)
        decoded["type_filter"] = frame[1]
        decoded["tag"] = int.from_bytes(frame[2:6], "little")
        if len(frame) >= 10:
            decoded["since"] = int.from_bytes(frame[6:10], "little")
        return decoded

    if subtype == 0x9 and len(frame) >= 7:
        # DISCOVER_RESP layout:
        # [flags][snr*4][tag:4][pubkey:8|32]
        node_type = flags & 0x0F
        raw_snr = int.from_bytes(frame[1:2], "little", signed=True)
        decoded["node_type"] = node_type
        decoded["node_type_name"] = DISCOVER_NODE_TYPE_NAMES.get(node_type, f"0x{node_type:X}")
        decoded["discover_snr"] = raw_snr / 4.0
        decoded["tag"] = int.from_bytes(frame[2:6], "little")
        pubkey_bytes = frame[6:]
        if pubkey_bytes:
            decoded["pubkey_hex"] = pubkey_bytes.hex()
            decoded["pubkey_size"] = len(pubkey_bytes)
        return decoded

    return decoded


class MeshBridge:
    """Coordinate Discord and MeshCore bridging."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = BridgeState()
        self.bot = None

        self.routes_by_discord: dict[int, Route] = {
            route.discord_channel_id: route for route in config.routes
        }
        self.routes_by_mesh: dict[int, Route] = {
            route.mesh_channel: route for route in config.routes
        }
        self.routes_by_name: dict[str, Route] = {
            route.name: route for route in config.routes
        }

        self.history = MessageHistory(config.max_message_history)
        self.unhandled_events = UnhandledEventStore(config.max_unhandled_events)
        self.neighbors = NeighborStore(config.neighbor_cache_file, config.neighbor_cache_limit)
        self.neighbors.load()

        self.rate_limiter = SlidingWindowRateLimiter(
            window_seconds=config.rate_limit_window_seconds,
            max_events=config.rate_limit_max_messages,
        )

        self.webhooks = WebhookSender(
            timeout_seconds=config.webhook_timeout_seconds,
            fixed_avatar_url=config.meshcore_avatar_url,
        )

        self.mesh = MeshAdapter(
            connection_type=config.mesh_connection_type,
            serial_port=config.serial_port,
            baud_rate=config.baud_rate,
            tcp_host=config.tcp_host,
            tcp_port=config.tcp_port,
        )
        self.mesh.set_callback(self.handle_mesh_event)

        self.discord_to_mesh_queue: asyncio.Queue[BridgeMessage] = asyncio.Queue()
        self.mesh_to_discord_queue: asyncio.Queue[BridgeMessage] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task[Any]] = []
        self._mesh_task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._last_auto_probe: dict[str, int] = {}
        self._pending_rf_samples: list[dict[str, Any]] = []
        self._recent_pkt_hashes: dict[int, dict[str, Any]] = {}
        self._recent_packet_history: dict[int, dict[str, Any]] = {}
        self._dm_user = None
        self._dm_channel = None

    def attach_bot(self, bot: Any) -> None:
        """Attach the Discord bot instance."""
        self.bot = bot

    async def start(self) -> None:
        """Start bridge background tasks."""
        self._stop_event.clear()
        await self.webhooks.start()
        self._worker_tasks = [
            asyncio.create_task(self.discord_to_mesh_worker(), name="discord_to_mesh_worker"),
            asyncio.create_task(self.mesh_to_discord_worker(), name="mesh_to_discord_worker"),
            asyncio.create_task(self.persistence_worker(), name="persistence_worker"),
        ]
        if self.config.auto_advert_interval_hours > 0:
            self._worker_tasks.append(
                asyncio.create_task(self.auto_advert_worker(), name="auto_advert_worker")
            )
        self._mesh_task = asyncio.create_task(self.mesh_connection_loop(), name="mesh_connection_loop")

    async def stop(self) -> None:
        """Stop bridge background tasks."""
        self._stop_event.set()
        if self._mesh_task is not None:
            self._mesh_task.cancel()

        for task in self._worker_tasks:
            task.cancel()

        await self.mesh.disconnect()
        self.neighbors.save(force=True)
        await self.webhooks.close()

    async def mesh_connection_loop(self) -> None:
        """Reconnect to MeshCore as needed."""
        delay = self.config.reconnect_initial_delay_seconds

        while not self._stop_event.is_set():
            try:
                await self.mesh.connect()
                self.state.mesh_connected = True
                self.state.reconnect_count += 1
                system_log.info("Connected to MeshCore")

                delay = self.config.reconnect_initial_delay_seconds

                await self._wait_for_mesh_disconnect()

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.mesh_connected = False
                system_log.exception("Mesh connection loop error: %s", exc)

            if self._stop_event.is_set():
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, self.config.reconnect_max_delay_seconds)

    async def _wait_for_mesh_disconnect(self) -> None:
        """Wait until the mesh client disconnects or the bridge stops."""
        waiters = [
            asyncio.create_task(self._stop_event.wait(), name="mesh_stop_waiter"),
        ]

        for index, waiter in enumerate(self.mesh.create_disconnect_waiters()):
            waiters.append(asyncio.create_task(waiter, name=f"mesh_disconnect_waiter_{index}"))

        try:
            if len(waiters) == 1:
                while not self._stop_event.is_set():
                    await asyncio.sleep(5)
            else:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()

        self.state.mesh_connected = False

    def build_version_text(self) -> str:
        """Build the version/status response body."""
        from meshbridge.version import __version__

        proc = psutil.Process()
        mem = proc.memory_info()
        vm = psutil.virtual_memory()
        uptime = int(time.time()) - self.state.started_at

        try:
            load = ", ".join(f"{v:.2f}" for v in __import__("os").getloadavg())
        except Exception:
            load = "unavailable"

        def fmt_uptime(seconds: int) -> str:
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            parts.append(f"{seconds}s")
            return " ".join(parts)

        return "\n".join(
            [
                f"MeshBridge Version: {__version__}",
                f"Bridge State: {'paused' if self.state.global_paused else 'running'}",
                f"Mesh Status: {'connected' if self.state.mesh_connected else 'disconnected'}",
                f"Uptime: {fmt_uptime(uptime)}",
                f"Python: {platform.python_version()}",
                f"OS: {platform.system()} {platform.release()}",
                f"Process RSS: {mem.rss / 1024 / 1024:.1f} MB",
                f"System Free Memory: {vm.available / 1024 / 1024:.1f} MB",
                f"Load Average: {load}",
                f"Recent Messages Buffered: {len(self.history)}",
                f"Reconnect Count: {self.state.reconnect_count}",
            ]
        )

    async def enqueue_discord_message(self, msg: BridgeMessage) -> None:
        """Queue a Discord-origin message."""
        await self.discord_to_mesh_queue.put(msg)

    async def enqueue_mesh_message(self, msg: BridgeMessage) -> None:
        """Queue a mesh-origin message."""
        await self.mesh_to_discord_queue.put(msg)

    async def discord_to_mesh_worker(self) -> None:
        """Deliver Discord-origin messages to mesh."""
        while True:
            msg = await self.discord_to_mesh_queue.get()
            try:
                await self._deliver_discord_to_mesh(msg)
            finally:
                self.history.add(msg)
                self.discord_to_mesh_queue.task_done()

    async def mesh_to_discord_worker(self) -> None:
        """Deliver mesh-origin messages to Discord."""
        while True:
            msg = await self.mesh_to_discord_queue.get()
            try:
                await self._deliver_mesh_to_discord(msg)
            finally:
                self.history.add(msg)
                self.mesh_to_discord_queue.task_done()

    async def persistence_worker(self) -> None:
        """Periodically persist compact neighbor state."""
        while True:
            await asyncio.sleep(30)
            self.neighbors.save()

    async def auto_advert_worker(self) -> None:
        """Send scheduled MeshCore adverts when enabled in configuration."""
        interval_hours = self.config.auto_advert_interval_hours
        interval_seconds = max(60.0, interval_hours * 60 * 60)
        flood = self.config.auto_advert_flood

        system_log.info(
            "Auto advert enabled: interval_hours=%s flood=%s",
            interval_hours,
            flood,
        )

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                break
            except asyncio.TimeoutError:
                pass

            if not self.state.mesh_connected:
                system_log.info("Skipping scheduled advert because MeshCore is disconnected")
                continue

            try:
                await self.mesh.send_advert(flood=flood)
                system_log.info("Sent scheduled advert: flood=%s", flood)
            except Exception as exc:
                system_log.exception("Scheduled advert failed: %s", exc)

    def _store_pending_rf_sample(self, msg: BridgeMessage) -> None:
        """Store an anonymous RF sample for later correlation."""
        if msg.rf.snr is None and msg.rf.rssi is None:
            return

        # RAW_DATA / RX_LOG_DATA can arrive without a sender identity and then be
        # followed a moment later by a message event that contains the human-usable
        # sender details. Keep a short rolling window of those anonymous samples so
        # we can graft the RF metadata onto the later message when timing matches.
        self._pending_rf_samples.append(
            {
                "ts": msg.created_at,
                "snr": msg.rf.snr,
                "rssi": msg.rf.rssi,
                "reachability": msg.rf.reachability,
                "hop_count": msg.path.hop_count,
                "path": list(msg.path.raw_path),
            }
        )

        # The correlation window is intentionally short. We only want "same burst"
        # RF telemetry, not stale samples from unrelated packets seen much earlier.
        cutoff = msg.created_at - 10
        self._pending_rf_samples = [
            sample for sample in self._pending_rf_samples
            if sample["ts"] >= cutoff
        ]

        rf_log.info(
            "Stored pending RF sample snr=%s rssi=%s reachability=%s hops=%s",
            msg.rf.snr,
            msg.rf.rssi,
            msg.rf.reachability,
            msg.path.hop_count,
        )

    def _apply_pending_rf_sample_to_message(self, msg: BridgeMessage) -> bool:
        """Apply the most recent anonymous RF sample to a message."""
        if msg.rf.snr is not None or msg.rf.rssi is not None:
            return False

        if not self._pending_rf_samples:
            return False

        now_ts = msg.created_at
        # Use a small symmetric time window because the event ordering is close but
        # not guaranteed. The newest matching sample is the best guess for "this
        # RF observation belongs to this message" when the adapter splits them.
        candidates = [
            sample for sample in self._pending_rf_samples
            if abs(now_ts - sample["ts"]) <= 5
        ]
        if not candidates:
            return False

        sample = candidates[-1]
        msg.rf.snr = sample["snr"]
        msg.rf.rssi = sample["rssi"]

        # Only fill fields that the higher-level message did not already decode.
        # Explicit per-message telemetry should always win over correlated fallback.
        if sample["reachability"] and msg.rf.reachability == "unknown":
            msg.rf.reachability = sample["reachability"]

        if msg.path.hop_count is None and sample["hop_count"] is not None:
            msg.path.hop_count = sample["hop_count"]

        if not msg.path.raw_path and sample["path"]:
            msg.path.raw_path = list(sample["path"])

        # Mark the provenance so logs and future command surfaces can distinguish
        # true in-message telemetry from metadata inferred by correlation.
        msg.metadata["rf_source"] = "pending_rf_correlation"
        return True

    def _annotate_recent_packet_reuse(self, msg: BridgeMessage) -> None:
        """Annotate repeated low-level packet observations using pkt_hash."""
        pkt_hash = _coerce_int(msg.rf.raw.get("pkt_hash"))
        if pkt_hash is None:
            return

        now_ts = msg.created_at
        previous = self._recent_pkt_hashes.get(pkt_hash)
        if previous is not None:
            msg.metadata["same_pkt_as_recent"] = True
            msg.metadata["pkt_hash"] = pkt_hash
            msg.metadata["previous_pkt_seen_at"] = previous["ts"]

            previous_path = previous.get("path") or []
            current_path = list(msg.path.raw_path)

            # When the same packet reappears with a longer path, that's usually a
            # flood retransmission from the repeater that appended its hash.
            # This is a heuristic, not a protocol guarantee, but it is very useful
            # for understanding "I heard the original" versus "I heard the repeater
            # rebroadcast of that same packet" in RF logs.
            if len(current_path) > len(previous_path):
                msg.metadata["likely_retransmit"] = True
                if current_path:
                    msg.metadata["likely_retransmit_via"] = current_path[-1]

        # Keep only a short recent view of packet hashes. We only need enough
        # history to compare immediate re-hears and repeater rebroadcasts.
        self._recent_pkt_hashes[pkt_hash] = {
            "ts": now_ts,
            "path": list(msg.path.raw_path),
        }

        # Keep a richer sighting history as well so operators can inspect the
        # observed propagation path of a packet instead of inferring it by hand
        # from a stream of RF log lines.
        history = self._recent_packet_history.get(pkt_hash)
        sighting = {
            "ts": now_ts,
            "path": list(msg.path.raw_path),
            "reachability": msg.rf.reachability,
            "snr": msg.rf.snr,
            "rssi": msg.rf.rssi,
            "key_prefix": msg.sender.key_prefix,
            "control_subtype_name": msg.metadata.get("control_subtype_name"),
        }
        if history is None:
            history = {
                "first_seen": now_ts,
                "last_seen": now_ts,
                "pkt_hash": pkt_hash,
                "sightings": [sighting],
            }
            self._recent_packet_history[pkt_hash] = history
        else:
            history["last_seen"] = now_ts
            history["sightings"].append(sighting)
            history["sightings"] = history["sightings"][-8:]

        cutoff = now_ts - 60
        self._recent_pkt_hashes = {
            hash_value: info
            for hash_value, info in self._recent_pkt_hashes.items()
            if info["ts"] >= cutoff
        }

        history_cutoff = now_ts - 300
        self._recent_packet_history = {
            hash_value: info
            for hash_value, info in self._recent_packet_history.items()
            if info["last_seen"] >= history_cutoff
        }

    @staticmethod
    def _format_path_summary(sightings: list[dict[str, Any]]) -> str:
        """Format a concise observed propagation summary from packet sightings."""
        path_chain: list[str] = []
        saw_direct = False

        for sighting in sightings:
            path = sighting.get("path") or []
            if not path:
                saw_direct = True
                continue
            for hop in path:
                hop_text = str(hop)
                if hop_text not in path_chain:
                    path_chain.append(hop_text)

        if saw_direct and path_chain:
            return "origin -> " + " -> ".join(path_chain)
        if saw_direct:
            return "origin"
        if path_chain:
            return " -> ".join(path_chain)
        return "unknown"

    @staticmethod
    def _parse_pkt_hash(value: str) -> int | None:
        """Parse a packet hash from decimal or hex text."""
        text = str(value).strip().lower()
        if not text:
            return None
        try:
            return int(text, 16 if text.startswith("0x") else 10)
        except ValueError:
            return None

    def list_recent_packet_paths(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent packet path summaries newest first."""
        rows = sorted(
            self._recent_packet_history.values(),
            key=lambda item: item["last_seen"],
            reverse=True,
        )
        summaries: list[dict[str, Any]] = []

        for row in rows[:limit]:
            sightings = list(row["sightings"])
            latest = sightings[-1]
            summaries.append(
                {
                    "pkt_hash": row["pkt_hash"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "count": len(sightings),
                    "path_summary": self._format_path_summary(sightings),
                    "latest_path": list(latest.get("path") or []),
                    "latest_snr": latest.get("snr"),
                    "latest_rssi": latest.get("rssi"),
                    "latest_reachability": latest.get("reachability"),
                    "control_subtype_name": latest.get("control_subtype_name"),
                }
            )

        return summaries

    def get_packet_path_details(self, pkt_hash_text: str) -> dict[str, Any] | None:
        """Return one packet's observed propagation details."""
        pkt_hash = self._parse_pkt_hash(pkt_hash_text)
        if pkt_hash is None:
            return None

        row = self._recent_packet_history.get(pkt_hash)
        if row is None:
            return None

        sightings = list(row["sightings"])
        return {
            "pkt_hash": row["pkt_hash"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "count": len(sightings),
            "path_summary": self._format_path_summary(sightings),
            "latest_path": list(sightings[-1].get("path") or []),
            "sightings": sightings,
        }

    def list_recent_chatters(self, limit: int = 10) -> list[dict[str, Any]]:
        """Summarize recent mesh channel senders from message history."""
        grouped: dict[str, dict[str, Any]] = {}

        for msg in self.history.recent():
            if msg.source != "mesh" or msg.kind != "channel":
                continue

            sender_name = (msg.sender.name or msg.sender.display or "unknown").strip() or "unknown"
            identity = msg.sender.key or f"name:{sender_name.lower()}"
            row = grouped.get(identity)
            if row is None:
                row = {
                    "sender_name": sender_name,
                    "key": msg.sender.key,
                    "key_prefix": msg.sender.key_prefix,
                    "last_seen": msg.created_at,
                    "count": 0,
                    "route_name": msg.route.route_name,
                    "reachability": msg.rf.reachability,
                    "hop_count": msg.path.hop_count,
                    "path": list(msg.path.raw_path),
                    "snr": msg.rf.snr,
                    "rssi": msg.rf.rssi,
                    "last_text": msg.text,
                }
                grouped[identity] = row

            row["count"] += 1

        rows = sorted(grouped.values(), key=lambda item: item["last_seen"], reverse=True)
        return rows[:limit]

    async def _deliver_discord_to_mesh(self, msg: BridgeMessage) -> None:
        """Send a Discord message to mesh."""
        if self.state.global_paused:
            msg.delivery_status = "skipped"
            msg.drop_reason = "bridge_paused"
            return

        if msg.route.mesh_channel is None:
            msg.delivery_status = "skipped"
            msg.drop_reason = "no_mesh_route"
            return

        route_key = f"discord_to_mesh:{msg.route.route_name}"
        if not self.rate_limiter.allow(route_key):
            msg.delivery_status = "skipped"
            msg.drop_reason = "rate_limited"
            return

        text = format_forwarded_text(
            sender=resolve_sender_display(msg),
            text=msg.text,
            key_prefix=None,
        )
        traffic_log.info(
            "Discord -> Mesh route=%s sender=%s discord_message_id=%s text=%r",
            msg.route.route_name,
            resolve_sender_display(msg),
            msg.metadata.get("discord_message_id"),
            msg.text,
        )

        for chunk in split_for_mesh(text, self.config.mesh_chunk_size):
            await self.mesh.send_channel_text(msg.route.mesh_channel, chunk)
            await self.mesh.sleep_briefly(self.config.mesh_chunk_delay_seconds)

        msg.delivery_status = "sent"

    async def _deliver_mesh_to_discord(self, msg: BridgeMessage) -> None:
        """Send a mesh message to Discord."""
        if self.state.global_paused:
            msg.delivery_status = "skipped"
            msg.drop_reason = "bridge_paused"
            return

        if msg.kind == "dm":
            if self.bot is None:
                msg.delivery_status = "failed"
                msg.drop_reason = "bot_not_attached"
                return

            text = format_forwarded_text(
                sender=resolve_sender_display(msg),
                text=msg.text,
                key_prefix=msg.sender.key_prefix,
            )

            if self.config.mesh_dm_user_id:
                user = await self._get_mesh_dm_user()
                await user.send(text, allowed_mentions=self.bot.allowed_mentions_none())
                traffic_log.info("Mesh DM -> Discord user sender=%s text=%r", resolve_sender_display(msg), msg.text)
            elif self.config.mesh_dm_channel_id:
                channel = await self._get_mesh_dm_channel()
                await channel.send(text, allowed_mentions=self.bot.allowed_mentions_none())
                traffic_log.info("Mesh DM -> Discord room sender=%s text=%r", resolve_sender_display(msg), msg.text)
            else:
                msg.delivery_status = "failed"
                msg.drop_reason = "no_dm_destination"
                return

            msg.delivery_status = "sent"
            return

        if not msg.route.webhook_url:
            msg.delivery_status = "skipped"
            msg.drop_reason = "no_webhook_url"
            return

        route_key = f"mesh_to_discord:{msg.route.route_name}"
        if not self.rate_limiter.allow(route_key):
            msg.delivery_status = "skipped"
            msg.drop_reason = "rate_limited"
            return

        sender_name = resolve_sender_display(msg)
        content = msg.text.strip() if msg.text else sender_name

        traffic_log.info("Mesh -> Discord route=%s sender=%s text=%r", msg.route.route_name, sender_name, msg.text)

        await self.webhooks.send(
            webhook_url=msg.route.webhook_url,
            display_name=sender_name,
            content=content,
        )
        msg.delivery_status = "sent"

    async def _get_mesh_dm_user(self) -> Any:
        """Return the cached Discord user for mesh DM delivery."""
        if self.bot is None or self.config.mesh_dm_user_id is None:
            raise RuntimeError("Mesh DM user destination is not configured")

        if self._dm_user is None or getattr(self._dm_user, "id", None) != self.config.mesh_dm_user_id:
            self._dm_user = await self.bot.fetch_user(self.config.mesh_dm_user_id)
        return self._dm_user

    async def _get_mesh_dm_channel(self) -> Any:
        """Return the cached Discord channel for mesh DM delivery."""
        if self.bot is None or self.config.mesh_dm_channel_id is None:
            raise RuntimeError("Mesh DM channel destination is not configured")

        if self._dm_channel is None or getattr(self._dm_channel, "id", None) != self.config.mesh_dm_channel_id:
            channel = self.bot.get_channel(self.config.mesh_dm_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.config.mesh_dm_channel_id)
            self._dm_channel = channel
        return self._dm_channel

    async def _try_enrich_neighbor_from_contact_lookup(self, msg: BridgeMessage) -> None:
        """Try to upgrade a neighbor name after adverts using contact lookup."""
        key_prefix = msg.sender.key_prefix
        if not key_prefix:
            return

        try:
            looked_up_name = await self.mesh.get_contact_name_by_key_prefix(key_prefix)
        except Exception as exc:
            rf_log.debug("Contact lookup failed for %s: %s", key_prefix, exc)
            return

        if looked_up_name:
            normalized = normalize_sender_name(looked_up_name, fallback=key_prefix)
            self.neighbors.upgrade_name(msg.sender.key, key_prefix, normalized)
            rf_log.info("Neighbor contact lookup: key_prefix=%s name=%s", key_prefix, normalized)

    async def _maybe_auto_probe_on_advert(self, msg: BridgeMessage) -> None:
        """Optionally send path discovery when a new advert is heard."""
        if not self.config.auto_probe_on_advert:
            return

        key = msg.sender.key or msg.sender.key_prefix
        if not key:
            rf_log.info("Auto probe skipped: no key available for advert sender=%s", msg.sender.display)
            return

        canonical = (msg.sender.key_prefix or key[:8]).lower()
        now_ts = msg.created_at
        last_ts = self._last_auto_probe.get(canonical, 0)

        if now_ts - last_ts < self.config.auto_probe_min_interval_seconds:
            rf_log.info(
                "Auto probe skipped: cooldown key=%s age=%s required=%s",
                canonical,
                now_ts - last_ts,
                self.config.auto_probe_min_interval_seconds,
            )
            return

        rf_log.info("Auto probe sending path discovery for key=%s canonical=%s", key, canonical)

        try:
            result = await self.mesh.send_path_discovery(key)
            self._last_auto_probe[canonical] = now_ts
            rf_log.info("Auto path discovery sent for key=%s result=%r", key, result)
        except Exception as exc:
            rf_log.warning("Auto path discovery failed for key=%s: %s", key, exc)

    async def handle_mesh_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Handle one MeshCore event."""
        now = int(time.time())

        if event_name == "CHANNEL_MSG_RECV":
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="channel")

            correlated = self._apply_pending_rf_sample_to_message(msg)
            if correlated:
                rf_log.info(
                    "Applied pending RF sample to CHANNEL_MSG_RECV sender=%s snr=%s rssi=%s",
                    resolve_sender_display(msg),
                    msg.rf.snr,
                    msg.rf.rssi,
                )

            self.neighbors.update_from_message(msg)

            await self.enqueue_mesh_message(msg)
            return

        if event_name == "CONTACT_MSG_RECV":
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="dm")
            self.neighbors.update_from_message(msg)
            await self.enqueue_mesh_message(msg)
            return

        if event_name in {"ADVERTISEMENT", "PATH_UPDATE", "PATH_RESPONSE", "TRACE_DATA", "RAW_DATA", "RX_LOG_DATA"}:
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="system")

            if event_name in {"RAW_DATA", "RX_LOG_DATA"} and not msg.sender.key and not msg.sender.key_prefix:
                self._store_pending_rf_sample(msg)

            self.neighbors.update_from_message(msg)

            if event_name == "ADVERTISEMENT":
                rf_log.info("ADVERTISEMENT key=%s key_prefix=%s", msg.sender.key, msg.sender.key_prefix)
                await self._try_enrich_neighbor_from_contact_lookup(msg)
                await self._maybe_auto_probe_on_advert(msg)

            if event_name in {"PATH_UPDATE", "PATH_RESPONSE", "TRACE_DATA", "RAW_DATA", "RX_LOG_DATA"}:
                details = ""
                control_name = msg.metadata.get("control_subtype_name")
                if control_name:
                    # Keep the high-signal control decode details on the main RF log
                    # line so discover traffic is recognizable without DEBUG mode.
                    detail_parts = [f"control={control_name}"]
                    node_type_name = msg.metadata.get("control_node_type_name")
                    if node_type_name:
                        detail_parts.append(f"node_type={node_type_name}")
                    if msg.metadata.get("control_tag") is not None:
                        detail_parts.append(f"tag={msg.metadata['control_tag']}")
                    if msg.metadata.get("control_discover_snr") is not None:
                        detail_parts.append(f"discover_snr={msg.metadata['control_discover_snr']}")
                    details = " " + " ".join(detail_parts)
                elif msg.metadata.get("likely_retransmit"):
                    detail_parts = [f"pkt_hash={msg.metadata.get('pkt_hash')}"]
                    via = msg.metadata.get("likely_retransmit_via")
                    if via:
                        detail_parts.append(f"likely_retransmit_via={via}")
                    else:
                        detail_parts.append("same_pkt_as_recent=yes")
                    details = " " + " ".join(detail_parts)

                rf_log.info(
                    "%s key=%s key_prefix=%s reachability=%s hops=%s snr=%s rssi=%s path=%s%s",
                    event_name,
                    msg.sender.key,
                    msg.sender.key_prefix,
                    msg.rf.reachability,
                    msg.path.hop_count,
                    msg.rf.snr,
                    msg.rf.rssi,
                    msg.path.raw_path,
                    details,
                )

            return

        self.unhandled_events.add(now, event_name, safe_log_text(repr(payload)))
        system_log.info("Unhandled MeshCore event: %s payload=%s", event_name, safe_log_text(repr(payload)))

    def _build_message_from_mesh_payload(
        self,
        now: int,
        event_name: str,
        payload: dict[str, Any],
        kind: str,
    ) -> BridgeMessage:
        """Build one internal message object from a mesh payload."""
        raw_text = str(payload.get("text", "") or "")
        sender_name = extract_sender_name(payload)
        full_key = extract_full_key(payload)
        key_prefix = extract_key_prefix(payload, full_key)
        channel_idx = payload.get("channel_idx")

        parsed_sender, parsed_body = extract_prefixed_sender(raw_text)
        if not sender_name and parsed_sender:
            sender_name = parsed_sender
            raw_text = parsed_body

        msg = BridgeMessage(
            message_id=str(uuid.uuid4()),
            source="mesh",
            kind="dm" if kind == "dm" else "channel" if kind == "channel" else "system",
            created_at=now,
            text=raw_text,
        )

        normalized_name = None
        if sender_name:
            normalized_name = normalize_sender_name(sender_name, fallback=key_prefix or "unknown")

        msg.sender.name = normalized_name
        msg.sender.display = normalized_name or key_prefix or "unknown"
        msg.sender.key = full_key
        msg.sender.key_prefix = key_prefix
        msg.contains_url = detect_url(msg.text)
        msg.contains_mass_mention = contains_mass_mention(msg.text)
        msg.text_safe_for_log = safe_log_text(msg.text)
        msg.metadata["mesh_event_type"] = event_name
        msg.metadata["raw_payload_preview"] = safe_log_text(repr(payload), max_len=800)

        if channel_idx is not None and int(channel_idx) in self.routes_by_mesh:
            route = self.routes_by_mesh[int(channel_idx)]
            msg.route.route_name = route.name
            msg.route.mesh_channel = route.mesh_channel
            msg.route.discord_channel_id = route.discord_channel_id
            msg.route.webhook_url = route.webhook_url
            msg.route.target = "discord"

        raw_path, hop_count, repeated, direct = decode_mesh_path(payload)
        msg.path.raw_path = raw_path
        msg.path.hop_count = hop_count
        msg.path.repeated = repeated
        msg.path.direct = direct

        snr = payload.get("snr")
        rssi = payload.get("rssi")

        if snr is None or rssi is None:
            nested_sources = [
                payload.get("rf"),
                payload.get("signal"),
                payload.get("decoded"),
                payload.get("contact"),
                payload.get("advert"),
                payload.get("node"),
            ]
            for nested in nested_sources:
                if not isinstance(nested, dict):
                    continue
                if snr is None and nested.get("snr") is not None:
                    snr = nested.get("snr")
                if rssi is None and nested.get("rssi") is not None:
                    rssi = nested.get("rssi")

        if event_name in {"RAW_DATA", "RX_LOG_DATA"}:
            if isinstance(payload.get("snr"), (int, float, str)):
                snr = payload.get("snr")
            if isinstance(payload.get("rssi"), (int, float, str)):
                rssi = payload.get("rssi")

        msg.rf.snr = float(snr) if snr is not None else None
        msg.rf.rssi = float(rssi) if rssi is not None else None

        if msg.rf.snr is not None or msg.rf.rssi is not None:
            msg.metadata["rf_source"] = event_name

        control_info = decode_control_payload(payload)
        if control_info:
            # Preserve decoded control fields on metadata so they are available to
            # logs now and to future command/debug surfaces without re-parsing.
            msg.metadata["control_subtype"] = control_info.get("subtype")
            msg.metadata["control_subtype_name"] = control_info.get("subtype_name")

            if control_info.get("tag") is not None:
                msg.metadata["control_tag"] = control_info["tag"]

            if control_info.get("prefix_only") is not None:
                msg.metadata["control_prefix_only"] = control_info["prefix_only"]

            if control_info.get("type_filter") is not None:
                msg.metadata["control_type_filter"] = control_info["type_filter"]

            if control_info.get("since") is not None:
                msg.metadata["control_since"] = control_info["since"]

            if control_info.get("node_type") is not None:
                msg.metadata["control_node_type"] = control_info["node_type"]
                msg.metadata["control_node_type_name"] = control_info.get("node_type_name")

            if control_info.get("discover_snr") is not None:
                msg.metadata["control_discover_snr"] = control_info["discover_snr"]

            pubkey_hex = control_info.get("pubkey_hex")
            if isinstance(pubkey_hex, str) and pubkey_hex:
                # DISCOVER_RESP can carry either an 8-byte prefix or a full 32-byte
                # public key. When we have it, attach it to the sender so RF logs and
                # neighbor tracking can stop treating the frame as anonymous.
                if control_info.get("pubkey_size") == 32:
                    msg.sender.key = pubkey_hex
                    msg.sender.key_prefix = pubkey_hex[:8]
                else:
                    msg.sender.key_prefix = pubkey_hex[:8]
                if not msg.sender.display or msg.sender.display == "unknown":
                    msg.sender.display = msg.sender.key_prefix or msg.sender.display

        if msg.path.direct:
            msg.rf.reachability = "direct"
        elif msg.path.repeated:
            msg.rf.reachability = "multi_hop"
        else:
            msg.rf.reachability = "unknown"

        msg.rf.raw = dict(payload)
        self._annotate_recent_packet_reuse(msg)

        rf_log.debug(
            "Built mesh message: sender=%r key=%r key_prefix=%r text=%r event=%s",
            msg.sender.display,
            msg.sender.key,
            msg.sender.key_prefix,
            msg.text,
            event_name,
        )

        if event_name == "CHANNEL_MSG_RECV":
            rf_log.debug("CHANNEL_MSG_RECV raw payload: %r", payload)

        if event_name in {"RAW_DATA", "RX_LOG_DATA"}:
            rf_log.debug("%s raw payload: %r", event_name, payload)
            if control_info:
                rf_log.debug("%s decoded control payload: %r", event_name, control_info)

        return msg
