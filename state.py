"""
state.py
--------
Very small JSON-file "database" that remembers which messages we've
already posted to Discord, so the GitHub Action doesn't re-announce the
same disruption every 10 minutes. The file is committed back to the repo
by the workflow after each run.
"""

from __future__ import annotations

import json
import os
from typing import Any


def load_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
