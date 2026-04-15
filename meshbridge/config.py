"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import hjson

from meshbridge.models import Route


@dataclass(slots=True)
class AppConfig:
    """Application configuration."""

    discord_token: str
    discord_application_id: int
    discord_guild_id: int
    mesh_dm_channel_id: int | None
    mesh_dm_user_id: int | None
    meshcore_avatar_url: str
    serial_port: str
    baud_rate: int
    debug: bool
    log_level: str
    log_mode: str
    log_file: str
    max_message_history: int
    max_unhandled_events: int
    neighbor_cache_file: str
    neighbor_cache_limit: int
    rate_limit_window_seconds: int
    rate_limit_max_messages: int
    mesh_chunk_size: int
    mesh_chunk_delay_seconds: float
    webhook_timeout_seconds: float
    reconnect_initial_delay_seconds: float
    reconnect_max_delay_seconds: float
    auto_probe_on_advert: bool
    auto_probe_min_interval_seconds: int
    routes: list[Route]

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        """Load configuration from an HJSON or JSON file."""
        raw = hjson.loads(path.read_text(encoding="utf-8"))

        routes = [
            Route(
                name=str(route["name"]),
                mesh_channel=int(route["mesh_channel"]),
                discord_channel_id=int(route["discord_channel_id"]),
                webhook_url=str(route["webhook_url"]).strip(),
            )
            for route in raw["routes"]
        ]

        return cls(
            discord_token=str(raw["discord_token"]).strip(),
            discord_application_id=int(raw["discord_application_id"]),
            discord_guild_id=int(raw["discord_guild_id"]),
            mesh_dm_channel_id=int(raw["mesh_dm_channel_id"]) if raw.get("mesh_dm_channel_id") else None,
            mesh_dm_user_id=int(raw["mesh_dm_user_id"]) if raw.get("mesh_dm_user_id") else None,
            meshcore_avatar_url=str(raw["meshcore_avatar_url"]).strip(),
            serial_port=str(raw["serial_port"]).strip(),
            baud_rate=int(raw.get("baud_rate", 115200)),
            debug=bool(raw.get("debug", False)),
            log_level=str(raw.get("log_level", "INFO")).upper(),
            log_mode=str(raw.get("log_mode", "DEBUG")).upper(),
            log_file=str(raw.get("log_file", "meshbridge.log")).strip(),
            max_message_history=int(raw.get("max_message_history", 100)),
            max_unhandled_events=int(raw.get("max_unhandled_events", 100)),
            neighbor_cache_file=str(raw.get("neighbor_cache_file", "neighbors.json")).strip(),
            neighbor_cache_limit=int(raw.get("neighbor_cache_limit", 5)),
            rate_limit_window_seconds=int(raw.get("rate_limit_window_seconds", 10)),
            rate_limit_max_messages=int(raw.get("rate_limit_max_messages", 5)),
            mesh_chunk_size=int(raw.get("mesh_chunk_size", 180)),
            mesh_chunk_delay_seconds=float(raw.get("mesh_chunk_delay_seconds", 0.5)),
            webhook_timeout_seconds=float(raw.get("webhook_timeout_seconds", 10)),
            reconnect_initial_delay_seconds=float(raw.get("reconnect_initial_delay_seconds", 2)),
            reconnect_max_delay_seconds=float(raw.get("reconnect_max_delay_seconds", 30)),
            auto_probe_on_advert=bool(raw.get("auto_probe_on_advert", True)),
            auto_probe_min_interval_seconds=int(raw.get("auto_probe_min_interval_seconds", 300)),
            routes=routes,
        )
