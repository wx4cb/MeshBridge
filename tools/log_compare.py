#!/usr/bin/env python3
"""Compare pyMC repeater packet logs with MeshBridge companion logs."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


REPEATER_TIME_RE = re.compile(r"(?P<ts>20\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})")
REPEATER_PACKET_RE = re.compile(
    r"Processing packet: (?P<size>\d+) bytes, data: (?P<data>[0-9a-fA-F]+)(?:\.\.\.)?"
)
REPEATER_PACKET_TYPE_RE = re.compile(r"Packet type: (?P<type>[0-9a-fA-F]{2})")
REPEATER_DUP_RE = re.compile(r"Duplicate packet ignored \(hash: (?P<hash>[0-9a-fA-F]+)\)")
BRIDGE_TIME_RE = re.compile(r"^(?P<ts>20\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})")
BRIDGE_PAYLOAD_RE = re.compile(r"RX_LOG_DATA raw payload: (?P<payload>\{.*\})$")
BRIDGE_CHANNEL_RE = re.compile(r"CHANNEL_MSG_RECV raw payload: (?P<payload>\{.*\})$")


@dataclass(slots=True)
class Sighting:
    source: str
    seen_at: datetime
    event: str
    packet_type: str | None = None
    chan_hash: str | None = None
    packet_key: str | None = None
    decoded: bool = False
    duplicate: bool = False
    text: str | None = None
    path: str | None = None
    raw_prefix: str | None = None


def parse_time(match: re.Match[str]) -> datetime:
    return datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S,%f")


def parse_group_text_hex(raw_hex: str) -> dict[str, Any]:
    """Parse enough MeshCore GRP_TXT framing to identify channel/path/cipher key."""
    if len(raw_hex) < 6:
        return {}
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError:
        return {}
    if not data:
        return {}

    header = data[0]
    payload_type = header & 0x0F
    if payload_type != 5 or len(data) < 3:
        return {"packet_type": f"0x{payload_type:02x}"}

    path_descriptor = data[1]
    path_len = path_descriptor & 0x0F
    path_hash_size = 2 if path_descriptor & 0x40 else 1
    path_byte_len = path_len * path_hash_size
    chan_offset = 2 + path_byte_len
    if len(data) <= chan_offset + 2:
        return {"packet_type": "GRP_TXT"}

    chan_hash = f"{data[chan_offset]:02x}"
    cipher_mac = data[chan_offset + 1:chan_offset + 3].hex()
    packet_key = f"{chan_hash}:{cipher_mac}"
    return {
        "packet_type": "GRP_TXT",
        "chan_hash": chan_hash,
        "cipher_mac": cipher_mac,
        "packet_key": packet_key,
        "path": data[2:chan_offset].hex(),
        "path_len": path_len,
        "path_hash_size": path_hash_size,
    }


def parse_repeater_log(path: Path) -> list[Sighting]:
    sightings: list[Sighting] = []
    pending: tuple[datetime, str, int, str | None] | None = None

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        time_match = REPEATER_TIME_RE.search(line)
        if not time_match:
            continue
        seen_at = parse_time(time_match)

        packet_match = REPEATER_PACKET_RE.search(line)
        if packet_match:
            pending = (seen_at, packet_match.group("data").lower(), int(packet_match.group("size")), None)
            continue

        packet_type_match = REPEATER_PACKET_TYPE_RE.search(line)
        if packet_type_match and pending:
            pending = (pending[0], pending[1], pending[2], packet_type_match.group("type").lower())
            continue

        dup_match = REPEATER_DUP_RE.search(line)
        if dup_match and pending:
            parsed = parse_group_text_hex(pending[1])
            if pending[3] == "05" and parsed.get("packet_type") == "GRP_TXT":
                sightings.append(
                    Sighting(
                        source="repeater",
                        seen_at=seen_at,
                        event="DUPLICATE",
                        packet_type="GRP_TXT",
                        chan_hash=parsed.get("chan_hash"),
                        packet_key=parsed.get("packet_key") or dup_match.group("hash").lower(),
                        duplicate=True,
                        path=parsed.get("path"),
                        raw_prefix=pending[1],
                    )
                )
            pending = None
            continue

        if "RX GRP_TXT" in line and pending:
            parsed = parse_group_text_hex(pending[1])
            sightings.append(
                Sighting(
                    source="repeater",
                    seen_at=seen_at,
                    event="RX",
                    packet_type="GRP_TXT",
                    chan_hash=parsed.get("chan_hash"),
                    packet_key=parsed.get("packet_key") or pending[1],
                    path=parsed.get("path"),
                    raw_prefix=pending[1],
                )
            )
            pending = None

    return sightings


def literal_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_bridge_log(path: Path) -> list[Sighting]:
    sightings: list[Sighting] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        time_match = BRIDGE_TIME_RE.search(line)
        if not time_match:
            continue
        seen_at = parse_time(time_match)

        payload_match = BRIDGE_PAYLOAD_RE.search(line)
        if payload_match:
            payload = literal_payload(payload_match.group("payload"))
            if not payload:
                continue
            packet_type = str(payload.get("payload_typename") or "")
            if packet_type != "GRP_TXT":
                continue
            chan_hash = str(payload.get("chan_hash") or "").lower() or None
            cipher_mac = str(payload.get("cipher_mac") or "").lower() or None
            packet_key = f"{chan_hash}:{cipher_mac}" if chan_hash and cipher_mac else None
            sightings.append(
                Sighting(
                    source="bridge",
                    seen_at=seen_at,
                    event="RX_LOG_DATA",
                    packet_type="GRP_TXT",
                    chan_hash=chan_hash,
                    packet_key=packet_key or str(payload.get("pkt_hash") or ""),
                    decoded=bool(payload.get("message")),
                    text=payload.get("message"),
                    path=str(payload.get("path") or ""),
                    raw_prefix=str(payload.get("payload") or payload.get("raw_hex") or "")[:32],
                )
            )
            continue

        channel_match = BRIDGE_CHANNEL_RE.search(line)
        if channel_match:
            payload = literal_payload(channel_match.group("payload"))
            if not payload:
                continue
            txt_hash = payload.get("txt_hash")
            sightings.append(
                Sighting(
                    source="bridge",
                    seen_at=seen_at,
                    event="CHANNEL_MSG_RECV",
                    packet_type="GRP_TXT",
                    packet_key=str(txt_hash) if txt_hash is not None else None,
                    decoded=True,
                    text=payload.get("text"),
                    path=str(payload.get("path") or ""),
                )
            )

    return sightings


def in_window(items: Iterable[Sighting], start: datetime | None, end: datetime | None) -> list[Sighting]:
    return [
        item for item in items
        if (start is None or item.seen_at >= start)
        and (end is None or item.seen_at <= end)
    ]


def summarize(label: str, sightings: list[Sighting]) -> None:
    by_hash = Counter(item.chan_hash or "unknown" for item in sightings if item.packet_type == "GRP_TXT")
    unique_keys = {item.packet_key for item in sightings if item.packet_key}
    unique_suffix = f", unique_keys={len(unique_keys)}" if unique_keys else ""
    print(f"{label}: {len(sightings)} sightings{unique_suffix}")
    if by_hash:
        print("  by channel hash: " + ", ".join(f"{key}={count}" for key, count in sorted(by_hash.items())))
    decoded = sum(1 for item in sightings if item.decoded)
    duplicates = sum(1 for item in sightings if item.duplicate)
    if decoded or duplicates:
        print(f"  decoded={decoded} duplicates={duplicates}")


def find_key_matches(
    repeater: list[Sighting],
    bridge: list[Sighting],
    tolerance_seconds: int,
) -> tuple[list[tuple[str, Sighting, Sighting]], list[Sighting]]:
    bridge_by_key: dict[str, list[Sighting]] = {}
    for item in bridge:
        if not item.packet_key:
            continue
        bridge_by_key.setdefault(item.packet_key, []).append(item)

    repeater_by_key: dict[str, list[Sighting]] = {}
    for item in repeater:
        if item.packet_key:
            repeater_by_key.setdefault(item.packet_key, []).append(item)

    matched: list[tuple[str, Sighting, Sighting]] = []
    missing: list[Sighting] = []
    tolerance = timedelta(seconds=tolerance_seconds)
    for packet_key, repeated_items in repeater_by_key.items():
        first_repeater = repeated_items[0]
        candidates = bridge_by_key.get(packet_key, [])
        best = None
        for candidate in candidates:
            if abs(candidate.seen_at - first_repeater.seen_at) <= tolerance:
                best = candidate
                break
        if best is None:
            missing.append(first_repeater)
        else:
            matched.append((packet_key, first_repeater, best))
    return matched, missing


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare repeater and MeshBridge packet logs.")
    parser.add_argument("--repeater-log", default="~/tmp.log", help="pyMC repeater log path.")
    parser.add_argument("--bridge-log", default="meshbridge.log", help="MeshBridge log path.")
    parser.add_argument("--start", help="Start time, e.g. '2026-05-17 14:30:00'.")
    parser.add_argument("--end", help="End time, e.g. '2026-05-17 15:15:30'.")
    parser.add_argument("--tolerance", type=int, default=8, help="Match window in seconds.")
    parser.add_argument("--show-missing", type=int, default=25, help="Number of missing repeater sightings to print.")
    return parser


def parse_cli_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def main() -> int:
    args = build_arg_parser().parse_args()
    repeater_path = Path(args.repeater_log).expanduser()
    bridge_path = Path(args.bridge_log).expanduser()
    start = parse_cli_time(args.start)
    end = parse_cli_time(args.end)

    repeater = in_window(parse_repeater_log(repeater_path), start, end)
    bridge = in_window(parse_bridge_log(bridge_path), start, end)
    bridge_rx = [item for item in bridge if item.event == "RX_LOG_DATA"]

    summarize("repeater", repeater)
    summarize("bridge RX_LOG_DATA", bridge_rx)
    summarize("bridge decoded/channel events", [item for item in bridge if item.event == "CHANNEL_MSG_RECV"])

    matched, missing = find_key_matches(repeater, bridge_rx, args.tolerance)
    print(f"matched unique repeater->bridge packets by channel hash+cipher MAC: {len(matched)}")
    print(f"missing unique repeater packets by that key: {len(missing)}")

    if missing and args.show_missing:
        print("missing unique repeater packets:")
        for item in missing[: args.show_missing]:
            duplicate = " duplicate=yes" if item.duplicate else ""
            print(
                f"  {item.seen_at} hash={item.chan_hash} key={item.packet_key} "
                f"path={item.path or '-'} raw={item.raw_prefix or '-'}{duplicate}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
