# XAgent (cross-agent)

XAgent runs a coding-agent CLI and records what happened. It is a recording exec wrapper, nothing more: you
hand it a command, it runs that command exactly as written, captures both streams, enforces a timeout, and
keeps a durable job record.

Knowing *how* to build a provider command is the [xagent skill](skills/xagent/SKILL.md)'s job, not the
runner's. The skill carries recommended invocations, sandbox settings, and per-provider flags, and a calling
agent adapts them case by case. That is the right place for judgment and the wrong place for a schema — a
validator can only see whether two flags collide, never whether they collide in intent.

```sh
xagent() { python3 /path/to/xagent/scripts/xagent.py "$@"; }

xagent run --cwd /repo --timeout 900 --prompt-file /tmp/task.md \
  -- codex exec --json -s read-only -C /repo --model gpt-5.6-sol -
```

Everything after `--` is the provider's command, passed through untouched.

## What it guarantees

- **A durable job record.** Every run gets an id and a directory under `.xagent/jobs/` (or `$XAGENT_HOME`)
  containing `job.json`, `prompt.txt`, `stdout.log`, and `stderr.log`. `job.json` holds the exact argv, the
  working directory, the timeout, timestamps, PID, exit code, final status, any recorded parent job, and the
  native session id recovered from the output.
- **Verbatim execution.** The argv you pass after `--` is what runs, and what is recorded. XAgent never
  injects, reorders, or rewrites a flag.
- **A hard timeout.** The child runs in its own process group. On timeout the whole group gets TERM, a
  grace period, then KILL — so a CLI's own children die with it.
- **Honest status.** A job whose process vanished without recording an outcome reports as `abandoned`, not
  `running`. `stop` verifies the target process carries this job's `XAGENT_JOB` marker before signalling, so
  a recycled PID is never hit.
- **Private artifacts.** Files are `0600` inside a `0700` directory.

## What it does not do

- **It is not a sandbox.** Sandbox and permission flags belong to the provider and are enforced by the
  provider. XAgent passes them through and records them. For hard confinement, run it inside a container or
  VM and pass only the directory you intend.
- **It does not choose flags for you.** No adapter, no templates, no policy mapping. The skill recommends,
  you decide, xagent records.
- **It does not resume for you.** It recovers the native session id from the output and hands it to you via
  `session` and `status`; you write the provider's own resume command. `--parent JOB` records the lineage.
- **It does not refuse anything.** If a command lacks a structured-output flag, xagent warns that `session`
  and log parsing will not work, then runs it. There is no denylist, because a refusal would prevent
  nothing — the same CLI is one Bash call away.
- **It does not wrap your shell.** Job state and output are ordinary files, so `cat`, `tail -f`, `grep`,
  and `jq` work on them directly. There is no command for reading a field that `job.json` already holds.

`status` and `session` are the exceptions, and the reason is the same for both: each reports something
`job.json` cannot hold. `status` reports `abandoned` for a job whose process is gone — a fact about the live
process table, so reading the file directly would say `running` forever. `session` scans the output when the
file has no id yet, which is the case for every job that is still running and for any that died before
recording one.

## Commands

| Command | |
| --- | --- |
| `run [--cwd DIR] [--timeout N] [--prompt-file PATH] [--parent JOB] -- CMD …` | Run a command. Prints the job id. |
| `status [JOB]` | Job state, exit code, session id. No argument lists everything. |
| `path JOB` | Print the job directory, which holds `job.json`, `prompt.txt`, `stdout.log`, `stderr.log`. |
| `session JOB` | Print the native session id, including while the job is still running. |
| `stop JOB` | Terminate the job's process group. |

`--prompt-file` is piped to the command's stdin and saved beside the log; `-` reads this process's stdin.
It is the only way to supply a prompt — there is no inline form, so a long prompt never has to survive shell
quoting.

`run` blocks. Background it the way you would any long command; there is no special mode for that, and
`stop` works either way.

That is a deliberate tradeoff. An earlier design watched the calling process and cancelled the job when it
exited, so a backgrounded job died with its caller. That watch keyed off whichever shell happened to spawn
xagent, which made it fire instantly in some shells and never in others, so it is gone. A backgrounded job
now outlives its caller. `--timeout` bounds it and `stop` ends it; nothing else will.

Statuses: `succeeded`, `failed`, `timed_out`, `cancelled`, `abandoned`, `corrupt`.

## Adding a provider

Nothing to configure. Write a reference file under `skills/xagent/references/` covering the recommended
invocation, the sandbox or permission controls, the flags worth knowing, how to resume, and the `jq` filter
for the final message. Then add it to the provider-selection step in [SKILL.md](skills/xagent/SKILL.md).

Check how the provider takes its prompt. Codex and Claude Code read stdin, so `--prompt-file` feeds them;
agy takes the prompt as the value of `--print`, so its jobs omit `--prompt-file` and the prompt is recorded
in `argv` instead of `prompt.txt`. Both work — the reference just has to say which.

If the provider can accept a caller-assigned session id, say so in the reference and recommend it over
recovery: xagent's recovery is a generic scan for the first root-level `session_id`, `thread_id`, or
`conversation_id` in the output, which suits today's CLIs but is inference, not a contract. Also check
whether the resume subcommand takes the same flags as the initial run — Codex's does not.

Avoid naming a reference `claude.md` or `agents.md`: on a case-insensitive filesystem those collide with
`CLAUDE.md` and `AGENTS.md`, and an agent working in this repo may load the file as project instructions.
Name them after the command plus `-cli`: `claude-cli.md`, `codex-cli.md`.

Keep references short. They will lag the CLI, and the skill already tells the agent to run `--help` when
something is missing — that hedge ages better than any schema.

## Operational notes

Transcripts can contain prompt injection, untrusted code, and secrets printed by a provider. Treat the job
store as sensitive: `umask 077` is recommended, and `XAGENT_HOME` can move it outside the repository. Do not
put credentials in prompts or provider arguments.

Logs are written raw, because escaping them would break `jq` on the structured stream that makes them useful.
Callers are responsible for treating the contents as data.

Nothing prunes the store; transcripts accumulate until you delete them.

## Tests

```sh
sh tests/test_smoke.sh
```
