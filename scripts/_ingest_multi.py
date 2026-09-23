"""Ingest a raw get_equity_historicals multi-symbol response (the {"data":{"results":[...]}} shape)
directly into data/prices/{symbol}.csv, filtering interpolated=true, dedup by date."""
import sys, csv, os, json

with open(sys.argv[1]) as f:
    obj = json.load(f)

for result in obj["data"]["results"]:
    symbol = result["symbol"]
    bars = result["bars"]
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
