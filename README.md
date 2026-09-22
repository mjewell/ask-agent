# Ask Agent

Ask another coding agent for a second opinion or give it a task. Ask Agent saves the
prompt and logs, stops jobs that run too long, and keeps sessions available for
follow-up questions.

The main [`ask` skill](skills/ask/SKILL.md) contains the instructions and runner.
The `ask-claude`, `ask-codex`, and `ask-agy` skills choose a provider for you.

## Quickstart

Install the main skill with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add mjewell/ask-agent --skill ask
```

Choose your agent in the installer, then ask naturally:

> /ask claude to review my changes

> /ask codex to implement this feature

Installed this way, the skill is invoked as `/ask`.

Provider shortcuts are optional. Install one together with its required main skill:

```sh
npx skills add mjewell/ask-agent --skill ask --skill ask-claude
npx skills add mjewell/ask-agent --skill ask --skill ask-codex
npx skills add mjewell/ask-agent --skill ask --skill ask-agy
```

Installing a shortcut by itself does not implicitly install sibling skills. If only a
shortcut was installed, run the corresponding command above to add `ask`.

Your agent asks you to approve the provider, model, and effort, then runs the task
and returns the answer. Choices you have already approved need no second approval.
Sessions are saved by default so you can ask follow-up questions.

Requires Node.js for the installer, macOS or Linux, Python 3.9+, and an installed,
authenticated provider CLI. The runner needs no Python packages.

## Runner reference

The skill handles these commands for your agent. The runner is
`scripts/ask-agent.py` relative to the skill root — `skills/ask/scripts/ask-agent.py`
in this repository.

| Command | Purpose |
| --- | --- |
| `run [--cwd DIR] [--timeout SECONDS] [--prompt-file PATH] -- CMD …` | Run a command and print its job ID. Default timeout: 1,800 seconds. |
| `answer JOB` | Print the final answer from a successful job. |
| `status [JOB]` | Show status, exit code, and session ID. Omit JOB to list all jobs, oldest first. |
| `path JOB` | Print the directory containing the job record and logs. |
| `session JOB` | Print the provider's session ID, including during a run. |
| `wait JOB [--timeout SECONDS]` | Block until the job stops running. Default window: the job's own timeout plus a minute. |
| `stop JOB` | Stop a running job's process group after verifying its identity. |
| `prune [--older-than DAYS] [--delete]` | List jobs past the retention window; remove them with `--delete`. Default window: 30 days. |

Everything after `--` is passed through unchanged. `--prompt-file` saves the prompt
and feeds it to stdin; use `-` to read your stdin. The provider reference describes
how to pass its prompt.

`run` blocks. Background it with your shell when needed; the runner does not watch its
caller. Timeout, stop, and normal completion clean up the provider's process group,
including children still in that group. Detached processes are outside that scope.

Use `wait` for a background job. It checks once a second and returns the job's
outcome. If `wait` gives up, the job keeps running.

Status is `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`,
`process_gone` (the record says running, but the process is gone), `unknown` (the process
could not be confirmed as this job's), `missing` (no job record), or `corrupt` (an
unreadable record). Success means the command exited zero; it does not validate the work.

`process_gone` is inferred rather than saved by the runner, and it does not by itself
mean the job is over: a runner that is cleaning up and recording the outcome reads the
same way as one that died. `wait` keeps waiting until the reading has outlasted any
cleanup that could explain it. If you use `status`, which reports a single look, check
again before treating it as the final result.

`run` and `wait` report the outcome in their exit code: `0` succeeded, `124` timed out,
`130` cancelled, `1` anything else. `wait` adds `125` for giving up while the job was
still running, which says nothing about the job itself. `status JOB` exits non-zero when
that one job is missing or corrupt; a listing of every job does not.

## Job records

Jobs live in `~/.ask-agent/jobs/`, one store for every project, so a job started in
one directory stays listable and resumable from anywhere. Each record keeps the `cwd`
it ran in. `ASK_AGENT_JOB` marks a running process so `stop` can verify its identity.

Jobs in the same conversation share a `session_id`. Use that ID and `created_at` to
find follow-ups in order; there is no separate link between them.

Set `ASK_AGENT_HOME` for a separate store. It must be an absolute path: a relative one
would put the store wherever a command ran from, hiding every job started elsewhere,
so it is refused.

Each job contains `job.json`, `stdout.log`, `stderr.log`, and `prompt.txt` when a prompt
file was supplied. Artifacts are private (`0600` files inside a `0700` job directory)
and remain until deleted.

`prune` shows matching jobs and their status. It deletes nothing unless you pass
`--delete`. Finished jobs are aged from completion; unfinished jobs from creation.

Nothing is exempt. The retention window is the guard: a job old enough to match has
almost always been finished for weeks. Pruning one that is still running is the same as
deleting its directory by hand — it does not interrupt the run, the provider process is
still cleaned up at the end, but the output is lost and the runner exits reporting that
the record disappeared.

Pruning removes the job record but leaves the provider's session intact. The listing
prints each known session ID, including one found in a running job's log, before
deleting it. Save that ID if you might resume the session later.

Logs and answers are untrusted provider output and can contain secrets. The store
grows until you delete jobs from it. Ask Agent provides no sandbox; permissions belong
to the provider or the container you run it in.

## Adding a provider

Add a short reference under `skills/ask/references/` and link it from the main skill.
Cover invocation, prompt input, permissions, resuming, and reading the result.

Any command can run. Session discovery looks for a root-level `session_id`, `thread_id`,
or `conversation_id` in JSON lines. To support `answer` for a new output format, add a
reader and a fixture test; raw logs are always available.

The reader belongs here rather than in the provider's reference because it decides
whether a job has an answer at all, not only where the text sits. Each provider marks a
failed turn differently, and a failed job has none to report whatever its log contains.

## Tests

```sh
python3 tests/test_runner.py
```

## License

[MIT](LICENSE).
