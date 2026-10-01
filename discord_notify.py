"""
discord_notify.py
------------------
Formats MVG alerts as Discord embeds and sends/deletes them via webhook.

Each alert is sent as its OWN webhook message (not batched), because we
request Discord's message id back (`?wait=true`) and store it in the
state file. Once a disruption is resolved, we delete that exact message
again instead of posting a separate "resolved" notice — this keeps the
channel showing only currently-active disruptions instead of growing
forever.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from segments import SEVERITY_COLOR, SEVERITY_EMOJI, SEVERITY_LABELS, Severity

BOT_USERNAME = "MVG S3 Alerts"
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def _fmt_timestamp(value: Any) -> str | None:
    """
    Best-effort formatting of a timestamp field (ms epoch or ISO string).

    MVG's API returns epoch seconds/milliseconds in UTC. We explicitly
    convert to Europe/Berlin (rather than relying on the runner's local
    timezone, which on GitHub Actions is UTC and would silently show the
    wrong, unconverted hour).
    """
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(BERLIN_TZ)
            return dt.strftime("%Y-%m-%d %H:%M %Z")
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
) -> dict[str, Any]:
    emoji = SEVERITY_EMOJI[severity]
    label = SEVERITY_LABELS[severity]
    color = SEVERITY_COLOR[severity]

    fields = [
        {"name": "Linie", "value": line_label, "inline": True},
        {"name": "Kategorie", "value": f"{emoji} {label}", "inline": True},
        {"name": "Typ", "value": msg_type.title(), "inline": True},
    ]

    if matched_stations:
        stations_value = ", ".join(sorted(set(matched_stations), key=matched_stations.index))
        fields.append(
            {
                "name": "Erkannte Haltestellen",
                "value": stations_value[:1024],
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

    description = (description or "").strip()
    # Discord's hard per-embed description limit is 4096, and the combined
    # size of title+description+fields+footer must stay under 6000 for the
    # whole message. Since we now send one embed per message, truncating
    # to this leaves comfortable headroom under normal circumstances.
    max_description = 3500
    if len(description) > max_description:
        description = description[:max_description].rstrip() + "\n… (gekürzt, siehe mvg.de)"

    embed: dict[str, Any] = {
        "title": f"{emoji} {title}"[:256],
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Quelle: mvg.de (inoffizielle API)"},
    }

    # Belt-and-braces: actually measure the combined size (rather than
    # just trusting the budget above) and trim the description further
    # if something unexpectedly pushes it over Discord's 6000 limit.
    overage = _embed_size(embed) - 5800  # small safety margin under 6000
    if overage > 0:
        new_len = max(0, len(embed["description"]) - overage - 20)
        embed["description"] = embed["description"][:new_len].rstrip() + "\n… (gekürzt)"

    return embed


def _embed_size(embed: dict[str, Any]) -> int:
    """Total characters Discord counts toward the 6000-per-message limit."""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len(embed.get("footer", {}).get("text", ""))
    total += len(embed.get("author", {}).get("name", ""))
    for field in embed.get("fields", []):
        total += len(field.get("name", "")) + len(field.get("value", ""))
    return total


def send_new_alert(webhook_url: str, embed: dict[str, Any]) -> str | None:
    """
    Send a single alert embed as its own Discord message and return the
    created message's id (so it can be deleted later once the disruption
    is resolved). Returns None if Discord didn't give back an id for some
    reason (the message was still sent either way).
    """
    resp = requests.post(
        webhook_url,
        params={"wait": "true"},
        json={"username": BOT_USERNAME, "embeds": [embed]},
        timeout=10,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord webhook returned {resp.status_code}: {resp.text[:500]}")
    try:
        return resp.json().get("id")
    except ValueError:
        return None


def delete_message(webhook_url: str, message_id: str) -> None:
    """
    Delete a previously sent alert message (called once its disruption is
    resolved). A 404 (already gone, e.g. manually deleted) is treated as
    success, not an error.
    """
    resp = requests.delete(f"{webhook_url}/messages/{message_id}", timeout=10)
    if resp.status_code not in (204, 404):
        raise RuntimeError(f"Discord delete returned {resp.status_code}: {resp.text[:500]}")
