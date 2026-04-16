"""Discord bot implementation for MeshBridge."""

from __future__ import annotations

import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from meshbridge.config import AppConfig
from meshbridge.models import BridgeMessage
from meshbridge.permissions import is_admin_user
from meshbridge.security import contains_mass_mention, detect_url, normalize_sender_name, safe_log_text

log = logging.getLogger(__name__)


def format_neighbor_label(name: str | None, key: str | None) -> str:
    """Format a readable label for neighbor/node output."""
    key = key or "unknown"
    short_key = key[:8] if not key.startswith("name:") else "unknown"

    if key.startswith("name:"):
        if name:
            return f"{name} (provisional)"
        return "unknown (provisional)"

    if name:
        return name

    return short_key


def is_provisional_neighbor_key(key: str | None) -> bool:
    """Return True if the neighbor key is a provisional placeholder."""
    return bool(key) and key.startswith("name:")


class MeshBridgeBot(commands.Bot):
    """Discord bot for bridge control and Discord-side ingestion."""

    def __init__(self, config: AppConfig, bridge) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=config.discord_application_id,
        )
        self.config = config
        self.bridge = bridge

    async def setup_hook(self) -> None:
        """Initialize background bridge tasks and sync slash commands."""
        await self.bridge.start()
        self.tree.add_command(self._build_bridge_group())
        self.tree.add_command(self._build_mesh_group())
        self.tree.add_command(self._build_neighbors_group())
        self.tree.add_command(self._build_nodes_group())
        guild = discord.Object(id=self.config.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def close(self) -> None:
        """Shut down cleanly."""
        await self.bridge.stop()
        await super().close()

    @staticmethod
    def allowed_mentions_none() -> discord.AllowedMentions:
        """Return a safe no-mentions policy."""
        return discord.AllowedMentions.none()

    async def on_ready(self) -> None:
        """Log ready state."""
        log.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "unknown"))

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages for bridge routing."""
        if message.author.bot:
            return

        route = self.bridge.routes_by_discord.get(message.channel.id)
        if route is None:
            return

        parts: list[str] = []
        if message.content and message.content.strip():
            parts.append(message.content.strip())

        for attachment in message.attachments:
            parts.append(f"[attachment] {attachment.filename}: {attachment.url}")

        if not parts:
            return

        text = " | ".join(parts)
        sender_name = normalize_sender_name(message.author.display_name or message.author.name)

        msg = BridgeMessage(
            message_id=str(uuid.uuid4()),
            source="discord",
            kind="channel",
            created_at=int(time.time()),
            text=text,
        )
        msg.sender.name = sender_name
        msg.sender.display = sender_name
        msg.route.route_name = route.name
        msg.route.mesh_channel = route.mesh_channel
        msg.route.discord_channel_id = route.discord_channel_id
        msg.route.webhook_url = route.webhook_url
        msg.route.target = "mesh"
        msg.contains_url = detect_url(msg.text)
        msg.contains_mass_mention = contains_mass_mention(msg.text)
        msg.text_safe_for_log = safe_log_text(msg.text)
        msg.metadata["discord_message_id"] = message.id
        msg.metadata["discord_channel_id"] = message.channel.id

        await self.bridge.enqueue_discord_message(msg)

    def _build_bridge_group(self) -> app_commands.Group:
        """Create the /bridge command group."""
        group = app_commands.Group(name="bridge", description="Bridge control commands")

        @group.command(name="pause", description="Pause all bridge traffic")
        async def pause_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            self.bridge.state.global_paused = True
            await interaction.response.send_message("Bridge paused.", ephemeral=True)

        @group.command(name="resume", description="Resume all bridge traffic")
        async def resume_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            self.bridge.state.global_paused = False
            await interaction.response.send_message("Bridge resumed.", ephemeral=True)

        @group.command(name="status", description="Show bridge status")
        async def status_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            text = self.bridge.build_version_text()
            await interaction.response.send_message(text, ephemeral=True)

        @group.command(name="version", description="Show version and host stats")
        async def version_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            text = self.bridge.build_version_text()
            await interaction.response.send_message(text, ephemeral=True)

        @group.command(name="unhandled", description="Show recent unhandled mesh events")
        async def unhandled_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            rows = self.bridge.unhandled_events.recent()[:10]
            if not rows:
                await interaction.response.send_message("No unhandled events seen.", ephemeral=True)
                return
            lines = [f"{event_type}: {preview}" for _, event_type, preview in rows]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        return group

    def _build_mesh_group(self) -> app_commands.Group:
        """Create the /mesh command group."""
        group = app_commands.Group(name="mesh", description="Mesh control commands")

        @group.command(name="advert", description="Send a mesh advert")
        @app_commands.describe(flood="Flood the advert through the mesh")
        async def advert_cmd(interaction: discord.Interaction, flood: bool = False) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                await self.bridge.mesh.send_advert(flood=flood)
            except Exception as exc:
                await interaction.edit_original_response(content=f"Advert failed: {exc}")
                return

            await interaction.edit_original_response(content=f"Advert sent (flood={flood}).")

        return group

    def _build_neighbors_group(self) -> app_commands.Group:
        """Create the /neighbors command group."""
        group = app_commands.Group(name="neighbors", description="Neighbor inspection commands")

        @group.command(name="list", description="List recent neighbors")
        async def list_cmd(interaction: discord.Interaction) -> None:
            rows = self.bridge.neighbors.list_recent()[:10]
            if not rows:
                await interaction.response.send_message("No neighbors known yet.", ephemeral=True)
                return

            lines = []
            for row in rows:
                label = format_neighbor_label(row.name, row.key)
                lines.append(
                    f"{label} | key={row.key} | reachability={row.reachability} | "
                    f"hops={row.hop_count} | last_seen={row.last_seen}"
                )

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @group.command(name="show", description="Show one neighbor by key prefix")
        async def show_cmd(interaction: discord.Interaction, prefix: str) -> None:
            row = self.bridge.neighbors.get(prefix)
            if row is None:
                await interaction.response.send_message("Neighbor not found.", ephemeral=True)
                return

            provisional = is_provisional_neighbor_key(row.key)
            label = format_neighbor_label(row.name, row.key)
            confirmed_name = row.name if not provisional else None

            text = "\n".join(
                [
                    f"display_name={label}",
                    f"confirmed_name={confirmed_name}",
                    f"provisional={provisional}",
                    f"key={row.key}",
                    f"last_seen={row.last_seen}",
                    f"reachability={row.reachability}",
                    f"hop_count={row.hop_count}",
                    f"snr={row.snr}",
                    f"rssi={row.rssi}",
                    f"rf_source={getattr(row, 'rf_source', None)}",
                    f"path={row.path}",
                    f"source={row.source}",
                ]
            )
            await interaction.response.send_message(text, ephemeral=True)

        @group.command(name="probe", description="Probe a neighbor by key prefix")
        async def probe_cmd(interaction: discord.Interaction, prefix: str) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return

            row = self.bridge.neighbors.get(prefix)
            if row is None:
                await interaction.response.send_message("Neighbor not found.", ephemeral=True)
                return

            if is_provisional_neighbor_key(row.key):
                await interaction.response.send_message(
                    "That node is still provisional and does not have a confirmed mesh key yet.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)

            try:
                await self.bridge.mesh.send_path_discovery(row.key)
            except Exception as exc:
                await interaction.edit_original_response(content=f"Probe failed: {exc}")
                return

            await interaction.edit_original_response(content=f"Probe sent for {row.key}.")

        return group

    def _build_nodes_group(self) -> app_commands.Group:
        """Create the /nodes command group."""
        group = app_commands.Group(name="nodes", description="Known node inspection commands")

        @group.command(name="list", description="List all currently known nodes")
        async def list_cmd(interaction: discord.Interaction) -> None:
            rows = self.bridge.neighbors.list_recent()
            if not rows:
                await interaction.response.send_message("No known nodes yet.", ephemeral=True)
                return

            lines: list[str] = []
            for row in rows[:25]:
                label = format_neighbor_label(row.name, row.key)
                lines.append(
                    f"{label} | key={row.key} | reachability={row.reachability} | "
                    f"hops={row.hop_count} | snr={row.snr} | rssi={row.rssi}"
                )

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        return group
