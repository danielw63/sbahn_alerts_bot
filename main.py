#!/usr/bin/env python3
"""
main.py
-------
Entry point for the GitHub Action. On every run it:

  1. Fetches all current MVG service messages and keeps only line S3.
  2. Classifies each message into Info / Kleine Warnung / Große Warnung
     based on which stations it mentions (see segments.py).
  3. Compares against state/seen_s3_messages.json to find:
       - newly appeared messages -> each sent as its own Discord message,
         whose message id is stored in the state file
       - previously-seen messages that are no longer active (either
         gone from the API entirely, OR still listed but past their own
         validTo) -> their original Discord message gets DELETED again
         (unless disabled via DELETE_RESOLVED=false), so the channel
         only ever shows currently-active disruptions instead of
         growing forever
  4. Writes the updated state back to disk (the workflow commits it).

Required environment variables:
    DISCORD_WEBHOOK_URL   Discord webhook URL to post to
    SUBREDDITS is NOT used here (that's the Reddit bot) -- n/a

Optional environment variables:
    LINE                  Line label to watch, default "S3"
    STATE_FILE            Path to the state file, default
                           "state/seen_s3_messages.json"
    DELETE_RESOLVED       "true"/"false", default "true". If "false",
                           resolved alerts are simply forgotten instead
                           of having their Discord message deleted (it
                           stays in the channel forever).
"""

from __future__ import annotations

import os
import sys

from discord_notify import build_embed, delete_message, send_new_alert
from html_utils import html_to_discord_text
from mvg_client import fetch_messages, filter_by_line, is_expired, message_id, message_type
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
    delete_resolved = env_bool("DELETE_RESOLVED", True)

    try:
        all_messages = fetch_messages()
    except Exception as exc:  # noqa: BLE001 - want a clean, actionable log line
        print(f"Error fetching MVG messages: {exc}", file=sys.stderr)
        return 1

    line_messages = filter_by_line(all_messages, line)

    # MVG often keeps a message listed in the API well past its own
    # validTo. We filter those out ourselves so they're treated exactly
    # like a disappeared/resolved message below (-> their Discord message
    # gets deleted), instead of lingering in the channel until MVG itself
    # gets around to removing them.
    expired_count = sum(1 for m in line_messages if is_expired(m))
    line_messages = [m for m in line_messages if not is_expired(m)]

    # id -> classified message info
    current: dict[str, dict] = {}
    for msg in line_messages:
        raw_description = msg.get("description") or msg.get("text") or msg.get("details") or ""
        clean_description = html_to_discord_text(raw_description)
        title = msg.get("title") or msg.get("headline") or "(ohne Titel)"

        # Classify on title + cleaned description so HTML tags can't
        # accidentally split a station name across a tag boundary.
        severity, stations = classify(f"{title}\n{clean_description}")

        current[message_id(msg)] = {
            "title": title,
            "description": clean_description,
            "type": message_type(msg),
            "severity": int(severity),
            "stations": stations,
            "validFrom": msg.get("validFrom") or msg.get("fromTime"),
            "validTo": msg.get("validTo") or msg.get("toTime"),
        }

    previous = load_state(state_file)

    new_ids = [mid for mid in current if mid not in previous]
    resolved_ids = [mid for mid in previous if mid not in current]

    error_count = 0
    sent_count = 0

    # --- New alerts: send each as its own message, remember the id ---
    for mid in new_ids:
        info = current[mid]
        embed = build_embed(
            title=info["title"],
            description=info["description"],
            severity=info["severity"],  # type: ignore[arg-type]
            line_label=line,
            msg_type=info["type"],
            matched_stations=info["stations"],
            valid_from=info["validFrom"],
            valid_to=info["validTo"],
        )
        try:
            info["message_id"] = send_new_alert(webhook_url, embed)
            sent_count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"Error sending alert '{info['title']}': {exc}", file=sys.stderr)
            error_count += 1
            # Drop it from `current` so it's retried (re-sent) next run
            # instead of being persisted without a trackable message id.
            del current[mid]

    # --- Resolved alerts: delete their original message ---
    carry_over: dict[str, dict] = {}
    deleted_count = 0
    for mid in resolved_ids:
        info = previous[mid]
        msg_id = info.get("message_id")

        if not delete_resolved or not msg_id:
            continue  # just forget it, leave the Discord message as-is

        try:
            delete_message(webhook_url, msg_id)
            deleted_count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"Error deleting resolved alert '{info.get('title', mid)}': {exc}", file=sys.stderr)
            error_count += 1
            # Keep it in the state so we retry the deletion next run
            # instead of losing track of the message id.
            carry_over[mid] = info

    final_state = {**current, **carry_over}
    save_state(state_file, final_state)

    print(
        f"Line {line}: {len(current)} active message(s) "
        f"({expired_count} filtered out as expired), "
        f"{sent_count} new sent, {deleted_count} resolved deleted, "
        f"{error_count} error(s)."
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
