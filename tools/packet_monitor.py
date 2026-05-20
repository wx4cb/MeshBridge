#!/usr/bin/env python3
"""Small read-only MeshCore companion packet monitor."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from meshbridge.config import AppConfig
from meshbridge.mesh_adapter import MeshAdapter


WATCH_EVENTS = {
    "ADVERTISEMENT",
    "CHANNEL_INFO",
    "CHANNEL_MSG_RECV",
    "CONTACT_MSG_RECV",
    "ERROR",
    "PATH_RESPONSE",
    "PATH_UPDATE",
    "RAW_DATA",
    "RX_LOG_DATA",
    "TRACE_DATA",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Listen to companion MeshCore events without starting Discord."
    )
    parser.add_argument("--config", default="config.hjson", help="Path to MeshBridge config.")
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Seconds to capture. Default 0 runs until Ctrl-C.",
    )
    parser.add_argument(
        "--events",
        default=",".join(sorted(WATCH_EVENTS)),
        help="Comma-separated event names to print.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Print one JSON object per event instead of compact text.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Include the full event payload. By default only high-signal fields are shown.",
    )
    parser.add_argument(
        "--channel-scan",
        action="store_true",
        help="Fetch channel slots 0..15 at startup when supported.",
    )
    return parser


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "type",
        "payload_typename",
        "route_typename",
        "channel_idx",
        "chan_hash",
        "chan_name",
        "message",
        "text",
        "msg_hash",
        "txt_hash",
        "pkt_hash",
        "sender_timestamp",
        "recv_time",
        "snr",
        "SNR",
        "rssi",
        "RSSI",
        "path",
        "path_len",
        "path_hash_size",
        "adv_name",
        "adv_key",
        "key_prefix",
        "error",
    ]
    return {key: payload[key] for key in keys if key in payload}


def text_line(event_name: str, payload: dict[str, Any]) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    typename = payload.get("payload_typename") or payload.get("type") or "-"
    chan = payload.get("chan_hash") or payload.get("channel_idx") or "-"
    name = payload.get("chan_name") or "-"
    pkt_hash = payload.get("pkt_hash") or payload.get("msg_hash") or payload.get("txt_hash") or "-"
    snr = payload.get("snr", payload.get("SNR", "-"))
    rssi = payload.get("rssi", payload.get("RSSI", "-"))
    path = payload.get("path") or "-"
    text = payload.get("message") or payload.get("text") or payload.get("adv_name") or ""
    if isinstance(text, str) and len(text) > 120:
        text = text[:117] + "..."
    return (
        f"{timestamp} {event_name:<16} type={typename} chan={chan} name={name} "
        f"pkt={pkt_hash} snr={snr} rssi={rssi} path={path} text={text!r}"
    )


async def print_channel_scan(mesh: MeshAdapter) -> None:
    print("channel scan:")
    for channel_idx in range(16):
        try:
            info = await mesh.get_channel_info(channel_idx)
        except Exception as exc:
            print(f"  {channel_idx}: error={exc}")
            continue
        if not info:
            continue
        name = info.get("channel_name") or info.get("name") or "-"
        channel_hash = info.get("channel_hash") or info.get("hash") or "-"
        print(f"  {channel_idx}: hash={channel_hash} name={name}")


async def async_main() -> int:
    args = build_arg_parser().parse_args()
    config = AppConfig.load(Path(args.config))
    selected_events = {
        item.strip().upper()
        for item in args.events.split(",")
        if item.strip()
    }

    mesh = MeshAdapter(
        connection_type=config.mesh_connection_type,
        serial_port=config.serial_port,
        baud_rate=config.baud_rate,
        tcp_host=config.tcp_host,
        tcp_port=config.tcp_port,
    )
    stop_event = asyncio.Event()

    async def handle_event(event_name: str, payload: dict[str, Any]) -> None:
        if event_name not in selected_events:
            return
        output_payload = payload if args.raw else compact_payload(payload)
        if args.jsonl:
            print(json.dumps({"event": event_name, "payload": output_payload}, default=str), flush=True)
        else:
            print(text_line(event_name, output_payload), flush=True)

    mesh.set_callback(handle_event)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await mesh.connect()
    try:
        if args.channel_scan:
            await print_channel_scan(mesh)
        if args.duration > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=args.duration)
            except asyncio.TimeoutError:
                pass
        else:
            await stop_event.wait()
    finally:
        await mesh.disconnect()

    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
