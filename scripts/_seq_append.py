"""Compact multi-day ingest. Line 1: space-separated dates (YYYY-MM-DD).
Each next line: SYM then one 'o,c,h,l,v' group per date (same order). Appends via _lines_append logic."""
import sys, subprocess, tempfile
lines = [l.split() for l in open(sys.argv[1]) if l.strip()]
dates = lines[0]
out = []
for parts in lines[1:]:
    s, groups = parts[0], parts[1:]
    assert len(groups) == len(dates), (s, len(groups))
    for d, g in zip(dates, groups):
        assert len(g.split(",")) == 5, (s, d, g)
        out.append(f"{s},{d},{g}")
tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt")
tmp.write("\n".join(out) + "\n"); tmp.close()
subprocess.run([sys.executable, "scripts/_lines_append.py", tmp.name], check=True)
print(len(lines) - 1, "symbols")
