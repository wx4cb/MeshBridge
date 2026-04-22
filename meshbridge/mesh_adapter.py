"""MeshCore integration adapter.

This module intentionally isolates MeshCore-specific behavior so the rest of
the project can remain stable even if the local MeshCore Python APIs differ.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable


MeshEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
log = logging.getLogger("meshbridge.system")


class MeshAdapter:
    """Thin wrapper around the MeshCore Python library."""

    def __init__(
        self,
        connection_type: str,
        serial_port: str,
        baud_rate: int,
        tcp_host: str,
        tcp_port: int,
    ) -> None:
        self.connection_type = connection_type
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self._client: Any = None
        self._callback: MeshEventCallback | None = None

    async def connect(self) -> None:
        """Connect to MeshCore."""
        try:
            from meshcore import EventType, MeshCore  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("MeshCore package is not installed or import failed") from exc

        self._event_type = EventType
        if self.connection_type == "serial":
            if not self.serial_port:
                raise RuntimeError("serial_port is required when mesh_connection_type is serial")
            log.info("Connecting to MeshCore over serial port=%s baud_rate=%s", self.serial_port, self.baud_rate)
            self._client = await MeshCore.create_serial(self.serial_port, self.baud_rate)
        elif self.connection_type == "tcp":
            if not hasattr(MeshCore, "create_tcp"):
                raise RuntimeError("MeshCore TCP connection helper is unavailable")
            log.info("Connecting to MeshCore over TCP host=%s port=%s", self.tcp_host, self.tcp_port)
            self._client = await MeshCore.create_tcp(self.tcp_host, self.tcp_port)
        else:
            raise RuntimeError(f"Unsupported mesh_connection_type: {self.connection_type}")

        if self._client is None:
            raise RuntimeError("MeshCore connection failed")

        if hasattr(self._client, "start_auto_message_fetching"):
            await self._client.start_auto_message_fetching()

        async def _forward(event: Any) -> None:
            if self._callback is None:
                return
            event_name = getattr(getattr(event, "type", None), "name", "UNKNOWN")
            payload = getattr(event, "payload", None) or {}
            await self._callback(event_name, payload)

        candidates = [
            "CHANNEL_MSG_RECV",
            "CONTACT_MSG_RECV",
            "ADVERTISEMENT",
            "PATH_UPDATE",
            "PATH_RESPONSE",
            "TRACE_DATA",
            "RAW_DATA",
            "RX_LOG_DATA",
            "ERROR",
        ]
        self._subscriptions: list[Any] = []

        for name in candidates:
            event_type = getattr(self._event_type, name, None)
            if event_type is None:
                continue
            if hasattr(self._client, "subscribe"):
                token = self._client.subscribe(event_type, _forward)
                self._subscriptions.append(token)

    async def disconnect(self) -> None:
        """Disconnect from MeshCore."""
        if self._client is None:
            return

        try:
            if hasattr(self._client, "stop_auto_message_fetching"):
                await self._client.stop_auto_message_fetching()
            if hasattr(self._client, "disconnect"):
                await self._client.disconnect()
        finally:
            self._client = None

    def create_disconnect_waiters(self) -> list[Awaitable[Any]]:
        """Return awaitables that resolve when the client disconnects."""
        if self._client is None:
            return []

        waiters: list[Awaitable[Any]] = []

        for attr_name in ("wait_closed", "wait_disconnected", "wait_for_disconnect"):
            fn = getattr(self._client, attr_name, None)
            if not callable(fn):
                continue
            try:
                waiter = fn()
            except TypeError:
                continue
            if asyncio.isfuture(waiter) or asyncio.iscoroutine(waiter):
                waiters.append(waiter)

        for attr_name in ("disconnected_event", "disconnect_event", "closed_event"):
            event = getattr(self._client, attr_name, None)
            if isinstance(event, asyncio.Event):
                waiters.append(event.wait())

        return waiters

    def set_callback(self, callback: MeshEventCallback) -> None:
        """Set the bridge event callback."""
        self._callback = callback

    async def send_channel_text(self, channel_idx: int, text: str) -> None:
        """Send one channel message."""
        if self._client is None:
            raise RuntimeError("MeshAdapter is not connected")

        commands = getattr(self._client, "commands", None)
        if commands is None or not hasattr(commands, "send_chan_msg"):
            raise RuntimeError("MeshCore send_chan_msg command is unavailable")

        await commands.send_chan_msg(channel_idx, text)

    async def send_advert(self, flood: bool = False) -> None:
        """Send an advert."""
        if self._client is None:
            raise RuntimeError("MeshAdapter is not connected")

        commands = getattr(self._client, "commands", None)
        if commands is None or not hasattr(commands, "send_advert"):
            raise RuntimeError("MeshCore send_advert command is unavailable")

        await commands.send_advert(flood=flood)

    async def send_path_discovery(self, dst: str) -> Any:
        """Send path discovery for a destination key or prefix.

        Prefer the sync helper when available because newer meshcore versions
        explicitly recommend it.
        """
        if self._client is None:
            raise RuntimeError("MeshAdapter is not connected")

        commands = getattr(self._client, "commands", None)
        if commands is None:
            raise RuntimeError("MeshCore commands API is unavailable")

        if hasattr(commands, "send_path_discovery_sync"):
            return await commands.send_path_discovery_sync(dst)

        if hasattr(commands, "send_path_discovery"):
            return await commands.send_path_discovery(dst)

        raise RuntimeError("MeshCore path discovery command is unavailable")

    async def send_node_discover_req(
        self,
        filter_bits: int,
        prefix_only: bool = False,
        since: int | None = None,
    ) -> Any:
        """Send a MeshCore NODE_DISCOVER_REQ control packet.

        This uses the control-data helper exposed by recent meshcore Python
        bindings. The request is emitted by the companion-connected device
        itself, so the resulting DISCOVER_RESP frames represent what that local
        radio can directly elicit over RF.
        """
        if self._client is None:
            raise RuntimeError("MeshAdapter is not connected")

        commands = getattr(self._client, "commands", None)
        if commands is None:
            raise RuntimeError("MeshCore commands API is unavailable")

        if hasattr(commands, "send_node_discover_req"):
            return await commands.send_node_discover_req(
                filter=filter_bits,
                prefix_only=prefix_only,
                since=since,
            )

        raise RuntimeError("MeshCore node discover request command is unavailable")

    async def send_trace(self, auth_code: int, tag: int, flags: int, path: list[str] | None = None) -> Any:
        """Send a trace request."""
        if self._client is None:
            raise RuntimeError("MeshAdapter is not connected")

        commands = getattr(self._client, "commands", None)
        if commands is None or not hasattr(commands, "send_trace"):
            raise RuntimeError("MeshCore send_trace command is unavailable")

        return await commands.send_trace(auth_code, tag, flags, path=path)

    async def get_contact_name_by_key_prefix(self, key_prefix: str) -> str | None:
        """Try to resolve a contact name by key prefix."""
        if self._client is None:
            return None

        candidates: list[Any] = []

        candidates.append(getattr(self._client, "get_contact_by_key_prefix", None))

        commands = getattr(self._client, "commands", None)
        if commands is not None:
            candidates.append(getattr(commands, "get_contact_by_key_prefix", None))

        for fn in candidates:
            if fn is None:
                continue
            try:
                result = fn(key_prefix)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception:
                continue

            if isinstance(result, dict):
                for key in ("adv_name", "name", "contact_name", "display_name"):
                    value = result.get(key)
                    if isinstance(value, str) and value.strip():
                        return value

        return None

    async def sleep_briefly(self, seconds: float) -> None:
        """Sleep briefly between chunk sends."""
        await asyncio.sleep(seconds)
