#!/usr/bin/env sh
set -eu
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
export XAGENT_HOME="$test_root/state"
export XAGENT_PROVIDERS="$(pwd)/tests/fixtures"
xagent="python3 scripts/xagent.py"
$xagent models echo | grep 'MODEL'
job=$($xagent run echo "first message" --cwd . --mode read-only --model echo --effort low)
$xagent status "$job" | grep '"status": "succeeded"'
$xagent logs "$job" | grep 'first message'
test "$(stat -f '%Lp' "$XAGENT_HOME/jobs/$job")" = 700
test "$(stat -f '%Lp' "$XAGENT_HOME/jobs/$job/prompt.txt")" = 600
grep 'first message' "$XAGENT_HOME/jobs/$job/prompt.txt"
next=$($xagent run echo "continued message" --cwd . --mode read-only --resume "$job")
$xagent status "$next" | grep '"provider_session_id": "fake-session"'
