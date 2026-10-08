#!/usr/bin/env bash
# Decide whether a response from POST /api/_tasks/run-prediction-log means the job really worked.
# Usage: check-prediction-log-result.sh <response.json>
#
# HTTP 200 only means "the task ran". The run is only a success when, afterwards, the log holds a prediction for every
# allowlisted symbol for the session the run was supposed to record (`expected_batch.base_date`: today's close after
# the US close, otherwise the previous trading day's close), whether it was written now or by an earlier run. Rows
# for an OLDER session do not count: on 2026-10-02 the provider kept serving Thursday's prices, every symbol came back
# "already logged" (for Thursday) and the job went green while Friday was never recorded.
#
# An API deployed before `expected_batch` existed gets the old, weaker check (something logged or already logged)
# plus a warning, so the workflow keeps working while the API is being redeployed.
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

if jq -e '.expected_batch | type == "object"' "$f" >/dev/null; then
  base=$(jq -r '.expected_batch.base_date' "$f")
  present=$(jq -r '.expected_batch.present | join(", ")' "$f")
  missing=$(jq -r '.expected_batch.missing | join(", ")' "$f")
  echo "expected_base=$base present=[${present}] missing=[${missing}]"
  if [ -n "$missing" ]; then
    echo "::error title=Prediction log incomplete for $base::No prediction for the $base close for: $missing. Skipped: ${reasons:-none}. A backup run before the next open retries automatically; a session that cannot be recorded from a fresh close is left as a gap (never back-filled)."
    exit 1
  fi
  if [ "$other" -gt 0 ]; then
    echo "::warning title=Prediction log notes::Batch for $base is complete, but some symbols reported: $reasons"
  fi
  exit 0
fi

echo "::warning title=Prediction log::The API response has no expected_batch (API not redeployed yet?); using the older, weaker check."
if [ "$logged" -eq 0 ] && [ "$already" -eq 0 ]; then
  echo "::error title=Prediction log recorded nothing::No prediction was logged and none was already logged. Skipped: ${reasons:-none}"
  exit 1
fi
if [ "$other" -gt 0 ]; then
  echo "::warning title=Prediction log partial::Some symbols were skipped: $reasons"
fi
exit 0
