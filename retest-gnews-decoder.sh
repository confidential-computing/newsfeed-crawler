#!/bin/bash
# Re-test the Google News link decoder held on the gnews-decoder branch.
# Runs master and the branch over the SAME fixed window, into /tmp, with
# throwaway state — the real .webfeed-state.json and editions are not touched.
#
# Pass criteria (all must hold):
#   1. Google is not rate-limiting this machine (pre-flight)
#   2. Branch decodes >0 links and is not rate-limited mid-run
#   3. Branch report has fewer news.google.com links than master
#   4. Branch keeps every story master found (no regressions)
#   5. Branch recovers >=1 story master dropped (the point of the change)
set -u
cd /home/mike/Projects/CC-news-crawler
START=${1:-2026-09-15}; END=${2:-2026-09-22}
OUT=/tmp/gnews-retest; rm -rf "$OUT"; mkdir -p "$OUT"

code=$(curl -s -o /dev/null -w '%{http_code}' -A "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0" \
  "https://news.google.com/articles/CBMingFBVV95cUxQaThudWF0aGQtc0NyaGlUN05JUXJrMUE0a1IwR3FROE5RVWh")
echo "pre-flight: news.google.com -> HTTP $code"
[ "$code" = 429 ] && { echo "FAIL: still rate-limited; try later"; exit 2; }

git diff --quiet || { echo "working tree dirty; commit or stash first"; exit 3; }
run() { python3 crawler.py --webfeed --start "$START" --end "$END" \
          --webfeed-state "$OUT/$1.state.json" --output "$OUT/$1.md" > "$OUT/$1.log" 2>&1; }

echo "running master..."; git checkout -q master && run master
echo "running gnews-decoder..."; git checkout -q gnews-decoder && run branch
git checkout -q master

python3 - "$OUT" <<'PY'
import re, sys
out = sys.argv[1]
def titles(p):
    return {re.sub(r"\s+[-–|]\s+[^-–|]{1,40}$", "", m.group(1)).strip().lower(): m.group(2)
            for m in re.finditer(r"^\s*- \[([^\]]+)\]\((\S+?)\)", open(p).read(), re.M)}
m, b = titles(f"{out}/master.md"), titles(f"{out}/branch.md")
log = open(f"{out}/branch.log").read()
dec = re.search(r"decoded to publisher URLs: (\d+) ok, (\d+) failed(.*)", log)
ok = int(dec.group(1)) if dec else 0
limited = bool(dec and "rate-limited" in dec.group(3))
gm = sum("news.google.com" in u for u in m.values())
gb = sum("news.google.com" in u for u in b.values())
lost, gained = set(m) - set(b), set(b) - set(m)

print(f"\nmaster: {len(m)} stories, {gm} google links")
print(f"branch: {len(b)} stories, {gb} google links, {ok} decoded"
      + (", RATE-LIMITED mid-run" if limited else ""))
for t in sorted(gained): print("  + recovered:", t[:90])
for t in sorted(lost):   print("  - lost:     ", t[:90])

checks = [("decoded >0, not rate-limited", ok > 0 and not limited),
          ("fewer google links", gb < gm),
          ("no stories lost", not lost),
          ("recovered >=1 story", bool(gained))]
print()
for name, passed in checks: print(f"  {'PASS' if passed else 'FAIL'}  {name}")
allok = all(p for _, p in checks)
print("\nVERDICT:", "MERGE gnews-decoder" if allok else "DO NOT MERGE — see failures")
print(f"(reports in {out}/)")
sys.exit(0 if allok else 1)
PY
