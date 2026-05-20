#!/usr/bin/env python3
"""Live side-by-side comparison of pyMC repeater and MeshBridge logs."""

from __future__ import annotations

import argparse
import ast
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from log_compare import (
    BRIDGE_CHANNEL_RE,
    BRIDGE_PAYLOAD_RE,
    BRIDGE_TIME_RE,
    REPEATER_DUP_RE,
    REPEATER_PACKET_RE,
    REPEATER_PACKET_TYPE_RE,
    REPEATER_TIME_RE,
    parse_group_text_hex,
    parse_time,
)


@dataclass(slots=True)
class PacketState:
    key: str
    chan_hash: str | None = None
    first_repeater_at: datetime | None = None
    bridge_rx_at: datetime | None = None
    bridge_decoded_at: datetime | None = None
    repeater_count: int = 0
    duplicate_count: int = 0
    bridge_rx_count: int = 0
    path: str | None = None
    text: str | None = None
    missing_reported: bool = False
    decode_gap_reported: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class RepeaterLineParser:
    """Stateful parser for pyMC repeater packet lines."""

    def __init__(self) -> None:
        self._pending: tuple[datetime, str, int, str | None] | None = None

    def parse(self, line: str) -> dict[str, Any] | None:
        time_match = REPEATER_TIME_RE.search(line)
        if not time_match:
            return None
        seen_at = parse_time(time_match)

        packet_match = REPEATER_PACKET_RE.search(line)
        if packet_match:
            self._pending = (
                seen_at,
                packet_match.group("data").lower(),
                int(packet_match.group("size")),
                None,
            )
            return None

        packet_type_match = REPEATER_PACKET_TYPE_RE.search(line)
        if packet_type_match and self._pending is not None:
            self._pending = (
                self._pending[0],
                self._pending[1],
                self._pending[2],
                packet_type_match.group("type").lower(),
            )
            return None

        duplicate = False
        dup_match = REPEATER_DUP_RE.search(line)
        if dup_match:
            duplicate = True
        elif "RX GRP_TXT" not in line:
            return None

        if self._pending is None:
            return None

        pending_at, raw_prefix, size, packet_type = self._pending
        parsed = parse_group_text_hex(raw_prefix)
        self._pending = None
        if duplicate and packet_type != "05":
            return None
        if parsed.get("packet_type") != "GRP_TXT":
            return None

        return {
            "source": "repeater",
            "seen_at": seen_at,
            "packet_at": pending_at,
            "size": size,
            "duplicate": duplicate,
            "chan_hash": parsed.get("chan_hash"),
            "packet_key": parsed.get("packet_key") or raw_prefix,
            "path": parsed.get("path"),
            "raw_prefix": raw_prefix,
        }


def literal_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_bridge_line(line: str) -> dict[str, Any] | None:
    time_match = BRIDGE_TIME_RE.search(line)
    if not time_match:
        return None
    seen_at = parse_time(time_match)

    payload_match = BRIDGE_PAYLOAD_RE.search(line)
    if payload_match:
        payload = literal_payload(payload_match.group("payload"))
        if not payload or str(payload.get("payload_typename") or "") != "GRP_TXT":
            return None
        chan_hash = str(payload.get("chan_hash") or "").lower() or None
        cipher_mac = str(payload.get("cipher_mac") or "").lower() or None
        packet_key = f"{chan_hash}:{cipher_mac}" if chan_hash and cipher_mac else None
        if not packet_key:
            return None
        return {
            "source": "bridge",
            "event": "RX_LOG_DATA",
            "seen_at": seen_at,
            "chan_hash": chan_hash,
            "packet_key": packet_key,
            "path": str(payload.get("path") or ""),
            "text": payload.get("message"),
            "msg_hash": payload.get("msg_hash"),
            "chan_name": payload.get("chan_name"),
        }

    channel_match = BRIDGE_CHANNEL_RE.search(line)
    if channel_match:
        payload = literal_payload(channel_match.group("payload"))
        if not payload:
            return None
        return {
            "source": "bridge",
            "event": "CHANNEL_MSG_RECV",
            "seen_at": seen_at,
            "txt_hash": payload.get("txt_hash"),
            "channel_idx": payload.get("channel_idx"),
            "path": str(payload.get("path") or ""),
            "text": payload.get("text"),
        }

    return None


def open_tail(path: Path, from_start: bool) -> TextIO:
    handle = path.open("r", encoding="utf-8", errors="replace")
    if not from_start:
        handle.seek(0, 2)
    return handle


def short_text(text: str | None, limit: int = 90) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def print_event(label: str, message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"{now} {label:<15} {message}", flush=True)


