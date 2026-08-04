#!/usr/bin/env python3
"""
Processes accounting_entries.csv into processed-accounting-entries.csv:
  - Converts AmtLC to CHF using FX rates logged in fx_rates.csv
    (collected daily by collect_fx_rates.py -- rate on the transaction
    date, or the last available rate before that date if the exact day
    is missing)
  - Stores the FX rate used in AmtCry (1 for CHF)
  - Renames Debit/Credit accounts to their VP equivalents when Ledger == "VP"

FX conversion (AmtCry/AmtCHF) is recomputed fresh on EVERY run for EVERY
row, using whatever fx_rates.csv currently contains -- including rows
whose raw content hasn't changed. This means a backfilled or corrected
historical FX rate automatically fixes past entries on the next run.
(This is a deliberate reversal of the original "no retroactive
recalculation" rule, which only ever applied to FX.)

Everything else (VP account renaming, RawHash bookkeeping) still only
happens when a row is new or its raw content changed, via the RawHash
fingerprint -- that part of the audit-integrity design is unchanged.

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
    (e.g. fixing a typo in accounting_entries.csv) so the row's non-FX derived
    fields (VP account renaming) get recomputed instead of silently carrying
    forward stale values. FX conversion is independent of this -- see module
    docstring."""
    parts = "|".join(str(v) for v in raw_row.values())
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


PROCESSED_FIELD_ORDER = [
    "Timestamp", "Date", "Currency", "AmtLC", "AmtCry", "AmtCHF",
    "DebitAccount", "CreditAccount", "Comment", "Party", "Location",
    "Ledger", "Flags", "SubmittedBy", "IP", "EntryID",
    "ProcessingDateTime", "RawHash",
]


def process(input_path, fx_source, output_path):
    fx_rates = load_fx_rates(fx_source)

    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    # Load already-processed rows (if the output file exists yet), keyed by
    # EntryID -- a stable ID generated once per row at creation time and never
    # recomputed. Used as the baseline for rows whose raw content is unchanged,
    # so VP-renaming etc. isn't redone needlessly. FX fields are always
    # recomputed fresh below, regardless of this baseline -- see module
    # docstring. Rows whose EntryID has disappeared from the raw file
    # (deleted) are dropped automatically since we only iterate raw_rows.
    existing_by_id = {}
    try:
        with open(output_path, encoding="utf-8") as f:
            existing_reader = csv.DictReader(f, delimiter=";")
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
    fx_updated_count = 0
    unchanged_count = 0

    for raw_row in raw_rows:
        eid = raw_row.get("EntryID")
        current_hash = raw_hash(raw_row)

        if not eid:
            warnings.append(f"Row with Timestamp {raw_row.get('Timestamp')} has no EntryID -- processing as new every run until it gets one.")

        existing = existing_by_id.get(eid) if eid else None
        raw_unchanged = existing is not None and existing.get("RawHash") == current_hash

        # Baseline: previous processed row if raw content is unchanged (keeps
        # its VP-renamed accounts etc. as-is), otherwise start fresh from raw.
        row = dict(existing) if raw_unchanged else dict(raw_row)

        currency = (raw_row.get("Currency") or "").strip()
        amt_lc_raw = (raw_row.get("AmtLC") or "").strip()
        date_raw = (raw_row.get("Date") or "").strip()

        try:
            amt_lc = float(amt_lc_raw) if amt_lc_raw != "" else None
        except ValueError:
            amt_lc = None

        try:
            tx_date = datetime.strptime(date_raw, "%d.%m.%Y").date()
        except ValueError:
            tx_date = None

        old_amt_cry = row.get("AmtCry")
        old_amt_chf = row.get("AmtCHF")

        # FX conversion: always recomputed, for every row, every run.
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

        fx_changed = row.get("AmtCry") != old_amt_cry or row.get("AmtCHF") != old_amt_chf

        if raw_unchanged and not fx_changed:
            # Nothing at all changed -- carry forward untouched.
            output_rows.append(row)
            unchanged_count += 1
            continue

        if not raw_unchanged:
            # New row, or raw content edited -- redo VP renaming from raw.
            row["DebitAccount"] = raw_row.get("DebitAccount", "")
            row["CreditAccount"] = raw_row.get("CreditAccount", "")
            if (raw_row.get("Ledger") or "").strip() == "VP":
                debit = (raw_row.get("DebitAccount") or "").strip()
                credit = (raw_row.get("CreditAccount") or "").strip()
                if debit in VP_RENAME_MAP:
                    row["DebitAccount"] = VP_RENAME_MAP[debit]
                if credit in VP_RENAME_MAP:
                    row["CreditAccount"] = VP_RENAME_MAP[credit]
            row["RawHash"] = current_hash
            reprocessed_count += 1
        else:
            # Raw unchanged, only the FX conversion moved (e.g. a backfilled
            # historical rate) -- RawHash stays the same, since the raw row
            # itself wasn't touched.
            fx_updated_count += 1

        row["ProcessingDateTime"] = now_str
        output_rows.append(row)

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", lineterminator="\n", extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(output_rows)

    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    print(f"{len(output_rows)} total rows, {unchanged_count} unchanged, {fx_updated_count} FX-updated, {reprocessed_count} (re)processed -> {output_path}")


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else "accounting_entries.csv"
    fx_source = sys.argv[2] if len(sys.argv) > 2 else FX_SOURCE_DEFAULT
    output_path = sys.argv[3] if len(sys.argv) > 3 else "processed-accounting-entries.csv"
    process(input_path, fx_source, output_path)
