#!/usr/bin/env sh
set -eu
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
export XAGENT_HOME="$test_root/state"
xagent="python3 $(pwd)/scripts/xagent.py"

fail() { echo "FAIL: $1" >&2; exit 1; }
ok() { echo "ok - $1"; }

# --- a plain command runs, is recorded, and its output is captured -----------------
job=$($xagent run --cwd . -- python3 -c 'print("hello from the provider")')
$xagent status "$job" | grep -q '"status": "succeeded"' || fail "job did not succeed"
grep -q 'hello from the provider' "$XAGENT_HOME/jobs/$job/stdout.log" || fail "stdout was not captured"
test "$($xagent path "$job")" = "$(cd "$XAGENT_HOME/jobs/$job" && pwd -P)" || fail "path did not resolve to the job dir"
ok "runs a command, captures stdout, and reports its directory"

# --- the job directory and its contents are private -------------------------------
python3 - "$XAGENT_HOME/jobs/$job" <<'PY' || exit 1
import os, stat, sys
d = sys.argv[1]
assert stat.S_IMODE(os.stat(d).st_mode) == 0o700, "job dir is not 0700"
for name in ("job.json", "stdout.log", "stderr.log"):
    p = os.path.join(d, name)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, f"{name} is not 0600"
PY
ok "job directory and artifacts are private"

# --- the recorded argv is exactly what was passed after `--` ----------------------
python3 - "$XAGENT_HOME/jobs/$job/job.json" <<'PY' || exit 1
import json, sys
argv = json.load(open(sys.argv[1]))["argv"]
assert argv == ["python3", "-c", 'print("hello from the provider")'], argv
PY
ok "argv is recorded verbatim"

# --- stderr is captured separately ------------------------------------------------
job=$($xagent run --cwd . -- python3 -c 'import sys; print("to stderr", file=sys.stderr)') || true
grep -q 'to stderr' "$XAGENT_HOME/jobs/$job/stderr.log" || fail "stderr was not captured"
test ! -s "$XAGENT_HOME/jobs/$job/stdout.log" || fail "stdout should be empty"
ok "stdout and stderr are captured separately"

# --- a non-zero exit is recorded as failed, not hidden ----------------------------
job=$($xagent run --cwd . -- python3 -c 'raise SystemExit(3)') && fail "run should exit non-zero" || true
$xagent status "$job" | grep -q '"status": "failed"' || fail "expected failed status"
$xagent status "$job" | grep -q '"exit_code": 3' || fail "expected exit_code 3"
ok "non-zero exit is recorded"

# --- the prompt file is piped to the command's stdin ------------------------------
printf 'prompt from a file' > "$test_root/prompt.txt"
job=$($xagent run --cwd . --prompt-file "$test_root/prompt.txt" -- python3 -c 'import sys; print(sys.stdin.read())')
grep -q 'prompt from a file' "$XAGENT_HOME/jobs/$job/stdout.log" || fail "prompt file was not piped to stdin"
grep -q 'prompt from a file' "$XAGENT_HOME/jobs/$job/prompt.txt" || fail "prompt was not saved"
ok "--prompt-file is piped to stdin and saved"

# --- `--prompt-file -` reads this process's stdin ---------------------------------
job=$(printf 'prompt from stdin' | $xagent run --cwd . --prompt-file - -- python3 -c 'import sys; print(sys.stdin.read())')
grep -q 'prompt from stdin' "$XAGENT_HOME/jobs/$job/stdout.log" || fail "stdin prompt was not piped through"
ok "--prompt-file - reads stdin"

# --- a session id is recovered from structured output after the fact --------------
job=$($xagent run --cwd . -- python3 -c 'import json; print(json.dumps({"type":"thread.started","thread_id":"thr_abc123"}))')
test "$($xagent session "$job")" = "thr_abc123" || fail "session id was not recovered"
$xagent status "$job" | grep -q '"session_id": "thr_abc123"' || fail "session id not in status"
grep -q '"session_id": "thr_abc123"' "$XAGENT_HOME/jobs/$job/job.json" || fail "session id not recorded in job.json"
ok "session id is recovered from saved output"

# --- session is readable mid-run, when job.json does not have it yet --------------
$xagent run --cwd . --timeout 20 -- python3 -u -c 'import json,time; print(json.dumps({"type":"thread.started","thread_id":"thr_live"})); time.sleep(15)' >"$test_root/live" 2>/dev/null &
python3 -c 'import time; time.sleep(3)'
live=$(cat "$test_root/live")
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('session_id') is None else 1)" \
  "$XAGENT_HOME/jobs/$live/job.json" || fail "precondition: job.json should not hold the id yet"
