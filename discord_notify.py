"""
discord_notify.py
------------------
Formats and sends Discord embeds via a webhook URL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from segments import SEVERITY_COLOR, SEVERITY_EMOJI, SEVERITY_LABELS, Severity

BOT_USERNAME = "MVG S3 Alerts"


def _fmt_timestamp(value: Any) -> str | None:
    """Best-effort formatting of a timestamp field (ms epoch or ISO string)."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone()
            return dt.strftime("%Y-%m-%d %H:%M")
        if isinstance(value, str):
            return value
    except (ValueError, OSError, OverflowError):
        pass
    return str(value)


def build_embed(
    *,
    title: str,
    description: str,
    severity: Severity,
    line_label: str,
    msg_type: str,
    matched_stations: list[str],
    valid_from: Any = None,
    valid_to: Any = None,
    resolved: bool = False,
) -> dict[str, Any]:
    emoji = "✅" if resolved else SEVERITY_EMOJI[severity]
    label = "Behoben" if resolved else SEVERITY_LABELS[severity]
    color = 0x2ECC71 if resolved else SEVERITY_COLOR[severity]

    fields = [
        {"name": "Linie", "value": line_label, "inline": True},
        {"name": "Kategorie", "value": f"{emoji} {label}", "inline": True},
        {"name": "Typ", "value": msg_type.title(), "inline": True},
    ]

    if matched_stations:
        fields.append(
            {
                "name": "Erkannte Haltestellen",
                "value": ", ".join(sorted(set(matched_stations), key=matched_stations.index)),
                "inline": False,
            }
        )

    vf, vt = _fmt_timestamp(valid_from), _fmt_timestamp(valid_to)
    if vf or vt:
        fields.append(
            {
                "name": "Zeitraum",
                "value": f"{vf or '?'} → {vt or 'bis auf Weiteres'}",
                "inline": False,
            }
        )

    return {
        "title": f"{emoji} {title}"[:256],
        "description": (description or "")[:4000],
        "color": color,
        "fields": fields,
        "footer": {"text": "Quelle: mvg.de (inoffizielle API)"},
    }


def send_webhook(webhook_url: str, embeds: list[dict[str, Any]]) -> None:
    """Send up to 10 embeds per Discord webhook message, batching as needed."""
    if not embeds:
        return
    for i in range(0, len(embeds), 10):
        batch = embeds[i : i + 10]
        resp = requests.post(
            webhook_url,
            json={"username": BOT_USERNAME, "embeds": batch},
            timeout=10,
        )
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Discord webhook returned {resp.status_code}: {resp.text[:500]}"
            )
