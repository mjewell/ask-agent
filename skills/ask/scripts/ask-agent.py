#!/usr/bin/env python3
"""Record and bound a coding-agent CLI invocation.

The caller builds the provider command, with help from the ask skill; this runner
executes it as written, captures both streams to files, enforces a timeout, and keeps a
durable record of what ran. Knowledge about which flags a provider takes lives in the
skill, not here.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
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
# An argv element exactly equal to this is replaced by the prompt text, for CLIs that
# take the prompt as an argument rather than on stdin.
PROMPT_ARG = "{prompt}"
# 124 is what timeout(1) reports, and 130 is a SIGINT exit, so a caller reading only the
# exit code of a backgrounded run can tell a provider failure from its own timeout.
EXIT_CODES = {"succeeded": 0, "timed_out": 124, "cancelled": 130}
# Covers a runner's cleanup after SIGTERM: a 5s kill grace, a reap capped at 10s, a log
# scan and a write.
CLEANUP_SECONDS = 30
STATUS_LIMIT = 20

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
    .get() on it; they report it as unreadable or exit saying so."""
    path = meta_path(job)
    if not path.is_file(): raise SystemExit(f"unknown job {job}")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc: raise SystemExit(f"job record is not readable JSON: {exc}")
    if not isinstance(data, dict): raise SystemExit(f"job record is not an object: {type(data).__name__}")
    return data

def write_json(path, value):
    path = Path(path); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600); os.replace(temporary, path); os.chmod(path, 0o600)

def private_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb")

def private_dir(path):
    """Create a directory only this user can enter, tightening one that predates this."""
    path.mkdir(parents=True, exist_ok=True); os.chmod(path, 0o700); return path

