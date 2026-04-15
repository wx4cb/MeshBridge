"""Discord webhook sender for Mesh → Discord messages."""

from __future__ import annotations

import aiohttp
import discord

from meshbridge.security import sanitize_webhook_username


class WebhookSender:
    """Send plain-text messages to Discord via webhook."""

    def __init__(self, timeout_seconds: float, fixed_avatar_url: str) -> None:
        self.timeout_seconds = timeout_seconds
        self.fixed_avatar_url = fixed_avatar_url
        self._session: aiohttp.ClientSession | None = None
        self._webhooks: dict[str, discord.Webhook] = {}

    async def start(self) -> None:
        """Start the sender session."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        """Close the sender session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._webhooks.clear()

    def _get_webhook(self, url: str) -> discord.Webhook:
        """Return a cached webhook object."""
        if self._session is None:
            raise RuntimeError("WebhookSender.start() must be called first")
        if url not in self._webhooks:
            self._webhooks[url] = discord.Webhook.from_url(url, session=self._session)
        return self._webhooks[url]

    async def send(self, webhook_url: str, display_name: str, content: str) -> None:
        """Send one webhook message."""
        webhook = self._get_webhook(webhook_url)
        await webhook.send(
            content=content,
            username=sanitize_webhook_username(display_name),
            avatar_url=self.fixed_avatar_url,
            allowed_mentions=discord.AllowedMentions.none(),
        )
