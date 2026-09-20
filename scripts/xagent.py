#!/usr/bin/env python3
"""Record and bound a coding-agent CLI invocation.

The caller builds the provider command, with help from the xagent skill; this runner
executes it exactly as written, captures both streams to files, enforces a timeout, and
keeps a durable record of what ran. Knowledge about which flags a provider takes lives
in the skill, not here.
"""
from __future__ import annotations

import argparse
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

ROOT = Path(os.environ.get("XAGENT_HOME", ".xagent")).expanduser()
JOB_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
SESSION_KEYS = ("session_id", "thread_id", "conversation_id")
STRUCTURED_HINTS = ("--json", "--output-format", "--experimental-json")

def now(): return datetime.now(timezone.utc).isoformat()
def jobs_root(): return (ROOT / "jobs").resolve()

def check_job(job):
    if not JOB_RE.fullmatch(job): raise SystemExit("invalid job id")
    return job

def job_dir(job): return jobs_root() / check_job(job)
def meta_path(job): return job_dir(job) / "job.json"

def job_data(job):
    path = meta_path(job)
    if not path.is_file(): raise SystemExit(f"unknown job {job}")
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path, value):
    path = Path(path); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600); os.replace(temporary, path); os.chmod(path, 0o600)

def update(job, **changes):
    data = job_data(job); data.update(changes); write_json(meta_path(job), data); return data

def private_file(path, mode="wb"):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), mode)

def kill_group(pgid, grace=5):
    """Terminate a process group. Never raises: callers use this during cleanup."""
    if not pgid: return
    try: os.killpg(pgid, signal.SIGTERM)
    except OSError: return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try: os.killpg(pgid, 0)
        except OSError: return
        time.sleep(0.1)
    try: os.killpg(pgid, signal.SIGKILL)
    except OSError: pass

def process_matches_job(pid, job):
    """True only if pid is live and carries this job's marker, so a recycled PID is never signalled."""
    if not pid: return False
    try:
        result = subprocess.run(["ps", "eww", "-p", str(pid), "-o", "command="], text=True, capture_output=True, timeout=2)
        return result.returncode == 0 and f"XAGENT_JOB={job}" in result.stdout
    except (OSError, subprocess.TimeoutExpired): return False

def find_session(job):
    """Recover a native session id from saved output, after the fact rather than mid-stream.

    This is the one thing a reader cannot get from job.json alone, so it is recorded there
    on completion and surfaced by `status`.
    """
    path = job_dir(job) / "stdout.log"
    if not path.is_file(): return None
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            line = line.strip()
            if not line.startswith("{"): continue
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): continue
            for key in SESSION_KEYS:
                value = event.get(key)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{4,}", value): return value
    return None

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
    parent = check_job(args.parent) if args.parent else None

    job = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    folder = job_dir(job); folder.mkdir(parents=True, mode=0o700); os.chmod(folder, 0o700)
    if prompt is not None:
        with private_file(folder / "prompt.txt", "w") as out: out.write(prompt)
    write_json(meta_path(job), {
        "job": job, "parent_job": parent, "argv": args.argv, "cwd": str(cwd),
        "timeout_seconds": args.timeout, "prompt_file": "prompt.txt" if prompt is not None else None,
        "created_at": now(), "status": "queued", "exit_code": None, "session_id": None,
    })
    print(job, flush=True)
    if not any(hint in item for item in args.argv for hint in STRUCTURED_HINTS):
        print(f"xagent: {args.argv[0]} was not asked for structured output; no session id will be "
              f"recovered for this job, and its log will not be machine-parsable", file=sys.stderr)
    return execute(job)

