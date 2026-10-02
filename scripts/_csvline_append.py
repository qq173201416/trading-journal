"""Append SYM,open,close,high,low,volume lines (single date given as argv[2]) to data/prices/SYM.csv, dedup by date."""
import sys, os
d = sys.argv[2] + "T00:00:00Z"
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    s, *v = line.split(",")
    p = f"data/prices/{s}.csv"
    if any(l.startswith(d) for l in open(p)): print(s, "dup"); continue
    with open(p, "a") as f: f.write(",".join([d] + v + ["reg"]) + "\n")
