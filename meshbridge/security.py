"""Security helpers for plain-text-only message handling."""

from __future__ import annotations

import re

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def normalize_sender_name(name: str | None, fallback: str = "unknown") -> str:
    """Normalize a sender display name."""
    if not name:
        return fallback
    cleaned = " ".join(name.replace("\r", " ").replace("\n", " ").split()).strip()
    return cleaned or fallback


def sanitize_webhook_username(name: str | None, fallback: str = "unknown") -> str:
    """Sanitize a webhook display name.

    The bridge uses only plain text. This helper removes control characters,
    collapses whitespace, strips common problematic substrings, and caps length.
    """
    value = normalize_sender_name(name, fallback=fallback)
    forbidden = ("discord", "clyde", "@everyone", "@here")
    for part in forbidden:
        value = value.replace(part, "")
        value = value.replace(part.title(), "")
        value = value.replace(part.upper(), "")
    value = "".join(ch for ch in value if ch.isprintable())
    value = " ".join(value.split()).strip()
    if not value:
        value = fallback
    return value[:60]


def safe_log_text(text: str, max_len: int = 300) -> str:
    """Create a safe single-line log preview."""
    value = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(value) > max_len:
        return value[:max_len] + "..."
    return value


def detect_url(text: str) -> bool:
    """Return True if the text contains a URL."""
    return bool(URL_RE.search(text))


def contains_mass_mention(text: str) -> bool:
    """Return True if the text contains a mass mention token."""
    lowered = text.lower()
    return "@everyone" in lowered or "@here" in lowered


def format_forwarded_text(sender: str, text: str, key_prefix: str | None = None) -> str:
    """Format a plain-text bridged message."""
    sender = normalize_sender_name(sender)
    if key_prefix:
        sender = f"{sender} [{key_prefix}]"
    body = text.strip()
    return f"{sender}: {body}" if body else sender


def split_for_mesh(text: str, max_len: int) -> list[str]:
    """Split a long outbound message into mesh-safe chunks."""
    compact = " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()
    if not compact:
        return []
    if len(compact) <= max_len:
        return [compact]

    chunks: list[str] = []
    remaining = compact
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        candidate = remaining[:max_len]
        break_at = candidate.rfind(" ")
        if break_at < max_len // 2:
            break_at = max_len
        chunks.append(remaining[:break_at].strip())
        remaining = remaining[break_at:].strip()
    return chunks
