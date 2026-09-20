"""
segments.py
-----------
Defines the station order of the Munich S3 line and classifies a
disruption/maintenance message into one of three severity levels based
on which part of the line it affects:

    INFO           - jenseits der Stammstrecke Richtung Maisach,
                     oder jenseits (ausgeschlossen) Taufkirchen Richtung Holzkirchen
    KLEINE_WARNUNG - auf der Stammstrecke (Pasing <-> Ostbahnhof, exkl. Ostbahnhof)
    GROSSE_WARNUNG - zwischen Ostbahnhof und Taufkirchen (jeweils inklusive)

Boundary decisions (adjust here if you weigh them differently):
  - "Stammstrecke" = Pasing ... Rosenheimer Platz (Ostbahnhof selbst zaehlt
    zum Abschnitt Ostbahnhof<->Taufkirchen, nicht zur Stammstrecke).
  - Taufkirchen selbst zaehlt noch zur Grossen Warnung; erst ab Furth
    (Richtung Holzkirchen) gilt es als "jenseits".
  - Wird in einer Meldung kein Haltestellenname erkannt (z.B. "gesamte
    Strecke betroffen"), wird sicherheitshalber GROSSE_WARNUNG angenommen.
"""

from __future__ import annotations

from enum import IntEnum


class Severity(IntEnum):
    INFO = 1
    KLEINE_WARNUNG = 2
    GROSSE_WARNUNG = 3


SEVERITY_LABELS = {
    Severity.INFO: "Info",
    Severity.KLEINE_WARNUNG: "Kleine Warnung",
    Severity.GROSSE_WARNUNG: "Große Warnung",
}

SEVERITY_EMOJI = {
    Severity.INFO: "ℹ️",
    Severity.KLEINE_WARNUNG: "⚠️",
    Severity.GROSSE_WARNUNG: "🚨",
}

# Discord embed colors (decimal)
SEVERITY_COLOR = {
    Severity.INFO: 0x3498DB,          # blue
    Severity.KLEINE_WARNUNG: 0xF1C40F,  # yellow/orange
    Severity.GROSSE_WARNUNG: 0xE74C3C,  # red
}

# Ordered station list Mammendorf -> Holzkirchen, with match-aliases.
# canonical name -> list of alternative spellings that might show up in
# MVG's free-text titles/descriptions.
_WEST_INFO = {
    "Mammendorf": [],
    "Malching": [],
    "Maisach": [],
    "Gernlinden": [],
    "Esting": [],
    "Olching": [],
    "Gröbenzell": ["Groebenzell"],
    "Lochhausen": ["München-Lochhausen"],
    "Langwied": ["München-Langwied"],
}

_STAMMSTRECKE = {
    "Pasing": ["München-Pasing"],
    "Laim": ["München-Laim"],
    "Hirschgarten": [],
    "Donnersbergerbrücke": ["Donnersberger Brücke", "Donnersbergerbruecke"],
    "Hackerbrücke": ["Hackerbruecke"],
    "München Hbf": ["München Hauptbahnhof", "Hauptbahnhof", "Hbf"],
    "Karlsplatz (Stachus)": ["Karlsplatz", "Stachus"],
    "Marienplatz": [],
    "Isartor": [],
    "Rosenheimer Platz": [],
}

_OST_TAUFKIRCHEN = {
    "Ostbahnhof": ["München Ost", "Munich East"],
    "St.-Martin-Straße": ["St. Martin-Straße", "St.-Martin-Str.", "Martinstraße"],
    "Giesing": ["München-Giesing"],
    "Fasangarten": ["München-Fasangarten"],
    "Fasanenpark": [],
    "Unterhaching": [],
    "Taufkirchen": ["Taufkirchen (Kreis München)"],
}

_EAST_INFO = {
    "Furth": ["Furth (Kr München)"],
    "Deisenhofen": [],
    "Sauerlach": [],
    "Otterfing": [],
    "Holzkirchen": [],
}

# Flattened lookup: alias/name (lowercase) -> (canonical name, Severity)
_STATION_LOOKUP: dict[str, tuple[str, Severity]] = {}
for group, severity in (
    (_WEST_INFO, Severity.INFO),
    (_STAMMSTRECKE, Severity.KLEINE_WARNUNG),
    (_OST_TAUFKIRCHEN, Severity.GROSSE_WARNUNG),
    (_EAST_INFO, Severity.INFO),
):
    for canonical, aliases in group.items():
        for name in [canonical, *aliases]:
            _STATION_LOOKUP[name.lower()] = (canonical, severity)

# Sort aliases longest-first so "Karlsplatz (Stachus)" is tried before the
# shorter "Karlsplatz" substring, avoiding partial-match ambiguity.
_ALL_ALIASES_SORTED = sorted(_STATION_LOOKUP.keys(), key=len, reverse=True)


def find_stations(text: str) -> list[str]:
    """Return the (deduplicated, canonical) station names recognized in the text."""
    if not text:
        return []
    haystack = text.lower()
    found: list[str] = []
    for alias in _ALL_ALIASES_SORTED:
        if alias in haystack:
            canonical, _ = _STATION_LOOKUP[alias]
            if canonical not in found:
                found.append(canonical)
    return found


def classify(text: str) -> tuple[Severity, list[str]]:
    """
    Classify a message's free text into a Severity.

    Returns (severity, matched_station_names). If no known station is
    found, defaults to GROSSE_WARNUNG (safe default: assume the whole
    line / an unclear-but-possibly-central section is affected).
    """
    matches = find_stations(text)
    if not matches:
        return Severity.GROSSE_WARNUNG, []

    severities = {_STATION_LOOKUP[m.lower()][1] for m in matches}
    return max(severities), matches
