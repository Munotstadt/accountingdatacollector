#!/usr/bin/env python3
"""
Processes accounting_entries.csv into processed-accounting-entries.csv:
  - Converts AmtLC to CHF using FX rates from financialdatacollector-public/all_data.csv
    (first rate of the transaction date, or the last available rate before that date)
  - Stores the FX rate used in AmtCry (1 for CHF)
  - Renames Debit/Credit accounts to their VP equivalents when Ledger == "VP"

Run from the repo root (expects accounting_entries.csv alongside this script,
or pass paths as CLI args: input, fx_source, output).
"""
import csv
import sys
import urllib.request
from datetime import datetime, date

FX_SOURCE_URL = "https://raw.githubusercontent.com/Munotstadt/financialdatacollector-public/main/all_data.csv"
FX_MAINIDS = {
    "USD": "275000",   # USD/CHF
    "EUR": "897789",   # EUR/CHF
}

# Ledger == "VP" account renaming (PG -> VP equivalents)
VP_RENAME_MAP = {
    "Restaurants PG": "Restaurants VP",
    "Life PG": "Life VP",
    "CC TCS PG": "CC TCS VP",
    "SQ WS EUR PG (#315)": "SQ WS EUR VP",
    "SQ WS CHF PG (#315)": "SQ WS CHF VP",
    "Groceries PG": "Groceries VP",
    "Sport & Hobbies & Leisure PG": "Sport & Hobbies & Leisure VP",
}


def load_fx_rates(path_or_url):
    """Returns {currency: [(datetime, rate), ...]} sorted ascending by datetime."""
    rates = {cur: [] for cur in FX_MAINIDS}
    if path_or_url.startswith("http"):
        with urllib.request.urlopen(path_or_url) as resp:
            text = resp.read().decode("utf-8")
        lines = text.splitlines()
        reader = csv.DictReader(lines)
    else:
        f = open(path_or_url, encoding="utf-8")
        reader = csv.DictReader(f)

    for row in reader:
        main_id = (row.get("MainID") or "").strip()
        for cur, mid in FX_MAINIDS.items():
            if main_id == mid:
                try:
                    dt = datetime.strptime(row["ValueDate"].strip(), "%d.%m.%Y %H:%M:%S")
                    rate = float(row["AmountLC"])
                    rates[cur].append((dt, rate))
                except (ValueError, KeyError):
                    continue

    for cur in rates:
        rates[cur].sort(key=lambda t: t[0])
    return rates


def get_rate(rates_for_currency, target_date):
    """First rate on target_date, else the last rate before target_date. None if unavailable."""
    same_day = [(dt, r) for dt, r in rates_for_currency if dt.date() == target_date]
    if same_day:
        same_day.sort(key=lambda t: t[0])
        return same_day[0][1]
    before = [(dt, r) for dt, r in rates_for_currency if dt.date() < target_date]
    if before:
        before.sort(key=lambda t: t[0])
        return before[-1][1]
    return None


def process(input_path, fx_source, output_path):
    fx_rates = load_fx_rates(fx_source)

    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    warnings = []
    for row in rows:
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
            elif currency in FX_MAINIDS and tx_date is not None:
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

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    print(f"Processed {len(rows)} rows -> {output_path}")


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else "accounting_entries.csv"
    fx_source = sys.argv[2] if len(sys.argv) > 2 else FX_SOURCE_URL
    output_path = sys.argv[3] if len(sys.argv) > 3 else "processed-accounting-entries.csv"
    process(input_path, fx_source, output_path)
