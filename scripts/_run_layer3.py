"""Layer 3: compute technical features for every universe ticker with >=260 rows in data/prices/,
append new (ticker, date) rows to data/features/features_daily.csv."""
import csv, os, sys
sys.path.insert(0, "scripts")
from technical_engine import compute_features

FEATURES_PATH = "data/features/features_daily.csv"

with open("data/universe.csv") as f:
    tickers = [row["ticker"] for row in csv.DictReader(f)]

with open("data/prices/SPY.csv") as f:
    spy_bars = list(csv.DictReader(f))

with open(FEATURES_PATH) as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    existing_keys = {(row["ticker"], row["date"]) for row in reader}

qualifying = []
for t in tickers:
    path = f"data/prices/{t}.csv"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        n = sum(1 for _ in f) - 1
    if n >= 260:
        qualifying.append(t)

print(f"qualifying tickers: {len(qualifying)} / {len(tickers)} universe (excl. SPY)")

new_rows = []
errors = []
for t in qualifying:
    with open(f"data/prices/{t}.csv") as f:
        bars = list(csv.DictReader(f))
    try:
        row = compute_features(t, bars, spy_bars)
    except Exception as e:
        errors.append((t, str(e)))
        continue
    key = (row["ticker"], row["date"])
    if key in existing_keys:
        continue
    new_rows.append(row)
    existing_keys.add(key)

print(f"new feature rows: {len(new_rows)}")
if errors:
    print(f"errors: {len(errors)}")
    for t, e in errors[:10]:
        print(f"  {t}: {e}")

with open(FEATURES_PATH, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    for row in new_rows:
        w.writerow({k: row.get(k, "") for k in fieldnames})

print("done")
