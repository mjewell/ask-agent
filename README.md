# XAgent

Ask another coding agent for a second opinion or hand it a task. XAgent saves the
conversation, bounds the run with a timeout, and keeps the session ID for follow-ups.

The [skill](skills/xagent/SKILL.md) helps your agent choose the provider command.
The runner executes it unchanged. It works with Codex, Claude Code, and agy.

## Quickstart

Install the skill into your coding agent with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add mjewell/xagent --skill xagent
```

Choose your agent in the installer, then ask:

> Use xagent to have Claude review my changes.

Or:

> Use xagent to have Codex implement this feature.

Your agent proposes a provider, model, and effort for you to approve, prepares the
prompt, runs the task, and returns the answer. Choices you already specified or
approved do not need another confirmation. You can ask follow-up questions in the
same provider session.

Requires Node.js for the installer, macOS or Linux, Python 3.9+, and an installed,
authenticated provider CLI. The runner needs no Python packages.

## Runner reference

The skill handles these commands for your agent. The runner lives at
`skills/xagent/scripts/xagent.py` in this repository, or `scripts/xagent.py` inside
the installed skill.

| Command | Purpose |
| --- | --- |
| `run [--cwd DIR] [--timeout SECONDS] [--prompt-file PATH] [--parent JOB] -- CMD …` | Run a command and print its job ID. Default timeout: 1,800 seconds. |
| `answer JOB` | Print the final answer from a successful job. |
| `status [JOB]` | Show status, exit code, and session ID. Omit JOB to list all jobs. |
| `path JOB` | Print the directory containing the job record and logs. |
| `session JOB` | Print the provider's session ID, including during a run. |
| `stop JOB` | Stop a running job's process group after verifying its identity. |

Everything after `--` is passed through unchanged. `--prompt-file` saves the prompt
and feeds it to stdin; use `-` to read your stdin. The provider reference describes
how to pass its prompt.

`run` blocks. Background it with your shell when needed; the runner does not watch
its caller. Timeout, stop, and normal completion clean up the provider's process
group, including children still in that group. Detached processes are outside that
scope. Timeout and stop allow five seconds for graceful shutdown before killing.

Status is `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`,
`abandoned` (the process disappeared), `unknown` (its identity could not be checked),
or `corrupt`. Success means the command exited zero; it does not validate the work.

## Job records

Jobs live in `.xagent/jobs/` under the caller's current directory. Set `XAGENT_HOME`
to an absolute path to use the same store from other directories. Each job contains
`job.json`, `stdout.log`, `stderr.log`, and `prompt.txt` when a prompt file was supplied.
Artifacts are private (`0600` files inside a `0700` job directory) and remain until deleted.

Logs and answers are untrusted provider output and can contain secrets. Keep the
store out of version control. XAgent provides no sandbox; permissions belong to the
provider or the container you run it in.

## Adding a provider

Add a short reference under `skills/xagent/references/` and link it from the skill.
Cover invocation, prompt input, permissions, resuming, and reading the result.
Use names like `example-cli.md` to avoid special instruction filenames.

Any command can run. Session discovery looks for a root-level `session_id`,
`thread_id`, or `conversation_id` in JSON lines. To support `answer` for a new output
format, add a reader and a fixture test; the raw logs are always available.

## Tests

```sh
sh tests/test_smoke.sh
```