test "$($xagent session "$live")" = "thr_live" || fail "session should find the id mid-run"
$xagent status "$live" | grep -q '"session_id": "thr_live"' || fail "status should agree mid-run"
$xagent stop "$live"; wait 2>/dev/null || true
ok "session and status find the id mid-run"

# --- lineage is recorded when a job continues another -----------------------------
child=$($xagent run --cwd . --parent "$job" -- python3 -c 'print("resumed")')
grep -q "\"parent_job\": \"$job\"" "$XAGENT_HOME/jobs/$child/job.json" || fail "parent job not recorded"
ok "--parent records lineage"

# --- a command with no structured-output flag warns but still runs ----------------
warning=$($xagent run --cwd . -- python3 -c 'print("plain")' 2>&1 >/dev/null)
echo "$warning" | grep -q 'structured output' || fail "expected a structured-output warning"
job=$($xagent run --cwd . -- python3 -c 'print("plain")' 2>/dev/null)
$xagent status "$job" | grep -q '"status": "succeeded"' || fail "warning should not block the run"
ok "missing structured output warns without refusing"

# --- a timeout terminates the whole process group, not just the direct child ------
marker="xagent-test-grandchild-$$"
job=$($xagent run --cwd . --timeout 1 -- sh -c "python3 -c 'import time; time.sleep(45)' # $marker" ) && fail "timeout should exit non-zero" || true
$xagent status "$job" | grep -q '"status": "timed_out"' || fail "expected timed_out status"
pgrep -f "$marker" >/dev/null && fail "grandchild survived the timeout" || true
ok "timeout kills the whole process group"

# --- SIGTERM to the runner kills the child and still records an outcome -----------
marker="xagent-test-sigterm-$$"
$xagent run --cwd . --timeout 120 -- sh -c "python3 -c 'import time; time.sleep(60)' # $marker" >"$test_root/tjob" 2>/dev/null &
runner=$!
python3 -c 'import time; time.sleep(2)'
tjob=$(cat "$test_root/tjob")
pgrep -f "$marker" >/dev/null || fail "precondition: child should be running"
kill -TERM "$runner"
python3 -c 'import time; time.sleep(2)'
pgrep -f "$marker" >/dev/null && { pkill -f "$marker"; fail "SIGTERM orphaned the child"; } || true
$xagent status "$tjob" | grep -q '"status": "cancelled"' || fail "SIGTERM did not record an outcome"
wait 2>/dev/null || true
ok "SIGTERM kills the child and records an outcome"

# --- a job whose process vanished reports as abandoned, not running ---------------
job=$($xagent run --cwd . -- python3 -c 'print("done")')
python3 - "$XAGENT_HOME/jobs/$job/job.json" <<'PY' || exit 1
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["status"] = "running"; d["process_group"] = 999999   # a pid that cannot exist
json.dump(d, open(p, "w"), indent=2, sort_keys=True)
PY
$xagent status "$job" | grep -q '"status": "abandoned"' || fail "expected abandoned status"
$xagent stop "$job" 2>&1 | grep -q 'abandoned' || fail "stop should record the job as abandoned"
$xagent status "$job" | grep -q '"status": "abandoned"' || fail "stop did not persist abandoned"
ok "a vanished job is reported and recorded as abandoned"

# --- input validation -------------------------------------------------------------
$xagent path ../../etc 2>/dev/null && fail "path traversal should be rejected" || true
$xagent run --cwd . -- 2>/dev/null && fail "an empty provider command should be rejected" || true
$xagent run --cwd /nope/nowhere -- python3 -c 'pass' 2>/dev/null && fail "a bad --cwd should be rejected" || true
$xagent run --cwd . --timeout 0 -- python3 -c 'pass' 2>/dev/null && fail "a zero timeout should be rejected" || true
ok "invalid input is rejected"

# --- flags after `--` reach the provider, not xagent ------------------------------
job=$($xagent run --cwd . -- python3 -c 'import sys; print(sys.argv[1:])' --timeout --cwd --json)
grep -q -- "--timeout" "$XAGENT_HOME/jobs/$job/stdout.log" || fail "provider flags were eaten by xagent"
ok "flags after -- are passed through untouched"

echo
echo "all tests passed"
