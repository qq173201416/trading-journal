"""Ingest a JSON bars array into data/prices/{symbol}.csv, filtering interpolated=true, dedup by date, sorted."""
import sys, json, os, csv

symbol = sys.argv[1]
json_path = sys.argv[2]

with open(json_path) as f:
    bars = json.load(f)

path = f"data/prices/{symbol}.csv"
existing = {}
if os.path.exists(path):
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            existing[row["begins_at"]] = row

added = 0
for b in bars:
    if b.get("interpolated"):
        continue
    row = {
        "begins_at": b["begins_at"],
        "open_price": b["open_price"],
        "close_price": b["close_price"],
        "high_price": b["high_price"],
        "low_price": b["low_price"],
        "volume": b["volume"],
        "session": b["session"],
    }
    if row["begins_at"] not in existing:
        added += 1
    existing[row["begins_at"]] = row

rows = sorted(existing.values(), key=lambda r: r["begins_at"])
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["begins_at", "open_price", "close_price", "high_price", "low_price", "volume", "session"])
    w.writeheader()
    for row in rows:
        w.writerow(row)

print(f"{symbol}: {added} new rows, {len(rows)} total rows")
