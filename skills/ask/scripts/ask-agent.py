#!/usr/bin/env python3
"""Record and bound a coding-agent CLI invocation.

The caller builds the provider command, with help from the ask skill; this runner
executes it exactly as written, captures both streams to files, enforces a timeout, and
keeps a durable record of what ran. Knowledge about which flags a provider takes lives
in the skill, not here.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

def store_root():
    """The job store. A relative ASK_AGENT_HOME would put it wherever a command ran from,
    silently hiding every job started in another directory."""
    raw = os.environ.get("ASK_AGENT_HOME")
    if raw is None: return Path("~/.ask-agent").expanduser()
    path = Path(raw).expanduser()
    if not path.is_absolute(): raise SystemExit(f"ASK_AGENT_HOME must be an absolute path: {raw}")
    return path

ROOT = store_root()
JOB_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
SESSION_KEYS = ("session_id", "thread_id", "conversation_id")
TERMINAL = ("succeeded", "failed", "timed_out", "cancelled", "abandoned")
# 124 is what timeout(1) reports, and 130 is a SIGINT exit, so a caller reading only the
# exit code of a backgrounded run can tell a provider failure from its own timeout.
EXIT_CODES = {"succeeded": 0, "timed_out": 124, "cancelled": 130}

def now(): return datetime.now(timezone.utc).isoformat()
def jobs_root(): return (ROOT / "jobs").resolve()

def check_job(job):
    if not JOB_RE.fullmatch(job): raise SystemExit("invalid job id")
    return job

def job_dir(job): return jobs_root() / check_job(job)
def exit_code(status): return EXIT_CODES.get(status, 1)
def meta_path(job): return job_dir(job) / "job.json"

def job_data(job):
    """A record as a dict. Anything else is damaged and refused here, so no caller reaches
    .get() on it; they report it as corrupt or exit saying so."""
    path = meta_path(job)
    if not path.is_file(): raise SystemExit(f"unknown job {job}")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc: raise SystemExit(f"job record is not readable JSON: {exc}")
    if not isinstance(data, dict): raise SystemExit(f"job record is not an object: {type(data).__name__}")
    return data

@contextmanager
def state_lock():
    """Serialize job metadata changes."""
    private_dir(ROOT)
    lock = ROOT / ".state.lock"
    with lock.open("a+") as handle:
        os.chmod(lock, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)

def write_json(path, value):
    path = Path(path); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600); os.replace(temporary, path); os.chmod(path, 0o600)

def update(job, **changes):
    with state_lock():
        data = job_data(job); data.update(changes); write_json(meta_path(job), data); return data

def private_file(path, mode="wb"):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), mode)

def private_dir(path):
    """Create a directory only this user can enter, tightening one that predates this."""
    path.mkdir(parents=True, exist_ok=True); os.chmod(path, 0o700); return path

class Interrupted(Exception):
    """SIGTERM reached the runner. Without this, Python's default disposition would exit
    immediately, orphaning a child that is in its own session and never recording an outcome."""

def _raise_interrupted(signum, _frame): raise Interrupted(signum)

def kill_group(pgid, grace=5, process=None):
    """Terminate a process group, reaping our child while allowing graceful shutdown."""
    if not pgid: return
    try: os.killpg(pgid, signal.SIGTERM)
    except OSError: return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if process is not None: process.poll()
        try: os.killpg(pgid, 0)
        except OSError: return
        time.sleep(0.1)
    try: os.killpg(pgid, signal.SIGKILL)
    except OSError: pass

def process_matches_job(pid, job):
    """Return True for a match, False for a vanished/replaced process, or None if unknown."""
    if not pid: return None
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except OSError: return None
    try:
        result = subprocess.run(["ps", "eww", "-p", str(pid), "-o", "command="], text=True, capture_output=True, timeout=2)
        if result.returncode != 0: return None
        markers = re.findall(r"(?:^|\s)ASK_AGENT_JOB=(\S+)", result.stdout)
        return markers[-1] == job if markers else None
    except (OSError, subprocess.TimeoutExpired): return None

def output_events(job):
    """Read JSON objects from the raw log, ignoring plain text and incomplete lines."""
    path = job_dir(job) / "stdout.log"
    if not path.is_file(): return
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            line = line.strip()
            if not line.startswith("{"): continue
            try: event = json.loads(line)
            except ValueError: continue
            if isinstance(event, dict): yield event

def find_session(job):
    for event in output_events(job):
        for key in SESSION_KEYS:
            value = event.get(key)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{4,}", value): return value
    return None

def find_answer(job):
    """Read final text from Codex, Claude Code, or agy without changing the saved log."""
    answer = None
    for event in output_events(job):
        if event.get("type") == "turn.failed":
            answer = None
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
        elif event.get("type") == "result":
            if event.get("is_error") or event.get("subtype", "success") != "success":
                answer = None
                continue
            text = event.get("result")
        elif event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
            if result.get("status") == "ERROR":
                answer = None
                continue
            text = result.get("response")
        else:
            continue
        if isinstance(text, str): answer = text
    return answer

def read_prompt(path):
    if path is None: return None
    if path == "-": return sys.stdin.read()
    try: return Path(path).read_text(encoding="utf-8")
    except OSError as exc: raise SystemExit(f"cannot read prompt file: {exc}")

def cmd_run(args):
    if not args.argv: raise SystemExit("provide the provider command after `--`")
    if args.timeout <= 0: raise SystemExit("--timeout must be positive")
    cwd = Path(args.cwd).resolve()
    if not cwd.is_dir(): raise SystemExit(f"--cwd is not a directory: {cwd}")
    prompt = read_prompt(args.prompt_file)

    job = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    private_dir(ROOT); private_dir(jobs_root())
    folder = job_dir(job); folder.mkdir(mode=0o700); os.chmod(folder, 0o700)
    if prompt is not None:
        with private_file(folder / "prompt.txt", "w") as out: out.write(prompt)
    write_json(meta_path(job), {
        "job": job, "argv": args.argv, "cwd": str(cwd),
        "timeout_seconds": args.timeout, "prompt_file": "prompt.txt" if prompt is not None else None,
        "created_at": now(), "status": "queued", "exit_code": None, "session_id": None,
    })
    print(job, flush=True)
    return execute(job)

def execute(job):
    data = job_data(job)
    prompt_name = data.get("prompt_file")
    stdin_source = (job_dir(job) / prompt_name).open("rb") if prompt_name else None
    proc = None; reason = None; rc = None; previous_handlers = {}
    error = None
    try:
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(signum, _raise_interrupted)
            with private_file(job_dir(job) / "stdout.log") as out, private_file(job_dir(job) / "stderr.log") as err:
                with state_lock():
                    proc = subprocess.Popen(data["argv"], cwd=data["cwd"], stdin=stdin_source or subprocess.DEVNULL,
                                            stdout=out, stderr=err, start_new_session=True,
                                            env={**os.environ, "ASK_AGENT_JOB": job})
                    data.update(status="running", started_at=now(), pid=proc.pid, process_group=proc.pid)
                    write_json(meta_path(job), data)
                rc = proc.wait(timeout=data["timeout_seconds"])
        except subprocess.TimeoutExpired:
            reason = "timed_out"
        except (KeyboardInterrupt, Interrupted):
            reason = "interrupted"
        except Exception as exc:
            error = str(exc)
        finally:
            # Repeated interrupts must not abandon cleanup or the final job record.
            for signum in previous_handlers: signal.signal(signum, signal.SIG_IGN)
            if proc:
                kill_group(proc.pid, process=proc)
                try: rc = proc.wait(timeout=10)
                except subprocess.TimeoutExpired: rc = None
            if stdin_source: stdin_source.close()

        session_id = find_session(job)
        with state_lock():
            if not meta_path(job).is_file():
                raise SystemExit(f"ask-agent: the record for {job} disappeared while it ran "
                                 f"(pruned or deleted); the command finished but its outcome "
                                 f"could not be recorded")
            data = job_data(job)
            if reason is None and data.get("stop_requested"): reason = "stopped"
            status = {"timed_out": "timed_out", "interrupted": "cancelled", "stopped": "cancelled"}.get(reason)
            if error is not None:
                status = "failed"
                data["error"] = error
            elif status is None:
                status = "succeeded" if rc == 0 else "failed"
            data.update(status=status, exit_code=rc, finished_at=now(), stop_reason=reason, session_id=session_id)
            write_json(meta_path(job), data)
        if error is not None: print(f"ask-agent: {error}", file=sys.stderr)
        if status == "succeeded" and session_id is None:
            # Observed rather than guessed from the provider's flags, and only on
            # success: a failed job has already reported its failure.
            print("ask-agent: no session id in this job's output; it cannot be resumed, and the "
                  "command may not have asked for structured output", file=sys.stderr)
        return exit_code(status)
    finally:
        for signum, handler in previous_handlers.items(): signal.signal(signum, handler)

def effective_session(job, data):
    """job.json only gains session_id at completion, so a running job needs the log scanned.
    A finished job's recorded value is authoritative, including when it is null, so listing
    a large store does not reread every log."""
    if data.get("session_id") or data.get("finished_at"): return data.get("session_id")
    return find_session(job)

def effective_status(job, data):
    """A job whose process is gone without recording an outcome is abandoned, not running."""
    if data.get("status") == "running":
        match = process_matches_job(data.get("process_group"), job)
        if match is None: return "unknown"
        if match is False: return "abandoned"
    return data.get("status")

def known_jobs():
    return sorted(p.name for p in jobs_root().glob("*") if p.is_dir() and JOB_RE.fullmatch(p.name))

def cmd_status(args):
    """A listing succeeds even when one record in it is unreadable; a single named job
    that cannot be read fails instead. Oldest first, by recorded start time rather than job
    id: ids carry a random suffix, so two started in the same second sort arbitrarily."""
    jobs = [check_job(args.job)] if args.job else known_jobs()
    unreadable = False
    rows = []
    for job in jobs:
        if not meta_path(job).is_file():
            rows.append((record_time(job, {}), {"job": job, "status": "missing"}))
            unreadable = True; continue
        try: data = job_data(job)
        except (SystemExit, OSError, ValueError) as exc:
            rows.append((record_time(job, {}), {"job": job, "status": "corrupt", "error": str(exc)}))
            unreadable = True; continue
        fields = {key: data.get(key) for key in ("job", "exit_code", "cwd",
                                                 "created_at", "finished_at")}
        rows.append((record_time(job, data, "created_at"),
                     {**fields, "status": effective_status(job, data),
                      "session_id": effective_session(job, data)}))
    for _, row in sorted(rows, key=lambda row: row[0]):   # ties keep the job-id order
        print(json.dumps(row, sort_keys=True))
    return 1 if args.job and unreadable else 0

def cmd_session(args):
    job = check_job(args.job)
    found = effective_session(job, job_data(job))
    if not found: raise SystemExit("no session id in this job's output; it may not have started, or the "
                                   "command may not have asked for structured output")
    print(found)

def cmd_path(args):
    folder = job_dir(args.job)
    # A damaged job.json still has logs worth reading, so the directory is what must exist.
    if not folder.is_dir(): raise SystemExit(f"unknown job {args.job}")
    print(folder)

def cmd_answer(args):
    job = check_job(args.job)
    status = effective_status(job, job_data(job))
    if status != "succeeded":
        raise SystemExit(f"job is {status}; inspect the logs with `ask-agent path {job}`")
    answer = find_answer(job)
    if answer is None:
        raise SystemExit(f"no final answer found; inspect the logs with `ask-agent path {job}`")
    print(answer)

def read_job(job):
    """job.json as far as it can be read; a record too damaged to parse is an empty one."""
    try: return job_data(job)
    except (SystemExit, OSError, ValueError): return {}

def record_time(job, data, *keys):
    """The first of these timestamps the record carries, in epoch seconds, falling back to
    the job directory for a record too damaged to hold one."""
    for key in keys:
        stamp = data.get(key)
        if isinstance(stamp, str):
            try: return datetime.fromisoformat(stamp).timestamp()
            except ValueError: pass
    try: return job_dir(job).stat().st_mtime
    except OSError: return 0.0

def job_age_days(job, data):
    """Age from when the job finished, or from when it started if it never did."""
    return (time.time() - record_time(job, data, "finished_at", "created_at")) / 86400

def remove_job(job):
    """Delete one job directory. job_dir validates the id; the rest refuses anything
    that is not a real directory sitting directly in this store."""
    folder = job_dir(job)
    if folder.is_symlink() or folder.parent != jobs_root() or not folder.is_dir():
        raise SystemExit(f"refusing to delete {folder}")
    shutil.rmtree(folder)

def cmd_prune(args):
    if args.older_than < 0: raise SystemExit("--older-than must not be negative")
    matched = 0
    for job in known_jobs():
        data = read_job(job)
        age = job_age_days(job, data)
        if age < args.older_than: continue
        matched += 1
        # The status is reported, not enforced: the listing is how you spot a job worth
        # keeping. Nothing is exempt, so the retention window is the guard.
        if args.delete: remove_job(job)
        print(json.dumps({"job": job, "status": effective_status(job, data) if data else "corrupt",
                          "age_days": round(age, 2), "session_id": data.get("session_id"),
                          "deleted": bool(args.delete)}, sort_keys=True))
    if not args.delete and matched:
        print(f"ask-agent: {matched} job(s) match; re-run with --delete to remove them", file=sys.stderr)
    return 0

def cmd_wait(args):
    """Block until a job stops running, then exit with that job's own outcome code."""
    job = check_job(args.job)
    data = job_data(job)
    if args.timeout is not None and args.timeout <= 0: raise SystemExit("--timeout must be positive")
    # The job's own deadline plus a minute, covering the kill grace period and the
    # final write of the record.
    limit = args.timeout if args.timeout is not None else (data.get("timeout_seconds") or 1800) + 60
    deadline = time.monotonic() + limit
    while True:
        status = effective_status(job, job_data(job))
        if status in TERMINAL:
            print(status)
            return exit_code(status)
        if time.monotonic() >= deadline:
            print(f"ask-agent: gave up waiting for {job} after {limit:g}s; "
                  f"it is {status} and was not stopped", file=sys.stderr)
            return 125
        time.sleep(1)

