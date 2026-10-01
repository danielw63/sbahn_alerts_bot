# MVG S3 Discord Alert Bot

Überwacht die Münchner S-Bahn-Linie S3 über die (inoffizielle) MVG-API
(`https://www.mvg.de/api/bgw-pt/v3/messages`) und postet Störungs-/Wartungsmeldungen
per Discord-Webhook — automatisiert als GitHub Action. Sobald eine Störung
behoben ist, wird ihre ursprüngliche Nachricht wieder **gelöscht**, statt
den Kanal mit einer zusätzlichen "Behoben"-Meldung zu füllen — der Kanal
zeigt so im Idealfall nur die gerade aktiven Störungen.

## Kategorien

Die Einteilung erfolgt anhand der in einer Meldung erwähnten Haltestellen
(Titel + Beschreibung werden nach bekannten S3-Stationsnamen durchsucht,
siehe `segments.py`):

| Kategorie | Bedeutung | Streckenabschnitt |
|---|---|---|
| ℹ️ **Info** | Störung/Ausfall/Wartung jenseits der Stammstrecke | Mammendorf … Langwied (Richtung Maisach) **oder** Furth … Holzkirchen (jenseits, exkl. Taufkirchen) |
| ⚠️ **Kleine Warnung** | Beeinträchtigung auf der Stammstrecke | Pasing … Rosenheimer Platz |
| 🚨 **Große Warnung** | Beeinträchtigung zwischen Ostbahnhof und Taufkirchen | Ostbahnhof … Taufkirchen (jeweils inklusive) |

Betrifft eine Meldung mehrere Abschnitte (z. B. "Marienplatz bis Taufkirchen"),
wird die **höchste** zutreffende Kategorie gewählt (🚨 > ⚠️ > ℹ️). Wird in einer
Meldung keine bekannte Haltestelle erkannt (z. B. "gesamte Linie betroffen"),
wird sicherheitshalber 🚨 **Große Warnung** angenommen.

> Die genaue Grenze der "Stammstrecke" (z. B. ob Ostbahnhof dazu zählt) ist
> Definitionssache — die hier gewählte Aufteilung steht am Anfang von
> `segments.py` und lässt sich dort leicht anpassen.

## Setup

1. **Discord-Webhook anlegen**: Kanaleinstellungen → Integrationen → Webhooks →
   "Neuer Webhook" → URL kopieren.
2. **Repo-Secret setzen**: In diesem GitHub-Repo unter
   *Settings → Secrets and variables → Actions → New repository secret*:
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: die kopierte Webhook-URL
3. **Workflow-Berechtigung prüfen**: *Settings → Actions → General →
   Workflow permissions* auf "Read and write permissions" stellen (nötig,
   damit die Action den aktualisierten Zustand in `state/` zurückcommitten
   kann).
4. Repo pushen — der Workflow läuft danach automatisch alle 10 Minuten
   (`.github/workflows/s3-alerts.yml`), und lässt sich auch manuell über
   "Run workflow" (workflow_dispatch) anstoßen.

## Lokal testen

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python main.py
```

Zustand wird standardmäßig in `state/seen_s3_messages.json` gehalten. Löschen,
um erneut alle aktuell aktiven Meldungen zu posten.

## Konfiguration (Umgebungsvariablen)

| Variable | Default | Zweck |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | *(erforderlich)* | Ziel-Webhook |
| `LINE` | `S3` | Beobachtete Linie |
| `STATE_FILE` | `state/seen_s3_messages.json` | Pfad der Zustandsdatei |
| `DELETE_RESOLVED` | `true` | Bei "false": behobene Meldungen werden nur vergessen statt ihre Discord-Nachricht zu löschen (sie bleibt dauerhaft im Kanal stehen) |

## Hinweise / Einschränkungen

- Die MVG-API ist **nicht offiziell dokumentiert**; Feldnamen können sich
  ändern. Bricht das Parsing, hilft ein Blick in die rohe API-Antwort
  (`curl https://www.mvg.de/api/bgw-pt/v3/messages`).
- Laut MVG-Impressum ist "moderate, private/nicht-kommerzielle Nutzung"
  der API toleriert, Data-Mining/häufiges Abfragen nicht — daher der
  10-Minuten-Takt im Workflow, nicht enger stellen ohne Grund.
- Die Haltestellen-Erkennung basiert auf einfachem Text-Matching im
  Titel/der Beschreibung der Meldung. Formuliert MVG eine Meldung
  untypisch (z. B. nur mit einer km-Angabe statt Stationsnamen), greift
  der Fallback auf 🚨 Große Warnung.
- **Löschen behobener Meldungen**: Jede neue Meldung wird als eigene
  Discord-Nachricht verschickt (nicht gebündelt), damit Discord deren
  Message-ID zurückgibt — die wird in `state/` mitgespeichert. Sobald
  eine Meldung aus der MVG-API verschwindet, wird genau diese Nachricht
  per Webhook-API wieder gelöscht. Schlägt das Löschen fehl (z. B.
  Netzwerkfehler), bleibt der Eintrag im State für einen erneuten
  Versuch beim nächsten Lauf erhalten, statt verloren zu gehen.
