#!/usr/bin/env python3
"""
Processes accounting_entries.csv into processed-accounting-entries.csv:
  - Converts AmtLC to CHF using FX rates logged in fx_rates.csv
    (collected daily at 06:00 Europe/Zurich from Yahoo Finance by
    collect_fx_rates.py -- rate on the transaction date, or the last
    available rate before that date if the exact day is missing)
  - Stores the FX rate used in AmtCry (1 for CHF)
  - Renames Debit/Credit accounts to their VP equivalents when Ledger == "VP"

Run from the repo root (expects accounting_entries.csv and fx_rates.csv
alongside this script, or pass paths as CLI args: input, fx_source, output).
"""
import csv
import hashlib
import sys
from datetime import datetime

FX_SOURCE_DEFAULT = "fx_rates.csv"
FX_CURRENCIES = {"USD", "EUR", "GBP"}

# Ledger == "VP" account renaming (PG -> VP equivalents)
VP_RENAME_MAP = {
    "Restaurants PG": "Restaurants VP",
    "Life PG": "Life VP",
    "CC TCS PG": "CC TCS VP",
    "SQ WS EUR PG (#315)": "SQ WS EUR VP",
    "SQ WS CHF PG (#315)": "SQ WS CHF VP",
    "Groceries PG": "Groceries VP",
    "Sport & Hobbies & Leisure PG": "Sport & Hobbies & Leisure VP",
    "Revolut PG": "Revolut VP",
    "RB PK Plus PG": "RB PK Plus VP",
}


def load_fx_rates(path):
    """Returns {currency: [(date, rate), ...]} sorted ascending by date,
    read from the local fx_rates.csv log (Date, Currency, Rate, CollectedAt)."""
    rates = {cur: [] for cur in FX_CURRENCIES}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur = (row.get("Currency") or "").strip()
            if cur not in FX_CURRENCIES:
                continue
            try:
                d = datetime.strptime(row["Date"].strip(), "%d.%m.%Y").date()
                rate = float(row["Rate"])
                rates[cur].append((d, rate))
            except (ValueError, KeyError):
                continue

    for cur in rates:
        rates[cur].sort(key=lambda t: t[0])
    return rates


def get_rate(rates_for_currency, target_date):
    """Rate on target_date, else the last available rate before it. None if unavailable."""
    candidates = [(d, r) for d, r in rates_for_currency if d <= target_date]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def raw_hash(raw_row):
    """Fingerprint of a raw row's editable content, used to detect manual edits
    (e.g. fixing a typo in accounting_entries.csv) so the row gets reprocessed
    instead of silently carrying forward stale computed values."""
    parts = "|".join(str(v) for v in raw_row.values())
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


PROCESSED_FIELD_ORDER = [
    "Timestamp", "Date", "Currency", "AmtLC", "AmtCry", "AmtCHF",
    "DebitAccount", "CreditAccount", "Comment", "Party", "Location",
    "Ledger", "Flags", "SubmittedBy", "Device", "IP", "EntryID",
    "ProcessingDateTime", "RawHash",
]


def process(input_path, fx_source, output_path):
    fx_rates = load_fx_rates(fx_source)

    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    # Load already-processed rows (if the output file exists yet), keyed by
    # EntryID -- a stable ID generated once per row at creation time and never
    # recomputed. Matching is content-aware: if a raw row's fingerprint
    # (raw_hash) no longer matches what was stored at last processing time,
    # the row has been manually edited (e.g. fixing a typo) and gets
    # reprocessed. Rows whose EntryID has disappeared from the raw file
    # (deleted) are dropped automatically since we only iterate raw_rows.
    #
    # Note: this means a row is NOT automatically reprocessed just because a
    # newer/better FX rate has since appeared in fx_rates.csv for that day --
    # only edits to the raw row itself trigger recomputation.
    existing_by_id = {}
    try:
        with open(output_path, encoding="utf-8") as f:
            existing_reader = csv.DictReader(f)
            for row in existing_reader:
                eid = row.get("EntryID")
                if eid:
                    existing_by_id[eid] = row
    except FileNotFoundError:
        pass

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    fieldnames = PROCESSED_FIELD_ORDER

    warnings = []
    output_rows = []
    reprocessed_count = 0
    carried_count = 0

    for raw_row in raw_rows:
        eid = raw_row.get("EntryID")
        current_hash = raw_hash(raw_row)

        if not eid:
            warnings.append(f"Row with Timestamp {raw_row.get('Timestamp')} has no EntryID -- processing as new every run until it gets one.")
        else:
            existing = existing_by_id.get(eid)
            if existing is not None and existing.get("RawHash") == current_hash:
                # Unchanged since last processing -- carry forward as-is.
                output_rows.append(existing)
                carried_count += 1
                continue

        # New row, or an existing row whose raw content changed (edited) -- (re)process it.
        row = dict(raw_row)
        currency = (row.get("Currency") or "").strip()
        amt_lc_raw = (row.get("AmtLC") or "").strip()
        date_raw = (row.get("Date") or "").strip()

        try:
            amt_lc = float(amt_lc_raw) if amt_lc_raw != "" else None
        except ValueError:
            amt_lc = None

        try:
            tx_date = datetime.strptime(date_raw, "%d.%m.%Y").date()
        except ValueError:
            tx_date = None

        if amt_lc is not None:
            if currency == "CHF":
                row["AmtCry"] = "1"
                row["AmtCHF"] = str(amt_lc)  # no rounding for CHF
            elif currency in FX_CURRENCIES and tx_date is not None:
                rate = get_rate(fx_rates[currency], tx_date)
                if rate is not None:
                    row["AmtCry"] = str(round(rate, 4))
                    row["AmtCHF"] = str(round(amt_lc * rate, 1))
                else:
                    warnings.append(f"No FX rate found for {currency} on/before {tx_date}")
            else:
                warnings.append(f"Unhandled currency '{currency}' — AmtCry/AmtCHF left blank")

        if (row.get("Ledger") or "").strip() == "VP":
            debit = (row.get("DebitAccount") or "").strip()
            credit = (row.get("CreditAccount") or "").strip()
            if debit in VP_RENAME_MAP:
                row["DebitAccount"] = VP_RENAME_MAP[debit]
            if credit in VP_RENAME_MAP:
                row["CreditAccount"] = VP_RENAME_MAP[credit]

        row["ProcessingDateTime"] = now_str
        row["RawHash"] = current_hash
        output_rows.append(row)
        reprocessed_count += 1

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(output_rows)

    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    print(f"{len(output_rows)} total rows, {carried_count} unchanged, {reprocessed_count} (re)processed -> {output_path}")


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else "accounting_entries.csv"
    fx_source = sys.argv[2] if len(sys.argv) > 2 else FX_SOURCE_DEFAULT
    output_path = sys.argv[3] if len(sys.argv) > 3 else "processed-accounting-entries.csv"
    process(input_path, fx_source, output_path)