def status_for(packet: PacketState) -> str:
    if packet.bridge_decoded_at:
        return "decoded"
    if packet.bridge_rx_at:
        return "bridge-rx"
    return "waiting"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tail pyMC repeater and MeshBridge logs side by side."
    )
    parser.add_argument(
        "--repeater-log",
        default="~/tmp.log",
        help="pyMC repeater log path, currently often ~/tmp.log.",
    )
    parser.add_argument(
        "--bridge-log",
        default="meshbridge.log",
        help="MeshBridge log path.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="Seconds before reporting a repeater packet as missing from bridge RX.",
    )
    parser.add_argument(
        "--decode-timeout",
        type=float,
        default=12.0,
        help="Seconds after bridge RX before reporting no CHANNEL_MSG_RECV decode.",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Read existing log content before following new lines.",
    )
    parser.add_argument(
        "--show-duplicates",
        action="store_true",
        help="Print repeater duplicate sightings too.",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.25,
        help="Polling interval in seconds.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    repeater_path = Path(args.repeater_log).expanduser()
    bridge_path = Path(args.bridge_log).expanduser()

    repeater_parser = RepeaterLineParser()
    packets: dict[str, PacketState] = {}
    msg_hash_to_key: dict[str, str] = {}

    print_event("START", f"repeater={repeater_path} bridge={bridge_path}")
    print_event("START", "columns: event key/hash status details")

    with open_tail(repeater_path, args.from_start) as repeater_file, open_tail(
        bridge_path, args.from_start
    ) as bridge_file:
        while True:
            made_progress = False

            for line in iter(repeater_file.readline, ""):
                made_progress = True
                event = repeater_parser.parse(line)
                if not event:
                    continue

                key = str(event["packet_key"])
                packet = packets.setdefault(key, PacketState(key=key))
                packet.chan_hash = event.get("chan_hash") or packet.chan_hash
                packet.path = event.get("path") or packet.path
                if packet.first_repeater_at is None:
                    packet.first_repeater_at = event["seen_at"]
                packet.repeater_count += 1
                if event.get("duplicate"):
                    packet.duplicate_count += 1

                if event.get("duplicate") and not args.show_duplicates:
                    continue

                print_event(
                    "REPEATER",
                    (
                        f"key={key} hash={packet.chan_hash or '-'} "
                        f"status={status_for(packet)} path={packet.path or '-'}"
                    ),
                )

            for line in iter(bridge_file.readline, ""):
                made_progress = True
                event = parse_bridge_line(line)
                if not event:
                    continue

                if event["event"] == "RX_LOG_DATA":
                    key = str(event["packet_key"])
                    packet = packets.setdefault(key, PacketState(key=key))
                    packet.bridge_rx_at = event["seen_at"]
                    packet.bridge_rx_count += 1
                    packet.chan_hash = event.get("chan_hash") or packet.chan_hash
                    packet.path = event.get("path") or packet.path
                    packet.text = event.get("text") or packet.text
                    if event.get("msg_hash") is not None:
                        msg_hash_to_key[str(event["msg_hash"])] = key
                    matched = "yes" if packet.first_repeater_at else "not-yet"
                    decoded_payload = "yes" if event.get("text") else "no"
                    print_event(
                        "BRIDGE-RX",
                        (
                            f"key={key} hash={packet.chan_hash or '-'} "
                            f"matched_repeater={matched} decoded_payload={decoded_payload} "
                            f"path={packet.path or '-'} text={short_text(packet.text)!r}"
                        ),
                    )
                    continue

                txt_hash = event.get("txt_hash")
                key = msg_hash_to_key.get(str(txt_hash)) if txt_hash is not None else None
                if key is None:
                    key = f"txt_hash:{txt_hash}"
                packet = packets.setdefault(key, PacketState(key=key))
                packet.bridge_decoded_at = event["seen_at"]
                packet.text = event.get("text") or packet.text
                print_event(
                    "BRIDGE-DECODE",
                    (
                        f"key={key} status=decoded channel={event.get('channel_idx')} "
                        f"path={event.get('path') or '-'} text={short_text(packet.text)!r}"
                    ),
                )

            now = datetime.now()
            for packet in list(packets.values()):
                if (
                    packet.first_repeater_at
                    and not packet.bridge_rx_at
                    and not packet.missing_reported
                    and (now - packet.first_repeater_at).total_seconds() >= args.timeout
                ):
                    packet.missing_reported = True
                    print_event(
                        "MISSING",
                        (
                            f"key={packet.key} hash={packet.chan_hash or '-'} "
                            f"no bridge RX after {args.timeout:g}s path={packet.path or '-'}"
                        ),
                    )

                if (
                    packet.bridge_rx_at
                    and not packet.bridge_decoded_at
                    and not packet.text
                    and not packet.decode_gap_reported
                    and (now - packet.bridge_rx_at).total_seconds() >= args.decode_timeout
                ):
                    packet.decode_gap_reported = True
                    print_event(
                        "NO-DECODE",
                        (
                            f"key={packet.key} hash={packet.chan_hash or '-'} "
                            f"no CHANNEL_MSG_RECV after {args.decode_timeout:g}s "
                            f"text_in_rx={'yes' if packet.text else 'no'}"
                        ),
                    )

            if not made_progress:
                time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
