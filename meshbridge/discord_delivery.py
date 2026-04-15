"""Discord delivery helpers for MeshBridge.

This module is responsible for sending:
- Mesh -> Discord messages through webhooks
- bridge/system notices through the bot client

Design goals:
- plain text only
- no markup/HTML/embeds
- safe webhook usernames
- fixed avatar for Mesh-originated messages
- no mention expansion
"""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp
import discord

from meshbridge.models import BridgeMessage, Route

LOG = logging.getLogger(__name__)


def sanitize_webhook_username(value: str | None) -> str:
    """Return a safe Discord webhook username.

    Discord webhook usernames should be short, single-line, and free from
    control characters. This function keeps the name human-readable while
    preventing odd rendering and obvious injection attempts.

    Args:
        value: Candidate display name.

    Returns:
        A sanitized username suitable for Discord webhooks.
    """
    if not value:
        return "unknown"

    # Collapse whitespace and remove line breaks/control-ish formatting.
    cleaned = " ".join(str(value).split()).strip()

    if not cleaned:
        return "unknown"

    # Avoid reserved-looking names and absurdly long values.
    cleaned = cleaned.replace("@everyone", "@ everyone")
    cleaned = cleaned.replace("@here", "@ here")

    # Keep it conservative.
    return cleaned[:80]


def get_sender_display_name(msg: BridgeMessage) -> str:
    """Resolve the best sender display name from a bridge message.

    Order of preference:
    1. explicit display field
    2. sender name
    3. key prefix
    4. fallback "unknown"

    Args:
        msg: The bridge message.

    Returns:
        Human-readable sender display name.
    """
    sender = getattr(msg, "sender", None)
    if sender is None:
        return "unknown"

    return sanitize_webhook_username(
        getattr(sender, "display", None)
        or getattr(sender, "name", None)
        or getattr(sender, "key_prefix", None)
        or "unknown"
    )


def format_mesh_to_discord_content(msg: BridgeMessage, include_sender_prefix: bool = False) -> str:
    """Format plain-text content for a Mesh -> Discord message.

    Since the webhook username already shows the Mesh node name, the default
    behavior is to send only the message text. During debugging, you can
    enable include_sender_prefix to keep the sender duplicated in the body.

    Args:
        msg: The bridge message.
        include_sender_prefix: Whether to prefix the message body with the
            sender display name.

    Returns:
        Plain-text message content.
    """
    text = (getattr(msg, "text", "") or "").strip()
    sender = get_sender_display_name(msg)

    if not text:
        return sender

    if include_sender_prefix:
        return f"{sender}: {text}"

    return text


def format_system_notice(content: str) -> str:
    """Normalize a bridge/system notice to plain text.

    Args:
        content: Notice body.

    Returns:
        Normalized plain-text notice.
    """
    return " ".join((content or "").split()).strip()


class DiscordDelivery:
    """Send bridged messages into Discord.

    This helper separates normal bot sends from webhook sends so the bridge
    can present Mesh-originated traffic with per-node display names while
    keeping admin/status messages under the real bot identity.
    """

    def __init__(
        self,
        bot: discord.Client,
        webhook_timeout_seconds: float,
        meshcore_avatar_url: str,
        include_mesh_sender_prefix_in_body: bool = False,
    ) -> None:
        """Initialize the delivery helper.

        Args:
            bot: Active Discord client.
            webhook_timeout_seconds: Timeout for webhook delivery.
            meshcore_avatar_url: Fixed avatar URL used for Mesh messages.
            include_mesh_sender_prefix_in_body: Whether Mesh -> Discord
                content should also include the sender prefix in the body.
        """
        self.bot = bot
        self.webhook_timeout_seconds = webhook_timeout_seconds
        self.meshcore_avatar_url = meshcore_avatar_url
        self.include_mesh_sender_prefix_in_body = include_mesh_sender_prefix_in_body
        self._webhook_cache: dict[str, discord.Webhook] = {}

    async def send_mesh_message(self, route: Route, msg: BridgeMessage) -> None:
        """Send a Mesh-originated message to Discord via webhook.

        Args:
            route: Route configuration for the target Discord channel.
            msg: Bridge message created from Mesh ingress.
        """
        webhook = await self._get_webhook(route.webhook_url)

        username = get_sender_display_name(msg)
        content = format_mesh_to_discord_content(
            msg,
            include_sender_prefix=self.include_mesh_sender_prefix_in_body,
        )

        LOG.debug(
            "Sending Mesh -> Discord via webhook: route=%s username=%r content=%r",
            route.name,
            username,
            content,
        )

        # AllowedMentions.none() ensures bridged content cannot ping roles/users.
        await webhook.send(
            content=content,
            username=username,
            avatar_url=self.meshcore_avatar_url,
            wait=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def send_mesh_dm_notice(self, channel_id: int, msg: BridgeMessage) -> None:
        """Send a Mesh DM into the configured private Discord room.

        Args:
            channel_id: Discord channel ID where Mesh DMs should be posted.
            msg: Bridge message representing the Mesh DM.
        """
        channel = await self._get_messageable_channel(channel_id)
        sender = get_sender_display_name(msg)
        body = (getattr(msg, "text", "") or "").strip()

        if body:
            content = f"DM from {sender}: {body}"
        else:
            content = f"DM from {sender}"

        LOG.debug("Sending Mesh DM notice to Discord channel %s", channel_id)
        await channel.send(
            content,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def send_system_notice(self, channel_id: int, content: str) -> None:
        """Send a bridge/system notice using the bot identity.

        Args:
            channel_id: Discord channel ID.
            content: Plain-text notice body.
        """
        channel = await self._get_messageable_channel(channel_id)
        normalized = format_system_notice(content)

        LOG.debug("Sending system notice to channel %s: %r", channel_id, normalized)
        await channel.send(
            normalized,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _get_webhook(self, webhook_url: str) -> discord.Webhook:
        """Return a cached Discord webhook client.

        Args:
            webhook_url: Full Discord webhook URL.

        Returns:
            Discord webhook object.
        """
        webhook_url = webhook_url.strip()
        cached = self._webhook_cache.get(webhook_url)
        if cached is not None:
            return cached

        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.webhook_timeout_seconds)
        )
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        self._webhook_cache[webhook_url] = webhook
        return webhook

    async def _get_messageable_channel(self, channel_id: int) -> discord.abc.Messageable:
        """Fetch or resolve a Discord channel that supports sending messages.

        Args:
            channel_id: Discord channel ID.

        Returns:
            A messageable Discord channel.

        Raises:
            RuntimeError: If the channel cannot be resolved or is not messageable.
        """
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"Channel {channel_id} is not messageable")

        return channel

    async def close(self) -> None:
        """Close any cached webhook HTTP sessions."""
        for webhook in self._webhook_cache.values():
            session = getattr(webhook, "session", None)
            if session is not None and not session.closed:
                await session.close()
        self._webhook_cache.clear()