def hold_runner_lock(folder):
    """Taken by the runner for its whole life. The kernel releases it however the runner
    exits, so a free lock under a record still saying running means the runner died.
    The descriptor is not inherited, so a provider left running cannot keep it held."""
    fd = os.open(folder / "runner.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd

def runner_alive(job):
    try: fd = os.open(job_dir(job) / "runner.lock", os.O_RDONLY)
    except FileNotFoundError: return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError: return True
    finally: os.close(fd)

def job_state(job):
    """The record, with a running job whose runner has gone reported as `runner_died`.
    The runner writes its outcome before releasing the lock, so the record is read again
    once the lock is seen free."""
    data = job_data(job)
    if data.get("status") == "running" and not runner_alive(job):
        data = job_data(job)
        if data.get("status") == "running": data["status"] = "runner_died"
    return data

class Interrupted(Exception):
    """SIGTERM reached the runner. Without this, Python's default disposition would exit
    immediately, orphaning a child that is in its own session and never recording an outcome."""

def _raise_interrupted(signum, _frame): raise Interrupted(signum)

def kill_group(pgid, process, grace=5):
    """Terminate a process group, reaping our child while allowing graceful shutdown."""
    try: os.killpg(pgid, signal.SIGTERM)
    except OSError: return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        process.poll()
        try: os.killpg(pgid, 0)
        except OSError: return
        time.sleep(0.1)
    try: os.killpg(pgid, signal.SIGKILL)
    except OSError: pass

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
    # Built under a hidden name and renamed into place, so no reader sees a job without
    # its record. The lock is held from before the record exists.
    staging = jobs_root() / f".{job}"
    staging.mkdir(mode=0o700); os.chmod(staging, 0o700)
    hold_runner_lock(staging)
    with private_file(staging / "prompt.txt") as out: out.write(prompt.encode("utf-8"))
    data = {"job": job, "argv": args.argv, "cwd": str(cwd), "timeout_seconds": args.timeout,
            "created_at": now(), "status": "running", "runner_pid": os.getpid(),
            "exit_code": None, "session_id": None}
    write_json(staging / "job.json", data)
    os.rename(staging, job_dir(job))
    print(job, flush=True)
    return execute(job, data, prompt)

def execute(job, data, prompt):
    folder = job_dir(job)
    argv = [prompt if arg == PROMPT_ARG else arg for arg in data["argv"]]
    stdin_source = None if PROMPT_ARG in data["argv"] else (folder / "prompt.txt").open("rb")
    proc = None; reason = None; rc = None; error = None; previous_handlers = {}
    try:
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(signum, _raise_interrupted)
            with private_file(folder / "stdout.log") as out, private_file(folder / "stderr.log") as err:
                proc = subprocess.Popen(argv, cwd=data["cwd"], stdin=stdin_source or subprocess.DEVNULL,
                                        stdout=out, stderr=err, start_new_session=True)
                rc = proc.wait(timeout=data["timeout_seconds"])
        except subprocess.TimeoutExpired:
            reason = "timed_out"
        except (KeyboardInterrupt, Interrupted):
            reason = "cancelled"
        except Exception as exc:
            error = str(exc)
        finally:
            # Repeated interrupts must not abandon cleanup or the final job record.
            for signum in previous_handlers: signal.signal(signum, signal.SIG_IGN)
            if proc:
                kill_group(proc.pid, proc)
                try: rc = proc.wait(timeout=10)
                except subprocess.TimeoutExpired: rc = None
            if stdin_source: stdin_source.close()

        status = reason or ("succeeded" if rc == 0 else "failed")
        session_id = find_session(job)
        if not meta_path(job).is_file():
            raise SystemExit(f"ask-agent: the record for {job} was deleted while it ran; the "
                             f"command finished but its outcome could not be recorded")
        data.update(status=status, exit_code=rc, finished_at=now(), session_id=session_id)
        if error is not None: data["error"] = error
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

def known_jobs():
    return sorted(p.name for p in jobs_root().glob("*") if p.is_dir() and JOB_RE.fullmatch(p.name))

def status_row(job):
    path = str(job_dir(job))
    try: data = job_state(job)
    except (SystemExit, OSError) as exc:
        return {"job": job, "status": "unreadable", "error": str(exc), "path": path}
    fields = {key: data.get(key) for key in ("job", "status", "exit_code", "cwd", "created_at", "finished_at")}
    return {**fields, "session_id": effective_session(job, data), "path": path}

def started_at(row):
    """Ids carry a random suffix, so two jobs started in the same second sort arbitrarily
    by id; the recorded start time orders them. An unreadable record has only its id."""
    if "created_at" in row: return datetime.fromisoformat(row["created_at"])
    return datetime.strptime(row["job"][:15], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)

def cmd_status(args):
    """A listing succeeds even when one record in it is unreadable; a single named job
    that cannot be read fails instead."""
    if args.job:
        if args.session or args.limit is not None: raise SystemExit("JOB cannot be combined with --session or --limit")
        if not job_dir(args.job).is_dir(): raise SystemExit(f"unknown job {args.job}")
        row = status_row(args.job)
        print(json.dumps(row, sort_keys=True))
        return 1 if row["status"] == "unreadable" else 0
    limit = STATUS_LIMIT if args.limit is None else args.limit
    if limit < 0: raise SystemExit("--limit must not be negative")
    rows = [status_row(job) for job in known_jobs()]
    if args.session: rows = [row for row in rows if row.get("session_id") == args.session]
    for row in sorted(rows, key=started_at, reverse=True)[:limit or None]:
        print(json.dumps(row, sort_keys=True))
    return 0

def cmd_session(args):
    job = check_job(args.job)
    found = effective_session(job, job_data(job))
    if not found: raise SystemExit("no session id in this job's output; it may not have started, or the "
                                   "command may not have asked for structured output")
    print(found)

def cmd_answer(args):
    job = check_job(args.job)
    status = job_state(job)["status"]
    if status != "succeeded":
        raise SystemExit(f"job is {status}; inspect the logs in {job_dir(job)}")
    answer = find_answer(job)
    if answer is None:
        raise SystemExit(f"no final answer found; inspect the logs in {job_dir(job)}")
    print(answer)

def cmd_wait(args):
    """Block until a job stops running, then exit with that job's own outcome code."""
    job = check_job(args.job)
    data = job_data(job)
    if args.timeout is not None and args.timeout <= 0: raise SystemExit("--timeout must be positive")
    limit = args.timeout if args.timeout is not None else data["timeout_seconds"] + CLEANUP_SECONDS
    deadline = time.monotonic() + limit
    while True:
        status = job_state(job)["status"]
        if status != "running":
            print(status)
            return exit_code(status)
        if time.monotonic() >= deadline:
            print(f"ask-agent: gave up waiting for {job} after {limit:g}s; "
                  f"it is {status} and was not stopped", file=sys.stderr)
            return 125
        time.sleep(0.5)

def cmd_stop(args):
    job = check_job(args.job)
    data = job_state(job)
    if data["status"] != "running": raise SystemExit(f"job is not running (status: {data['status']})")
    # The runner's lock is held, so this pid is still the runner. It turns SIGTERM into
    # stopping the provider's process group and recording the job as cancelled.
    try: os.kill(data["runner_pid"], signal.SIGTERM)
    except ProcessLookupError: pass   # it finished in between; report what it recorded
    deadline = time.monotonic() + CLEANUP_SECONDS
    while runner_alive(job):
        if time.monotonic() >= deadline:
            raise SystemExit(f"sent SIGTERM, but {job} is still running after {CLEANUP_SECONDS}s")
        time.sleep(0.1)
    print(job_state(job)["status"])

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
    run.add_argument("--prompt-file", metavar="PATH", required=True,
                     help=f"saved as prompt.txt and piped to the command's stdin, or substituted for "
                          f"an argument that is exactly {PROMPT_ARG}; `-` reads this process's stdin")
    status = sub.add_parser("status", help="show a job's state and directory; omit JOB to list jobs, newest first")
    status.add_argument("job", nargs="?")
    status.add_argument("--session", metavar="ID", help="list only jobs in this provider session")
    status.add_argument("--limit", type=int, metavar="N",
                        help=f"list at most N jobs (default {STATUS_LIMIT}); 0 lists all")
    answer = sub.add_parser("answer", help="print the final answer from a successful job"); answer.add_argument("job")
    session = sub.add_parser("session", help="print the job's native session id, even while it runs")
    session.add_argument("job")
    wait = sub.add_parser("wait", help="block until a job stops running, exiting with its outcome")
    wait.add_argument("job")
    wait.add_argument("--timeout", type=float, metavar="SECONDS",
                      help="how long to wait; defaults to the job's own timeout plus 30 seconds")
    stop = sub.add_parser("stop", help="stop a running job and wait for its outcome to be recorded")
    stop.add_argument("job")
    args = parser.parse_args(mine)
    args.argv = provider_argv
    return {"run": cmd_run, "status": cmd_status, "answer": cmd_answer, "session": cmd_session,
            "wait": cmd_wait, "stop": cmd_stop}[args.action](args)

if __name__ == "__main__": raise SystemExit(main())
