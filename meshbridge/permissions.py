"""Discord permission helpers."""

from __future__ import annotations

import discord


def is_admin_user(interaction: discord.Interaction) -> bool:
    """Return True if the invoking user has administrator permission."""
    user = interaction.user
    return isinstance(user, discord.Member) and user.guild_permissions.administrator
