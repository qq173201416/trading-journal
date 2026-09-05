"""Append non-interpolated bars to data/prices/{symbol}.csv, dedup by date.
Input: JSON file mapping symbol -> list of bar dicts."""
import sys, csv, os, json

with open(sys.argv[1]) as f:
    batch = json.load(f)

for symbol, bars in batch.items():
    path = f"data/prices/{symbol}.csv"
    exists_dates = set()
    if os.path.exists(path):
        with open(path) as f:
            r = csv.DictReader(f)
            for row in r:
                exists_dates.add(row["begins_at"])
    added = 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        for b in bars:
            if b.get("interpolated"):
                continue
            if b["begins_at"] in exists_dates:
                continue
            w.writerow([b["begins_at"], b["open_price"], b["close_price"],
                        b["high_price"], b["low_price"], b["volume"], b["session"]])
            exists_dates.add(b["begins_at"])
            added += 1
    print(f"{symbol}: {added} new rows appended")
