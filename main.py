#!/usr/bin/env python3
"""
main.py
-------
Entry point for the GitHub Action. On every run it:

  1. Fetches all current MVG service messages and keeps only line S3.
  2. Classifies each message into Info / Kleine Warnung / Große Warnung
     based on which stations it mentions (see segments.py).
  3. Compares against state/seen_s3_messages.json to find:
       - newly appeared messages  -> posted to Discord
       - previously-seen messages that are no longer active -> posted
         as "Behoben" (resolved), unless disabled via env var
  4. Writes the updated state back to disk (the workflow commits it).

Required environment variable:
    DISCORD_WEBHOOK_URL   Discord webhook URL to post to

Optional environment variables:
    LINE                  Line label to watch, default "S3"
    STATE_FILE            Path to the state file, default
                           "state/seen_s3_messages.json"
    NOTIFY_RESOLVED        "true"/"false", default "true"
"""

from __future__ import annotations

import os
import sys

from discord_notify import build_embed, send_webhook
from mvg_client import fetch_messages, filter_by_line, message_id, message_text, message_type
from segments import classify
from state import load_state, save_state


def env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        return 1

    line = os.environ.get("LINE", "S3")
    state_file = os.environ.get("STATE_FILE", "state/seen_s3_messages.json")
    notify_resolved = env_bool("NOTIFY_RESOLVED", True)

    try:
        all_messages = fetch_messages()
    except Exception as exc:  # noqa: BLE001 - want a clean, actionable log line
        print(f"Error fetching MVG messages: {exc}", file=sys.stderr)
        return 1

    line_messages = filter_by_line(all_messages, line)

    # id -> classified message info
    current: dict[str, dict] = {}
    for msg in line_messages:
        text = message_text(msg)
        severity, stations = classify(text)
        current[message_id(msg)] = {
            "title": msg.get("title") or msg.get("headline") or "(ohne Titel)",
            "description": msg.get("description") or msg.get("text") or msg.get("details") or "",
            "type": message_type(msg),
            "severity": int(severity),
            "stations": stations,
            "validFrom": msg.get("validFrom") or msg.get("fromTime"),
            "validTo": msg.get("validTo") or msg.get("toTime"),
        }

    previous = load_state(state_file)

    new_ids = [mid for mid in current if mid not in previous]
    resolved_ids = [mid for mid in previous if mid not in current]

    embeds = []

    for mid in new_ids:
        info = current[mid]
        embeds.append(
            build_embed(
                title=info["title"],
                description=info["description"],
                severity=info["severity"],  # type: ignore[arg-type]
                line_label=line,
                msg_type=info["type"],
                matched_stations=info["stations"],
                valid_from=info["validFrom"],
                valid_to=info["validTo"],
            )
        )

    if notify_resolved:
        for mid in resolved_ids:
            info = previous[mid]
            embeds.append(
                build_embed(
                    title=info["title"],
                    description=info.get("description", ""),
                    severity=info["severity"],
                    line_label=line,
                    msg_type=info.get("type", "MELDUNG"),
                    matched_stations=info.get("stations", []),
                    resolved=True,
                )
            )

    try:
        send_webhook(webhook_url, embeds)
    except Exception as exc:  # noqa: BLE001
        print(f"Error sending Discord webhook: {exc}", file=sys.stderr)
        # still persist state below so we don't lose track of what happened,
        # but signal failure to the Action.
        save_state(state_file, current)
        return 1

    save_state(state_file, current)

    print(
        f"Line {line}: {len(current)} active message(s), "
        f"{len(new_ids)} new, {len(resolved_ids)} resolved."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
