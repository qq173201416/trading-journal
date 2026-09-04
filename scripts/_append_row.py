"""Append a single non-interpolated bar row to data/prices/{symbol}.csv if not already present."""
import sys, csv, os

symbol, begins_at, open_p, close_p, high_p, low_p, volume, session = sys.argv[1:9]
path = f"data/prices/{symbol}.csv"

exists_dates = set()
if os.path.exists(path):
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            exists_dates.add(row["begins_at"])

if begins_at in exists_dates:
    print(f"{symbol}: {begins_at} already present, skip")
else:
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([begins_at, open_p, close_p, high_p, low_p, volume, session])
    print(f"{symbol}: appended {begins_at}")
