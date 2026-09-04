"""Append one non-interpolated bar row per symbol to data/prices/{symbol}.csv, from a JSON file
mapping symbol -> {begins_at, open_price, close_price, high_price, low_price, volume, session}."""
import sys, csv, os, json

with open(sys.argv[1]) as f:
    batch = json.load(f)

for symbol, bar in batch.items():
    path = f"data/prices/{symbol}.csv"
    exists_dates = set()
    if os.path.exists(path):
        with open(path) as f:
            r = csv.DictReader(f)
            for row in r:
                exists_dates.add(row["begins_at"])
    if bar["begins_at"] in exists_dates:
        print(f"{symbol}: {bar['begins_at']} already present, skip")
        continue
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([bar["begins_at"], bar["open_price"], bar["close_price"],
                    bar["high_price"], bar["low_price"], bar["volume"], bar["session"]])
    print(f"{symbol}: appended {bar['begins_at']}")
