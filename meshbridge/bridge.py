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
    direct_candidates = [payload.get("pubkey"), payload.get("public_key")]
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
        for key in ("pubkey", "public_key"):
            value = obj.get(key)
            if value is not None:
                return str(value)

    return None


def extract_key_prefix(payload: dict[str, Any], full_key: str | None) -> str | None:
    """Extract or derive the display key prefix."""
    direct_candidates = [payload.get("pubkey_prefix"), payload.get("key_prefix")]
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
        for key in ("pubkey_prefix", "key_prefix"):
            value = obj.get(key)
            if value is not None:
                return str(value)[:8]

    if full_key:
        return str(full_key)[:8]

    return None


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

        self.mesh = MeshAdapter(config.serial_port, config.baud_rate)
        self.mesh.set_callback(self.handle_mesh_event)

        self.discord_to_mesh_queue: asyncio.Queue[BridgeMessage] = asyncio.Queue()
        self.mesh_to_discord_queue: asyncio.Queue[BridgeMessage] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task[Any]] = []
        self._mesh_task: asyncio.Task[Any] | None = None
        self._last_auto_probe: dict[str, int] = {}

    def attach_bot(self, bot: Any) -> None:
        """Attach the Discord bot instance."""
        self.bot = bot

    async def start(self) -> None:
        """Start bridge background tasks."""
        await self.webhooks.start()
        self._worker_tasks = [
            asyncio.create_task(self.discord_to_mesh_worker(), name="discord_to_mesh_worker"),
            asyncio.create_task(self.mesh_to_discord_worker(), name="mesh_to_discord_worker"),
            asyncio.create_task(self.persistence_worker(), name="persistence_worker"),
        ]
        self._mesh_task = asyncio.create_task(self.mesh_connection_loop(), name="mesh_connection_loop")

    async def stop(self) -> None:
        """Stop bridge background tasks."""
        if self._mesh_task is not None:
            self._mesh_task.cancel()

        for task in self._worker_tasks:
            task.cancel()

        await self.mesh.disconnect()
        self.neighbors.save()
        await self.webhooks.close()

    async def mesh_connection_loop(self) -> None:
        """Reconnect to MeshCore as needed."""
        delay = self.config.reconnect_initial_delay_seconds

        while True:
            try:
                await self.mesh.connect()
                self.state.mesh_connected = True
                self.state.reconnect_count += 1
                system_log.info("Connected to MeshCore")

                delay = self.config.reconnect_initial_delay_seconds

                while self.state.mesh_connected:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                self.state.mesh_connected = False
                system_log.exception("Mesh connection loop error: %s", exc)

            await asyncio.sleep(delay)
            delay = min(delay * 2, self.config.reconnect_max_delay_seconds)

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
                f"Recent Messages Buffered: {len(self.history.recent())}",
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
                self.neighbors.update_from_message(msg)
                self.mesh_to_discord_queue.task_done()

    async def persistence_worker(self) -> None:
        """Periodically persist compact neighbor state."""
        while True:
            await asyncio.sleep(30)
            self.neighbors.save()

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
        traffic_log.info("Discord -> Mesh route=%s sender=%s text=%r", msg.route.route_name, resolve_sender_display(msg), msg.text)

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
                user = await self.bot.fetch_user(self.config.mesh_dm_user_id)
                await user.send(text, allowed_mentions=self.bot.allowed_mentions_none())
                traffic_log.info("Mesh DM -> Discord user sender=%s text=%r", resolve_sender_display(msg), msg.text)
            elif self.config.mesh_dm_channel_id:
                channel = self.bot.get_channel(self.config.mesh_dm_channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.config.mesh_dm_channel_id)
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
            return

        canonical = (msg.sender.key_prefix or key[:8]).lower()
        now_ts = msg.created_at
        last_ts = self._last_auto_probe.get(canonical, 0)

        if now_ts - last_ts < self.config.auto_probe_min_interval_seconds:
            return

        try:
            await self.mesh.send_path_discovery(key)
            self._last_auto_probe[canonical] = now_ts
            rf_log.info("Auto path discovery sent for key=%s", key)
        except Exception as exc:
            rf_log.warning("Auto path discovery failed for key=%s: %s", key, exc)

    async def handle_mesh_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Handle one MeshCore event."""
        now = int(time.time())

        if event_name == "CHANNEL_MSG_RECV":
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="channel")
            self.neighbors.update_from_message(msg)

            if msg.sender.name and not msg.sender.key and not msg.sender.key_prefix:
                upgraded = self.neighbors.upgrade_recent_unnamed_neighbor(
                    route_name=msg.route.route_name,
                    msg=msg,
                    max_age_seconds=120,
                )
                if upgraded:
                    rf_log.info("Heuristically upgraded recent unnamed neighbor to %s", msg.sender.name)

            await self.enqueue_mesh_message(msg)
            return

        if event_name == "CONTACT_MSG_RECV":
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="dm")
            self.neighbors.update_from_message(msg)
            await self.enqueue_mesh_message(msg)
            return

        if event_name in {"ADVERTISEMENT", "PATH_UPDATE", "PATH_RESPONSE", "TRACE_DATA"}:
            msg = self._build_message_from_mesh_payload(now, event_name, payload, kind="system")
            self.neighbors.update_from_message(msg)

            if event_name == "ADVERTISEMENT":
                rf_log.info("ADVERTISEMENT key=%s key_prefix=%s", msg.sender.key, msg.sender.key_prefix)
                await self._try_enrich_neighbor_from_contact_lookup(msg)
                await self._maybe_auto_probe_on_advert(msg)

            if event_name in {"PATH_UPDATE", "PATH_RESPONSE", "TRACE_DATA"}:
                rf_log.info(
                    "%s key=%s key_prefix=%s reachability=%s hops=%s snr=%s rssi=%s path=%s",
                    event_name,
                    msg.sender.key,
                    msg.sender.key_prefix,
                    msg.rf.reachability,
                    msg.path.hop_count,
                    msg.rf.snr,
                    msg.rf.rssi,
                    msg.path.raw_path,
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

        path = payload.get("path") or payload.get("hops") or []
        if isinstance(path, list):
            msg.path.raw_path = [str(item) for item in path]
            msg.path.hop_count = len(path)
            msg.path.repeated = len(path) > 1
            msg.path.direct = len(path) <= 1

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

        msg.rf.snr = float(snr) if snr is not None else None
        msg.rf.rssi = float(rssi) if rssi is not None else None

        if msg.path.direct:
            msg.rf.reachability = "direct"
        elif msg.path.repeated:
            msg.rf.reachability = "multi_hop"
        else:
            msg.rf.reachability = "unknown"

        msg.rf.raw = dict(payload)

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

        return msg
