#!/usr/bin/env python3
"""Local job runner for durable, auditable coding-agent CLI handoffs.

It intentionally does not invent an agent-to-agent protocol.  It invokes the
provider CLI, records exactly what happened, and preserves the native session
identifier so a later job can resume the same conversation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("XAGENT_HOME", ".xagent")).expanduser()
PROVIDERS = Path(os.environ.get("XAGENT_PROVIDERS", Path(__file__).resolve().parents[1] / "providers")).expanduser()
STATE_LOCK = threading.Lock()


def now(): return datetime.now(timezone.utc).isoformat()
def job_dir(job): return ROOT / "jobs" / job
def meta_path(job): return job_dir(job) / "job.json"
def read_json(path): return json.loads(Path(path).read_text())
def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
def write_private_text(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
def load_provider(name):
    path = PROVIDERS / f"{name}.json"
    if not path.exists(): raise SystemExit(f"unknown provider {name!r}; add {path}")
    return read_json(path)


def render(parts, values):
    return [str(part).format(**values) for part in parts]


def validate_passthrough(spec, args):
    reserved = spec.get("reserved_args", [])
    for value in args:
        if any(value == flag or value.startswith(flag + "=") for flag in reserved):
            raise SystemExit(f"{value!r} is controlled by XAgent; use its dedicated option instead")


def selection(spec, prompt, model, effort):
    if model is None or effort is None:
        raise SystemExit("model and effort are required for a new task. "
                         "Run `xagent models PROVIDER`, choose based on task needs and cost, or pass "
                         "--model default --effort default to explicitly use provider defaults.")
    return {"model": model, "effort": effort, "model_source": "explicit", "effort_source": "explicit"}


def build_command(provider, cwd, prompt, mode, resume=None, extra=(), model=None, effort=None):
    spec = load_provider(provider)
    if mode not in spec["policies"]:
        raise SystemExit(f"{provider} does not define policy {mode!r}")
    command = spec["resume"] if resume else spec["new"]
    values = {"cwd": str(Path(cwd).resolve()), "prompt": prompt,
              "session_id": resume or "", **spec["policies"][mode]}
    validate_passthrough(spec, extra)
    picked = selection(spec, prompt, model, effort)
    tuning = []
    if picked["model"] != "default": tuning.extend(render(spec.get("model_args", []), {"model": picked["model"]}))
    if picked["effort"] and picked["effort"] != "default": tuning.extend(render(spec.get("effort_args", []), {"effort": picked["effort"]}))
    rendered = render(command, values); at = spec.get("passthrough_position", 0)
    return [spec["binary"], *tuning, *rendered[:at], *extra, *rendered[at:]], spec, picked


def add_event(job, channel, text):
    path = job_dir(job) / "events.jsonl"
    with STATE_LOCK:
        with path.open("a") as out:
            out.write(json.dumps({"at": now(), "channel": channel, "text": text}) + "\n")
    os.chmod(path, 0o600)


def update(job, **changes):
    with STATE_LOCK:
        data = read_json(meta_path(job)); data.update(changes); write_json(meta_path(job), data)


def discover_session(spec, text):
    pattern = spec.get("session_id_regex")
    if not pattern: return None
    hit = re.search(pattern, text)
    return hit.group(1) if hit else None


def worker(job):
    data = read_json(meta_path(job)); command = data["command"]
    timeout = data.get("timeout_seconds")
    spec = load_provider(data["provider"])
    update(job, status="running", started_at=now())
    add_event(job, "bridge", "process started")
    prompt_stream = None
    stdin = subprocess.DEVNULL
    if spec.get("prompt_transport") == "stdin":
        prompt_stream = (job_dir(job) / data["prompt_file"]).open("r")
        stdin = prompt_stream
    proc = subprocess.Popen(command, cwd=data["cwd"], stdin=stdin,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        start_new_session=True, env={**os.environ, "XAGENT_JOB": job})
    if prompt_stream: prompt_stream.close()
    update(job, pid=proc.pid, process_group=proc.pid)
    done = threading.Event()
    cancelled_by_parent = threading.Event()
    owner_pid = data.get("owner_pid")
    def watch_owner():
        # A detached runner is intentionally re-parented, so process groups alone
        # cannot express ownership of the caller's agent session.
        while not done.wait(1):
            try: os.kill(owner_pid, 0)
            except ProcessLookupError:
                cancelled_by_parent.set()
                add_event(job, "bridge", f"owner pid {owner_pid} exited; process group terminated")
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                return
    owner_thread = threading.Thread(target=watch_owner, daemon=True) if owner_pid else None
    if owner_thread: owner_thread.start()
    session = None
    def consume(stream, name):
        nonlocal session
        for line in iter(stream.readline, ""):
            add_event(job, name, line.rstrip("\n"))
            session = session or discover_session(spec, line)
            if session: update(job, provider_session_id=session)
        stream.close()
    threads = [threading.Thread(target=consume, args=(proc.stdout, "stdout")),
               threading.Thread(target=consume, args=(proc.stderr, "stderr"))]
    for thread in threads: thread.start()
    try:
        rc = proc.wait(timeout=timeout)
        status = "cancelled" if cancelled_by_parent.is_set() else ("succeeded" if rc == 0 else "failed")
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try: rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); rc = proc.wait()
        status = "timed_out"
        add_event(job, "bridge", f"timeout after {timeout} seconds; process group terminated")
    done.set()
    for thread in threads: thread.join()
    if owner_thread: owner_thread.join(timeout=1)
    update(job, status=status, exit_code=rc, finished_at=now(), provider_session_id=session or data.get("provider_session_id"))
    add_event(job, "bridge", f"process finished with status={status}, exit_code={rc}")
    return 0 if status == "succeeded" else 1


def create_job(args):
    resume = None
    if args.resume:
        prior = read_json(meta_path(args.resume))
        if prior["provider"] != args.provider: raise SystemExit("a job can only resume with its original provider")
        resume = prior.get("provider_session_id")
        if not resume: raise SystemExit(f"job {args.resume} has no captured provider session id")
        if args.model is None: args.model = prior.get("model_selection", {}).get("model")
        if args.effort is None: args.effort = prior.get("model_selection", {}).get("effort")
    command, _, picked = build_command(args.provider, args.cwd, args.prompt, args.mode, resume, args.provider_arg,
                                       args.model, args.effort)
    job = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    folder = job_dir(job); folder.mkdir(parents=True, mode=0o700)
    os.chmod(folder, 0o700)
    write_private_text(folder / "prompt.txt", args.prompt)
    data = {"job": job, "parent_job": args.resume, "provider": args.provider, "provider_session_id": None,
            "cwd": str(Path(args.cwd).resolve()), "mode": args.mode, "timeout_seconds": args.timeout,
            "owner_pid": (os.getppid() if args.detach and not args.survive_parent else None),
            "model_selection": picked,
            "created_at": now(), "status": "queued", "command": command, "prompt_file": "prompt.txt"}
    write_json(meta_path(job), data)
    add_event(job, "bridge", "job created")
    return job


def cmd_run(args):
    job = create_job(args)
    if args.detach:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_worker", job],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        print(job); return 0
    print(job)
    return worker(job)


def cmd_status(args):
    jobs = [args.job] if args.job else sorted(p.name for p in (ROOT / "jobs").glob("*") if p.is_dir())
    for job in jobs:
        data = read_json(meta_path(job)); print(json.dumps({k: data.get(k) for k in ("job", "provider", "status", "pid", "provider_session_id", "created_at", "finished_at")}, sort_keys=True))


def cmd_logs(args):
    path = job_dir(args.job) / "events.jsonl"
    if args.raw: print(path.read_text(), end="")
    else:
        for line in path.read_text().splitlines():
            event = json.loads(line); print(f"{event['at']} {event['channel']}: {event['text']}")


def cmd_stop(args):
    data = read_json(meta_path(args.job)); pid = data.get("process_group")
    if not pid or data["status"] not in ("queued", "running"): raise SystemExit("job is not running")
    try: os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError: pass
    update(args.job, status="stopping"); add_event(args.job, "bridge", "stop requested")


def cmd_doctor(args):
    names = [args.provider] if args.provider else [p.stem for p in PROVIDERS.glob("*.json")]
    bad = False
    for name in names:
        spec = load_provider(name); binary = spec["binary"]; found = shutil.which(binary)
        print(f"{name}: {'found at ' + found if found else 'NOT FOUND: install ' + binary}")
        bad |= found is None
    print("Authentication is deliberately not probed: run the provider's native login/status command so no credentials are logged.")
    return 1 if bad else 0


def cmd_models(args):
    names = [args.provider] if args.provider else sorted(p.stem for p in PROVIDERS.glob("*.json"))
    for name in names:
        spec = load_provider(name)
        print(f"{name} catalog (maintained {spec.get('catalog_as_of', 'unknown')}):")
        print("MODEL\tINPUT $/MTok\tOUTPUT $/MTok\tEFFORT\tDESCRIPTION")
        for model in spec.get("models", []):
            print(f"{model['id']}\t{model.get('input_usd_per_mtok', '—')}\t{model.get('output_usd_per_mtok', '—')}\t"
                  f"{','.join(model['effort_options'])}\t{model['description']}")
        print("Catalog entries are maintained choices, not an entitlement check; edit providers/ when you update it.\n")


def main():
    parser = argparse.ArgumentParser(prog="xagent", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="start a provider task")
    run.add_argument("provider"); run.add_argument("prompt"); run.add_argument("--cwd", default=".")
    run.add_argument("--mode", choices=("read-only", "workspace-write", "unrestricted"), default="read-only")
    run.add_argument("--resume", metavar="JOB", help="resume this bridge job's captured native session")
    run.add_argument("--timeout", type=int, default=1800); run.add_argument("--detach", action="store_true")
    run.add_argument("--survive-parent", action="store_true", help="do not cancel a detached job when its caller exits")
    run.add_argument("--model", help="provider-native model ID or alias; required for new tasks")
    run.add_argument("--effort", help="provider-native effort; required for new tasks")
    run.add_argument("--provider-arg", "--passthrough", action="append", default=[], metavar="ARG",
                     help="append one literal, non-reserved provider CLI argument (repeat for values)")
    stat = sub.add_parser("status"); stat.add_argument("job", nargs="?")
    logs = sub.add_parser("logs"); logs.add_argument("job"); logs.add_argument("--raw", action="store_true")
    stop = sub.add_parser("stop"); stop.add_argument("job")
    doc = sub.add_parser("doctor"); doc.add_argument("provider", nargs="?")
    models = sub.add_parser("models", help="show the maintained provider model catalog")
    models.add_argument("provider", nargs="?")
    internal = sub.add_parser("_worker"); internal.add_argument("job")
    args = parser.parse_args()
    return {"run": cmd_run, "status": cmd_status, "logs": cmd_logs, "stop": cmd_stop,
            "doctor": cmd_doctor, "models": cmd_models,
            "_worker": lambda a: worker(a.job)}[args.action](args)

if __name__ == "__main__": raise SystemExit(main())
