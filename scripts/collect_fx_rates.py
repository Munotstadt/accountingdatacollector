#!/usr/bin/env python3
"""
Collects daily FX closing rates (EUR/CHF, USD/CHF, GBP/CHF) from Yahoo Finance
and logs them to fx_rates.csv.

One row per (Date, Currency): if the collector runs more than once for the
same trading day, the existing row for that day is overwritten rather than
duplicated. This log is the sole FX source used by process_accounting.py --
there is no external dependency on financialdatacollector-public anymore.

Run from the repo root (writes fx_rates.csv alongside this script),
or pass the output path as a CLI arg.
"""
import csv
import json
import sys
import urllib.request
from datetime import datetime, timezone

TICKERS = {
    "EUR": "EURCHF=X",
    "USD": "USDCHF=X",
    "GBP": "GBPCHF=X",
}

FIELDNAMES = ["Date", "Currency", "Rate", "CollectedAt"]


def fetch_rate(ticker):
    """Returns (trading_date, rate) for the most recent close of `ticker`."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]

    # Walk backwards to find the most recent non-null close.
    for ts, close in zip(reversed(timestamps), reversed(closes)):
        if close is not None:
            trading_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            return trading_date, round(float(close), 4)

    raise ValueError(f"No usable close price found for {ticker}")


def load_existing(path):
    rows = {}
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["Date"], row["Currency"])
                rows[key] = row
    except FileNotFoundError:
        pass
    return rows


def collect(output_path):
    existing = load_existing(output_path)
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    warnings = []

    for currency, ticker in TICKERS.items():
        try:
            trading_date, rate = fetch_rate(ticker)
        except Exception as exc:
            warnings.append(f"Could not fetch {currency} ({ticker}): {exc}")
            continue

        date_str = trading_date.strftime("%d.%m.%Y")
        existing[(date_str, currency)] = {
            "Date": date_str,
            "Currency": currency,
            "Rate": str(rate),
            "CollectedAt": now_str,
        }

    all_rows = sorted(
        existing.values(),
        key=lambda r: (datetime.strptime(r["Date"], "%d.%m.%Y"), r["Currency"]),
    )

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(all_rows)

    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    print(f"{len(all_rows)} total FX rate rows -> {output_path}")

    if warnings and len(warnings) == len(TICKERS):
        # All fetches failed -- surface this as a real failure so the
        # Action run is flagged red instead of silently doing nothing.
        sys.exit(1)


if __name__ == "__main__":
    output_path = sys.argv[1] if len(sys.argv) > 1 else "fx_rates.csv"
    collect(output_path)
