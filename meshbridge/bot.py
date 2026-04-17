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
        return f"{name} ({short_key})"

    return short_key


def is_provisional_neighbor_key(key: str | None) -> bool:
    """Return True if the neighbor key is a provisional placeholder."""
    return bool(key) and key.startswith("name:")


def short_node_key(key: str | None) -> str:
    """Return an operator-friendly 4-byte node prefix when possible."""
    if not key:
        return "unknown"
    if key.startswith("name:"):
        return key
    return key[:8]


def format_path_hop(bridge, hop: str) -> str:
    """Render one observed path hop with best-effort node resolution.

    MeshCore packets may carry 1-byte, 2-byte, or longer hop hashes depending
    on how the packet was encoded. We preserve the exact hop text seen on the
    wire and only expand it when the local neighbor table can resolve that hop
    unambiguously to a known node. For Discord output we stop at a 4-byte node
    prefix (8 hex chars), which is usually enough to be useful without making
    the path unreadably long.
    """
    needle = str(hop).strip().lower()
    if not needle:
        return "unknown"

    matches = []
    for row in bridge.neighbors.list_recent():
        if is_provisional_neighbor_key(row.key):
            continue

        key = (row.key or "").lower()
        key_prefix = key[:8]
        if key.startswith(needle) or key_prefix.startswith(needle):
            matches.append(row)

    # If we cannot resolve the hop locally, keep the raw on-air hash.
    if not matches:
        return needle

    # A unique match lets us expand the short hop into a stable 4-byte prefix.
    if len(matches) == 1:
        row = matches[0]
        return row.key[:8]

    # Multiple candidates sharing the same short hop means the packet did not
    # carry enough path width to disambiguate them. Show the ambiguity plainly.
    candidates = ", ".join(sorted({row.key[:8] for row in matches})[:3])
    return f"{needle}(ambiguous:{candidates})"


def format_observed_path(bridge, path: list[str]) -> str:
    """Render an observed message path for Discord command output."""
    if not path:
        return ""
    return " -> ".join(format_path_hop(bridge, hop) for hop in path)


def has_node_list_signal(row) -> bool:
    """Return True when a node row has useful operator-facing signal."""
    if is_provisional_neighbor_key(row.key):
        return True
    if row.name:
        return True
    if row.reachability not in (None, "unknown"):
        return True
    if row.hop_count is not None:
        return True
    if row.snr is not None or row.rssi is not None:
        return True
    return bool(row.path)


