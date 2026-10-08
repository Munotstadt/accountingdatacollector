# AccountingDataCollector

Persönliches Buchhaltungssystem (Double-Entry, CSV-basiert), Teil der Munotstadt-Suite. Erfassung über ein mobiles Formular, automatische Verarbeitung und Fremdwährungsumrechnung via GitHub Actions.

## Datenfluss

```
index.html  →  accounting_entries.csv  →  process_accounting.py  →  processed-accounting-entries.csv
                        ↑
              fx_rates.csv  ←  collect_fx_rates.py (täglich, Yahoo Finance)
```

## Dateien

| Datei | Zweck |
|---|---|
| `index.html` | Erfassungsformular (mobil), Login-Screen vorgeschaltet, Vorlagen, committet Einträge direkt via GitHub Contents API |
| `editor.html` | Rohdaten-Editor für `accounting_entries.csv` |
| `spending.html` | Auswertungs-Dashboard |
| `assets/style.css` | Gemeinsames Stylesheet aller drei Seiten (Layout wie `seestrasse52b`: Topbar mit Tabs, Cards, Space Grotesk / Inter / IBM Plex Mono, Akzent `#E30613`) |
| `templates.json` | Gespeicherte Vorlagen (wird beim ersten «Als Vorlage speichern» automatisch angelegt) |
| `accounting_entries.csv` | Rohdaten (append-only, Quelle der Wahrheit), Komma-getrennt |
| `fx_rates.csv` | Täglicher FX-Kurs-Log (EUR/CHF, USD/CHF, GBP/CHF), Format `Date,Currency,Rate,CollectedAt`, Komma-getrennt |
| `processed-accounting-entries.csv` | Verarbeitete Daten inkl. CHF-Umrechnung, VP-Kontenumbenennung, **Semikolon**-getrennt |
| `scripts/collect_fx_rates.py` | Holt tägliche Schlusskurse von Yahoo Finance |
| `scripts/process_accounting.py` | Umrechnung + Verarbeitung |

## index.html — Erfassungsformular

- **Login vorgeschaltet**: Beim Öffnen erscheint zuerst ein Login-Screen (GitHub Personal Access Token, Passwort-Feld). Das Formular selbst ist erst danach sichtbar. Token wird nur lokal (`localStorage`) auf dem Gerät gespeichert; einmal eingeloggt bleibt man auf dem Gerät angemeldet. „log out / clear saved token" loggt aus und zeigt den Login-Screen wieder.
- **Feldreihenfolge**: Amount (LC) + Currency zuerst, dann Date.
- **Debit/Credit Account**: Tag-Buttons statt Dropdown (wie Comment/Party/Location). Sortierung nach einem Score aus Häufigkeit + Aktualität der Nutzung im bestehenden Ledger — meistgenutzte/zuletzt genutzte Konten stehen oben. „OTHERS" (Freitext) bleibt immer am Ende.
- **Defaults**: Date = heutiges Datum (bei jedem Laden und nach jedem Absenden neu gesetzt), Credit Account = `CC TCS PG`.
- **Layout**: wie 52b.munot.app (Topbar mit Tabs Buchung / Editor / Spending, Sections als Cards). Editor und Spending nutzen dasselbe Stylesheet.
- **Vorlagen**:
  - Dropdown «Vorlage» oben füllt Währung, Konten, Tags, Ledger und Flags aus. Das Datum bleibt immer heute.
  - Unten im Formular: «Als Vorlage speichern». Der Dialog schlägt Konten-Kombinationen (Debit → Credit) vor, basierend auf der aktuellen Auswahl und der Häufigkeit/Aktualität im Ledger (Kombinationen mit gleicher Party/Comment werden bevorzugt). Konten sind manuell änderbar.
  - **Mit Betrag** (z. B. SBB-Billett mit festem Preis) oder **Ohne Betrag** (z. B. Mittagessen, Betrag wird jeweils eingegeben).
  - Gleicher Name überschreibt die bestehende Vorlage (mit Rückfrage). Löschen über den Button neben dem Dropdown.
  - Speicherort: `templates.json` im Repo, damit Vorlagen auf allen Geräten gleich sind. Schreiben mit demselben Token wie die Buchungen (mit Retry bei 409/5xx). Der Processing-Workflow wird dadurch nicht ausgelöst.
- **Retry**: Buchungen werden bei GitHub-Serverfehlern (5xx) und 409 bis zu 4-mal automatisch wiederholt, ohne Doppeleinträge (Prüfung über die EntryID).

## Workflows

- **Collect FX Rates** — primär 05:07 Zürich, Fallback 05:52 Zürich (GitHub `schedule`-Trigger sind nicht pünktlichkeitsgarantiert und können verzögert/übersprungen werden), holt EUR/USD/GBP → CHF von Yahoo Finance
- **Process Accounting Entries** — bei jedem Push auf `accounting_entries.csv` oder `fx_rates.csv`, rechnet um und schreibt `processed-accounting-entries.csv`

## FX-Umrechnungslogik

- Kurs vom Transaktionsdatum, sonst letzter verfügbarer Kurs davor
- CHF-Beträge: Kurs = 1, keine Umrechnung nötig
- **FX-Umrechnung wird bei jedem Lauf für jede Zeile neu berechnet** — auch für bereits verarbeitete, unveränderte Zeilen. Ein nachträglich ergänzter oder korrigierter historischer Kurs in `fx_rates.csv` korrigiert also automatisch alle betroffenen Vergangenheits-Einträge beim nächsten Lauf (bewusste Umkehr der ursprünglichen „keine rückwirkende Neuberechnung"-Regel, gilt nur für FX)
- Kein externer Link mehr zu `financialdatacollector-public` — FX-Daten sind vollständig lokal (`fx_rates.csv`)

## Verarbeitungslogik (`process_accounting.py`)

- Jede Rohzeile hat eine stabile `EntryID` und einen `RawHash` (Fingerprint des Rohinhalts)
- **VP-Kontenumbenennung** und sonstige Rohdaten-Verarbeitung: nur bei neuer oder tatsächlich geänderter Rohzeile (RawHash-Vergleich) — hier gilt weiterhin keine automatische Neuberechnung bei Unverändertem
- Bei `Ledger == "VP"` werden bestimmte PG-Konten automatisch auf ihr VP-Äquivalent umbenannt
- `Device`-Spalte wird nicht in den Output übernommen (bleibt in `accounting_entries.csv` erhalten)

## Konventionen

- Datumsformat überall: `DD.MM.YYYY`, mit Zeit `DD.MM.YYYY HH:MM:SS`
- Alle Zeitstempel in `Europe/Zurich`
- `accounting_entries.csv` und `fx_rates.csv`: Komma-getrennt · `processed-accounting-entries.csv`: Semikolon-getrennt
