#!/usr/bin/env python3
"""Fetch all tradable US stock symbols from Finnhub and save to CSV."""

import csv
import json
import os
import sys
import urllib.request
import urllib.error


FINNHUB_BASE = "https://finnhub.io/api/v1"
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "..", "us-tickers.csv")


def get_api_key():
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FINNHUB_KEY="):
                        key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        print("Error: FINNHUB_KEY not found. Set it as an env var or in .env")
        sys.exit(1)
    return key


def fetch_symbols(api_key):
    url = f"{FINNHUB_BASE}/stock/symbol?exchange=US&token={api_key}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data


def main():
    api_key = get_api_key()
    print("Fetching all US stock symbols from Finnhub...")
    symbols = fetch_symbols(api_key)

    # Filter to common stocks and ADRs that are actively tradable
    tradable = [
        s for s in symbols
        if s.get("type") in ("Common Stock", "ADR", "ETP", "ETF")
    ]

    # Sort by ticker
    tradable.sort(key=lambda s: s.get("symbol", ""))

    out_path = os.path.abspath(OUTPUT_CSV)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "description", "type", "currency", "mic"])
        for s in tradable:
            writer.writerow([
                s.get("symbol", ""),
                s.get("description", ""),
                s.get("type", ""),
                s.get("currency", ""),
                s.get("mic", ""),
            ])

    print(f"Saved {len(tradable)} tradable US symbols to {out_path}")
    print(f"  (filtered from {len(symbols)} total entries)")

    # Summary by type
    from collections import Counter
    types = Counter(s.get("type") for s in tradable)
    for t, count in types.most_common():
        print(f"  {t}: {count}")


if __name__ == "__main__":
    main()
