"""
mvg_client.py
-------------
Thin client around MVG's public (unofficial, undocumented) JSON API for
service messages/disruptions, the same one used by mvg.de.

See the standalone mvg_s3_alerts.py script for background. This module
mirrors that logic but is import-friendly for the Discord bot.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import requests

MESSAGES_URL = "https://www.mvg.de/api/bgw-pt/v3/messages"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; mvg-s3-discord-bot/1.0; +https://www.mvg.de)"
    ),
    "Accept": "application/json",
}


def fetch_messages(timeout: float = 10.0) -> list[dict[str, Any]]:
    """Fetch all current service messages from the MVG API."""
    resp = requests.get(MESSAGES_URL, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError(f"Unexpected response shape from MVG API: {type(data)}")


def _line_labels(message: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    lines = message.get("lines") or message.get("line") or []
    if isinstance(lines, dict):
        lines = [lines]
    for line in lines:
        if isinstance(line, dict):
            label = line.get("label") or line.get("name") or line.get("line")
            if label:
                labels.append(str(label))
        elif isinstance(line, str):
            labels.append(line)
    return labels


def filter_by_line(
    messages: Iterable[dict[str, Any]], line: str
) -> list[dict[str, Any]]:
    """Keep only messages that reference the given line label (case-insensitive)."""
    line = line.strip().upper()
    return [m for m in messages if line in [l.upper() for l in _line_labels(m)]]


def message_text(message: dict[str, Any]) -> str:
    """Combine all free-text fields of a message for keyword scanning."""
    parts = [
        message.get("title") or message.get("headline") or "",
        message.get("description") or message.get("text") or message.get("details") or "",
    ]
    return " \n ".join(p for p in parts if p)


def is_expired(message: dict[str, Any]) -> bool:
    """
    Whether a message's own validTo timestamp has already passed.

    MVG's API often keeps a message listed for a while after its stated
    end time instead of removing it immediately, which would otherwise
    make our bot treat it as "still active" forever (and never delete
    its Discord message). Filtering these out ourselves makes them look
    "gone" to the rest of the pipeline, which reuses the normal
    resolved -> delete logic.

    A missing/unparseable validTo is treated as "not expired" (i.e. an
    open-ended / until-further-notice message), never as a reason to
    delete something we're unsure about.
    """
    valid_to = message.get("validTo") or message.get("toTime")
    if valid_to in (None, "", 0):
        return False
    try:
        if isinstance(valid_to, (int, float)):
            seconds = valid_to / 1000 if valid_to > 10_000_000_000 else valid_to
            return seconds < time.time()
        if isinstance(valid_to, str):
            dt = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() < time.time()
    except (ValueError, OSError, OverflowError):
        return False
    return False


def message_type(message: dict[str, Any]) -> str:
    return str(message.get("type") or message.get("category") or "MELDUNG").upper()


def message_id(message: dict[str, Any]) -> str:
    """
    Build a stable identifier for a message so repeated runs can tell
    "already notified" apart from "new/changed". Prefers the API's own
    id if present, otherwise falls back to a content hash.
    """
    native_id = message.get("id") or message.get("messageId") or message.get("uuid")
    if native_id:
        return str(native_id)

    fingerprint = json.dumps(
        {
            "title": message.get("title") or message.get("headline"),
            "description": message.get("description") or message.get("text"),
            "validFrom": message.get("validFrom") or message.get("fromTime"),
            "validTo": message.get("validTo") or message.get("toTime"),
            "lines": sorted(_line_labels(message)),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]
