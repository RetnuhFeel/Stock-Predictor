#!/usr/bin/env bash
# Decide whether a response from POST /api/_tasks/run-prediction-log means the job really worked.
# Usage: check-prediction-log-result.sh <response.json>
#
# HTTP 200 only means "the task ran". The run is only useful if it recorded something, or if everything it would have
# recorded was already there (the task is idempotent, and on a market holiday the newest bar is already logged).
# So the job FAILS (red) when nothing was logged and nothing was "already logged", e.g. every symbol skipped because
# the data provider failed or the data was stale. Partial skips are annotated as warnings.
set -euo pipefail
f="${1:?response file}"
command -v jq >/dev/null || { echo "::error::jq is required"; exit 2; }
jq -e 'type == "object" and (.logged | type == "array") and (.skipped | type == "array")' "$f" >/dev/null \
  || { echo "::error title=Prediction log::Unexpected response shape from the task (not JSON, or missing logged/skipped)."; exit 1; }

logged=$(jq '.logged | length' "$f")
already=$(jq '[.skipped[] | select(.reason == "ALREADY_LOGGED")] | length' "$f")
other=$(jq '[.skipped[] | select(.reason != "ALREADY_LOGGED")] | length' "$f")
reasons=$(jq -r '[.skipped[] | select(.reason != "ALREADY_LOGGED") | "\(.symbol)=\(.reason)"] | join(", ")' "$f")
resolved=$(jq '.resolved // 0' "$f"); pending=$(jq '.still_pending // 0' "$f")
echo "logged=$logged already_logged=$already other_skips=$other resolved=$resolved still_pending=$pending"

if [ "$logged" -eq 0 ] && [ "$already" -eq 0 ]; then
  echo "::error title=Prediction log recorded nothing::No prediction was logged and none was already logged. Skipped: ${reasons:-none}"
  exit 1
fi
if [ "$other" -gt 0 ]; then
  echo "::warning title=Prediction log partial::Some symbols were skipped: $reasons"
fi
exit 0
