#!/bin/bash
# Weekly webfeed run, started by cc-webfeed.timer. Exits non-zero, which makes
# systemd start cc-webfeed-alert.service, when the crawler fails or when it
# exits cleanly without writing a new edition (empty window, refused re-run).
# Extra arguments are passed to the crawler, e.g. for testing.
set -u

dir=$(cd "$(dirname "$0")" && pwd)
state="$dir/.webfeed-state.json"
log="$dir/webfeed-cron.log"

# After a missed run, Persistent=true starts us at boot, possibly before the
# network is up. Give it two minutes rather than failing straight away.
for _ in $(seq 24); do
    getent hosts news.google.com >/dev/null && break
    sleep 5
done

before=$(stat -c %Y "$state" 2>/dev/null || echo 0)
echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') UTC webfeed run ===" >> "$log"
/usr/bin/python3 "$dir/crawler.py" --webfeed --webfeed-exclude-uk "$@" 2>&1 | tee -a "$log"
status=${PIPESTATUS[0]}

if [ "$status" -ne 0 ]; then
    echo "webfeed-run: crawler exited with status $status" | tee -a "$log" >&2
    exit "$status"
fi
after=$(stat -c %Y "$state" 2>/dev/null || echo 0)
if [ "$after" -eq "$before" ]; then
    echo "webfeed-run: crawler exited cleanly but wrote no new edition" | tee -a "$log" >&2
    exit 1
fi
