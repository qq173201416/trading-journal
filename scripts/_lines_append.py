"""Append compact lines 'SYM,YYYY-MM-DD,open,close,high,low,volume' (non-interpolated bars only)
to data/prices/SYM.csv, dedup by date, keep sorted order."""
import sys
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    s, d, *v = line.split(",")
    d = d + "T00:00:00Z"
    p = f"data/prices/{s}.csv"
    rows = open(p).read().splitlines()
    if any(l.startswith(d) for l in rows): continue
    if rows[-1][:20] > d:
        print("OUT OF ORDER", s, d); continue
    with open(p, "a") as f: f.write(",".join([d] + v + ["reg"]) + "\n")
print("ok")
