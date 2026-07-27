# AccountingDataCollector

Persönliches Buchhaltungssystem (Double-Entry, CSV-basiert), Teil der Munotstadt-Suite. Erfassung über ein mobiles Formular, automatische Verarbeitung und Fremdwährungsumrechnung via GitHub Actions.

## Datenfluss

```
accounting-entry-form.html  →  accounting_entries.csv  →  process_accounting.py  →  processed-accounting-entries.csv
                                        ↑
                              fx_rates.csv  ←  collect_fx_rates.py (täglich, Yahoo Finance)
```

## Dateien

| Datei | Zweck |
|---|---|
| `accounting-entry-form.html` | Erfassungsformular (mobil), committet Einträge direkt via GitHub Contents API |
| `accounting-entries-editor.html` | Rohdaten-Editor für `accounting_entries.csv` |
| `spending-dashboard.html` | Auswertungs-Dashboard |
| `accounting_entries.csv` | Rohdaten (append-only, Quelle der Wahrheit) |
| `fx_rates.csv` | Täglicher FX-Kurs-Log (EUR/CHF, USD/CHF, GBP/CHF), Format `Date,Currency,Rate,CollectedAt` |
| `processed-accounting-entries.csv` | Verarbeitete Daten inkl. CHF-Umrechnung, VP-Kontenumbenennung |
| `scripts/collect_fx_rates.py` | Holt tägliche Schlusskurse von Yahoo Finance |
| `scripts/process_accounting.py` | Umrechnung + Verarbeitung |

## Workflows

- **Collect FX Rates** — täglich 05:07 Zürich (dual Cron für MEZ/MESZ), holt EUR/USD/GBP → CHF von Yahoo Finance
- **Process Accounting Entries** — bei jedem Push auf `accounting_entries.csv` oder `fx_rates.csv`, rechnet um und schreibt `processed-accounting-entries.csv`

## FX-Umrechnungslogik

- Kurs vom Transaktionsdatum, sonst letzter verfügbarer Kurs davor
- CHF-Beträge: Kurs = 1, keine Umrechnung nötig
- Kein externer Link mehr zu `financialdatacollector-public` — FX-Daten sind vollständig lokal (`fx_rates.csv`)

## Verarbeitungslogik (`process_accounting.py`)

- Jede Rohzeile hat eine stabile `EntryID` und einen `RawHash` (Fingerprint des Rohinhalts)
- Unveränderte Zeilen werden 1:1 übernommen (kein Neuberechnen bei z. B. später ergänztem FX-Kurs)
- Ändert sich eine Rohzeile (z. B. Betrag korrigiert), wird sie automatisch neu verarbeitet
- **Keine rückwirkende Neuberechnung** bei nachträglich verbesserten FX-Kursen — bewusste Design-Entscheidung
- Bei `Ledger == "VP"` werden bestimmte PG-Konten automatisch auf ihr VP-Äquivalent umbenannt

## Konventionen

- Datumsformat überall: `DD.MM.YYYY`, mit Zeit `DD.MM.YYYY HH:MM:SS`
- Alle Zeitstempel in `Europe/Zurich`
