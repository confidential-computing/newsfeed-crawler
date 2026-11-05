#!/bin/bash
# Run hourly from cron. Starts the weekly webfeed run (webfeed-run.sh) when no
# edition has been written since the most recent scheduled slot (Thursday
# 13:00 UTC), so a run that was missed (machine off), killed (reboot mid-run,
# as on 2026-11-05) or failed is retried at the next hour, until one succeeds.
# The crawler resumes from the last recorded cutoff, so a late run neither
# drops nor repeats articles.
#
# Environment overrides, for testing: WEBFEED_STATE (state file),
# WEBFEED_RUNNER (command to run instead of webfeed-run.sh), WEBFEED_NOW
# (epoch seconds to treat as "now").
set -u

dir=$(cd "$(dirname "$0")" && pwd)
state=${WEBFEED_STATE:-$dir/.webfeed-state.json}
runner=${WEBFEED_RUNNER:-$dir/webfeed-run.sh}
lock="$dir/.webfeed.lock"

due=$(STATE="$state" NOW="${WEBFEED_NOW:-}" /usr/bin/python3 - <<'PY'
import json, os
from datetime import datetime, timedelta, timezone

now = (datetime.fromtimestamp(int(os.environ["NOW"]), timezone.utc)
       if os.environ["NOW"] else datetime.now(timezone.utc))
# Most recent Thursday 13:00 UTC at or before now.
slot = now.replace(hour=13, minute=0, second=0, microsecond=0)
slot -= timedelta(days=(slot.weekday() - 3) % 7)
if slot > now:
    slot -= timedelta(days=7)
try:
    with open(os.environ["STATE"]) as f:
        last = datetime.strptime(json.load(f)["last_run_at"],
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
except FileNotFoundError:
    last = None   # first ever run: the crawler handles that
except Exception:
    # Damaged state: the crawler would refuse every hour and fill the log.
    # Run only in the scheduled hour, so the refusal is logged once a week.
    print("yes" if now - slot < timedelta(hours=1) else "no")
    raise SystemExit
print("yes" if last is None or last < slot else "no")
PY
)

[ "$due" = "no" ] && exit 0
# -n: if a slow run from an earlier hour is still going, leave it alone.
exec flock -n "$lock" "$runner"