def cmd_stop(args):
    job = check_job(args.job)
    with state_lock():   # one critical section: a natural completion cannot land mid-check
        data = job_data(job)
        if data.get("status") != "running": raise SystemExit(f"job is not running (status: {data.get('status')})")
        pid = data.get("process_group")
        match = process_matches_job(pid, job)
        if match is None:
            raise SystemExit("cannot verify the job process; no signal sent and job state unchanged")
        if match is False:
            data.update(status="abandoned", finished_at=now(), stop_reason="process_gone")
            write_json(meta_path(job), data)
            raise SystemExit("job process is gone; recorded as abandoned")
        data["stop_requested"] = True
        write_json(meta_path(job), data)
    kill_group(pid)

def split_argv(raw):
    """Everything after the first `--` is the provider command, verbatim."""
    if "--" in raw:
        at = raw.index("--"); return raw[:at], raw[at + 1:]
    return raw, []

def main():
    mine, provider_argv = split_argv(sys.argv[1:])
    parser = argparse.ArgumentParser(prog="ask-agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run a provider command, recorded and time-bounded")
    run.add_argument("--cwd", default=".", help="working directory for the provider command")
    run.add_argument("--timeout", type=int, default=1800, help="seconds before the process group is terminated")
    run.add_argument("--prompt-file", metavar="PATH", help="file piped to the command's stdin; `-` reads this process's stdin")
    status = sub.add_parser("status", help="show job state"); status.add_argument("job", nargs="?")
    answer = sub.add_parser("answer", help="print the final answer from a successful job"); answer.add_argument("job")
    path = sub.add_parser("path", help="print a job's directory, which holds stdout.log and stderr.log")
    path.add_argument("job")
    session = sub.add_parser("session", help="print the job's native session id, even while it runs")
    session.add_argument("job")
    wait = sub.add_parser("wait", help="block until a job stops running, exiting with its outcome")
    wait.add_argument("job")
    wait.add_argument("--timeout", type=float, metavar="SECONDS",
                      help="how long to wait; defaults to the job's own timeout plus a minute")
    stop = sub.add_parser("stop", help="terminate a running job's process group"); stop.add_argument("job")
    prune = sub.add_parser("prune", help="list, and with --delete remove, finished jobs past a retention window")
    prune.add_argument("--older-than", type=float, default=30, metavar="DAYS",
                       help="retention window in days; jobs finished longer ago than this match")
    prune.add_argument("--delete", action="store_true", help="actually remove them; without it this only lists")
    args = parser.parse_args(mine)
    args.argv = provider_argv
    return {"run": cmd_run, "status": cmd_status, "answer": cmd_answer, "path": cmd_path,
            "session": cmd_session, "wait": cmd_wait, "stop": cmd_stop,
            "prune": cmd_prune}[args.action](args)

if __name__ == "__main__": raise SystemExit(main())