def format_node_list_line(bridge, row) -> str:
    """Format one operator-friendly line for `/nodes list`."""
    label = format_neighbor_label(row.name, row.key)
    details = [f"{label} | key={short_node_key(row.key)}"]

    if row.reachability not in (None, "unknown"):
        details.append(f"reachability={row.reachability}")

    if row.hop_count is not None:
        details.append(f"hops={row.hop_count}")

    path_text = format_observed_path(bridge, row.path)
    if path_text:
        details.append(f"path={path_text}")

    if row.snr is not None:
        details.append(f"snr={row.snr}")

    if row.rssi is not None:
        details.append(f"rssi={row.rssi}")

    return " | ".join(details)


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
            rows = self.bridge.unhandled_events.recent(limit=10)
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

        @group.command(name="discover", description="Send a MeshCore discover request")
        @app_commands.describe(
            filter_bits="MeshCore advert-type filter bitmask; 6 matches the MeshMapper-style repeater/infra ping",
            prefix_only="Ask responders to return only a pubkey prefix instead of a full key",
            since="Optional last-modified timestamp filter; use 0 for a full discover",
        )
        async def discover_cmd(
            interaction: discord.Interaction,
            filter_bits: app_commands.Range[int, 0, 255] = 6,
            prefix_only: bool = False,
            since: int = 0,
        ) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                # This sends a real MeshCore DISCOVER_REQ from the companion-side
                # radio. It is best thought of as "what can this local radio elicit
                # nearby right now?" which is usually a good proxy for a co-sited
                # repeater, but not a remote repeater's full internal neighbor list.
                result = await self.bridge.mesh.send_node_discover_req(
                    filter_bits=filter_bits,
                    prefix_only=prefix_only,
                    since=since,
                )
            except Exception as exc:
                await interaction.edit_original_response(content=f"Discover failed: {exc}")
                return

            tag = None
            if getattr(result, "payload", None):
                tag = result.payload.get("tag")

            content = (
                f"Discover request sent (filter_bits={filter_bits}, prefix_only={prefix_only}, since={since}, tag={tag}). "
                "Watch the RF logs for DISCOVER_RESP frames."
            )
            await interaction.edit_original_response(content=content)

        @group.command(name="packets", description="Show recent observed packet propagation summaries")
        async def packets_cmd(interaction: discord.Interaction) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return

            rows = self.bridge.list_recent_packet_paths(limit=10)
            if not rows:
                await interaction.response.send_message("No recent packet observations yet.", ephemeral=True)
                return

            lines = []
            for row in rows:
                pkt_hash = row["pkt_hash"]
                control = row.get("control_subtype_name")
                control_text = f" | control={control}" if control else ""
                resolved_path = format_observed_path(self.bridge, row.get("latest_path") or [])
                path_text = f" | path={resolved_path}" if resolved_path else ""
                lines.append(
                    f"pkt_hash={pkt_hash} | seen={row['count']} | observed={row['path_summary']}{path_text} | "
                    f"reachability={row['latest_reachability']} | snr={row['latest_snr']} | rssi={row['latest_rssi']}{control_text}"
                )

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @group.command(name="packet", description="Show one packet's observed propagation path")
        @app_commands.describe(pkt_hash="Packet hash in decimal or hex (for example 3158068015 or 0xbc3f1234)")
        async def packet_cmd(interaction: discord.Interaction, pkt_hash: str) -> None:
            if not is_admin_user(interaction):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return

            details = self.bridge.get_packet_path_details(pkt_hash)
            if details is None:
                await interaction.response.send_message("Packet hash not found in recent observations.", ephemeral=True)
                return

            # Present the operator view as an observed propagation history rather
            # than a guaranteed protocol-level end-to-end route.
            lines = [
                f"pkt_hash={details['pkt_hash']}",
                f"first_seen={details['first_seen']}",
                f"last_seen={details['last_seen']}",
                f"sightings={details['count']}",
                f"observed_path={details['path_summary']}",
            ]
            resolved_latest_path = format_observed_path(self.bridge, details["latest_path"])
            if resolved_latest_path:
                lines.append(f"path={resolved_latest_path}")

            for index, sighting in enumerate(details["sightings"], start=1):
                control = sighting.get("control_subtype_name")
                control_text = f" control={control}" if control else ""
                resolved = format_observed_path(self.bridge, sighting["path"])
                resolved_text = f" resolved={resolved}" if resolved else ""
                lines.append(
                    f"{index}. ts={sighting['ts']} reachability={sighting['reachability']} "
                    f"path={sighting['path']}{resolved_text} "
                    f"snr={sighting['snr']} rssi={sighting['rssi']}{control_text}"
                )

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        return group

    def _build_neighbors_group(self) -> app_commands.Group:
        """Create the /neighbors command group."""
        group = app_commands.Group(name="neighbors", description="Neighbor inspection commands")

        @group.command(name="list", description="List recent neighbors")
        async def list_cmd(interaction: discord.Interaction) -> None:
            rows = self.bridge.neighbors.list_recent(limit=10)
            if not rows:
                await interaction.response.send_message("No neighbors known yet.", ephemeral=True)
                return

            lines = []
            for row in rows:
                if has_node_list_signal(row):
                    line = format_node_list_line(self.bridge, row)
                else:
                    label = format_neighbor_label(row.name, row.key)
                    line = f"{label} | key={short_node_key(row.key)}"
                lines.append(f"{line} | last_seen={row.last_seen}")

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
                    f"key={short_node_key(row.key)}",
                    f"last_seen={row.last_seen}",
                    f"reachability={row.reachability}",
                    f"hop_count={row.hop_count}",
                    f"snr={row.snr}",
                    f"rssi={row.rssi}",
                    f"rf_source={getattr(row, 'rf_source', None)}",
                    f"path={row.path}",
                    f"resolved_path={format_observed_path(self.bridge, row.path) or 'direct/none'}",
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

            await interaction.edit_original_response(content=f"Probe sent for {short_node_key(row.key)}.")

        return group

    def _build_nodes_group(self) -> app_commands.Group:
        """Create the /nodes command group."""
        group = app_commands.Group(name="nodes", description="Known node inspection commands")

        @group.command(name="list", description="List all currently known nodes")
        async def list_cmd(interaction: discord.Interaction) -> None:
            rows = [
                row for row in self.bridge.neighbors.list_recent()
                if has_node_list_signal(row)
            ][:25]
            if not rows:
                await interaction.response.send_message("No actionable nodes yet.", ephemeral=True)
                return

            lines = [format_node_list_line(self.bridge, row) for row in rows]

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        return group
