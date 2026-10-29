#!/bin/bash
# Post a Slack message when the weekly webfeed run fails. Started by
# cc-webfeed-alert.service (OnFailure= of cc-webfeed.service).
#
# The incoming-webhook URL is a secret, so it lives outside the repository in
# ~/.config/cc-webfeed/slack-webhook-url (mode 600). SLACK_WEBHOOK_URL in the
# environment overrides it, for testing.
set -u

dir=$(cd "$(dirname "$0")" && pwd)
url_file="${XDG_CONFIG_HOME:-$HOME/.config}/cc-webfeed/slack-webhook-url"
url=${SLACK_WEBHOOK_URL:-$(cat "$url_file" 2>/dev/null)}
if [ -z "$url" ]; then
    echo "webfeed-alert: no webhook URL in $url_file" >&2
    exit 1
fi

tail_lines=$(tail -n 15 "$dir/webfeed-cron.log" 2>/dev/null)
text=":warning: *CC webfeed run failed* on $(hostname) at $(date -u '+%Y-%m-%d %H:%M') UTC. No edition was produced this week.
Last log lines (full log: \`$dir/webfeed-cron.log\`, or \`journalctl --user -u cc-webfeed\`):
\`\`\`
$tail_lines
\`\`\`"

payload=$(TEXT="$text" /usr/bin/python3 -c 'import json, os; print(json.dumps({"text": os.environ["TEXT"]}))')
curl -sS --fail --max-time 30 --retry 3 --retry-delay 10 \
    -H 'Content-Type: application/json' -d "$payload" "$url"