def execute(job):
    data = job_data(job)
    prompt_name = data.get("prompt_file")
    stdin_source = (job_dir(job) / prompt_name).open("rb") if prompt_name else None
    proc = None; reason = None; rc = None
    try:
        with private_file(job_dir(job) / "stdout.log") as out, private_file(job_dir(job) / "stderr.log") as err:
            update(job, status="running", started_at=now())
            proc = subprocess.Popen(data["argv"], cwd=data["cwd"], stdin=stdin_source or subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True,
                                    env={**os.environ, "XAGENT_JOB": job})
            update(job, pid=proc.pid, process_group=proc.pid)
            try:
                rc = proc.wait(timeout=data["timeout_seconds"])
            except subprocess.TimeoutExpired:
                reason = "timed_out"; kill_group(proc.pid)
                try: rc = proc.wait(timeout=10)
                except subprocess.TimeoutExpired: rc = None
    except KeyboardInterrupt:
        reason = "interrupted"
        if proc: kill_group(proc.pid); rc = proc.poll()
    except Exception as exc:
        # Record the outcome before any cleanup, so a failing kill can never swallow the status.
        update(job, status="failed", finished_at=now(), error=str(exc))
        if proc: kill_group(proc.pid)
        raise SystemExit(f"xagent: {exc}")
    finally:
        if stdin_source: stdin_source.close()

    if reason is None and job_data(job).get("stop_requested"): reason = "stopped"
    status = {"timed_out": "timed_out", "interrupted": "cancelled", "stopped": "cancelled"}.get(reason)
    if status is None: status = "succeeded" if rc == 0 else "failed"
    update(job, status=status, exit_code=rc, finished_at=now(), stop_reason=reason, session_id=find_session(job))
    return 0 if status == "succeeded" else 1

def effective_status(job, data):
    """A job whose process is gone without recording an outcome is abandoned, not running."""
    if data.get("status") == "running" and not process_matches_job(data.get("process_group"), job):
        return "abandoned"
    return data.get("status")

def cmd_status(args):
    jobs = [check_job(args.job)] if args.job else sorted(
        p.name for p in jobs_root().glob("*") if p.is_dir() and JOB_RE.fullmatch(p.name))
    for job in jobs:
        try: data = job_data(job)
        except (SystemExit, OSError, ValueError) as exc:
            print(json.dumps({"job": job, "status": "corrupt", "error": str(exc)})); continue
        fields = {key: data.get(key) for key in ("job", "exit_code", "session_id", "cwd", "created_at", "finished_at")}
        print(json.dumps({**fields, "status": effective_status(job, data)}, sort_keys=True))

def cmd_path(args):
    print(job_dir(args.job))

def cmd_stop(args):
    job = check_job(args.job); data = job_data(job)
    if data.get("status") != "running": raise SystemExit(f"job is not running (status: {data.get('status')})")
    pid = data.get("process_group")
    if not process_matches_job(pid, job):
        update(job, status="abandoned", finished_at=now(), stop_reason="process_gone")
        raise SystemExit("job process is gone; recorded as abandoned")
    update(job, stop_requested=True)
    kill_group(pid)

def split_argv(raw):
    """Everything after the first `--` is the provider command, verbatim."""
    if "--" in raw:
        at = raw.index("--"); return raw[:at], raw[at + 1:]
    return raw, []

def main():
    mine, provider_argv = split_argv(sys.argv[1:])
    parser = argparse.ArgumentParser(prog="xagent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run a provider command, recorded and time-bounded")
    run.add_argument("--cwd", default=".", help="working directory for the provider command")
    run.add_argument("--timeout", type=int, default=1800, help="seconds before the process group is terminated")
    run.add_argument("--prompt-file", metavar="PATH", help="file piped to the command's stdin; `-` reads this process's stdin")
    run.add_argument("--parent", metavar="JOB", help="record this job as a continuation of an earlier one")
    status = sub.add_parser("status", help="show job state"); status.add_argument("job", nargs="?")
    path = sub.add_parser("path", help="print a job's directory, which holds stdout.log and stderr.log")
    path.add_argument("job")
    stop = sub.add_parser("stop", help="terminate a running job's process group"); stop.add_argument("job")
    args = parser.parse_args(mine)
    args.argv = provider_argv
    return {"run": cmd_run, "status": cmd_status,
            "path": cmd_path, "stop": cmd_stop}[args.action](args)

if __name__ == "__main__": raise SystemExit(main())
