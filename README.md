# Ask Agent

Ask another coding agent for a second opinion or hand it a task. Ask Agent saves the
conversation, bounds the run with a timeout, and keeps the provider session available
for follow-ups.

The main [`ask` skill](skills/ask/SKILL.md) owns the shared policy, provider references,
and runner. Thin `ask-claude`, `ask-codex`, and `ask-agy` skills preselect a provider
without duplicating that implementation.

## Quickstart

Install the main skill with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add mjewell/ask-agent --skill ask
```

Choose your agent in the installer, then ask naturally:

> /ask claude to review my changes

> /ask codex to implement this feature

Standalone skill installs normally expose `/ask`. Plugin hosts may namespace commands;
use the invocation name shown by the host after installation.

Provider shortcuts are optional. Install one together with its required main skill:

```sh
npx skills add mjewell/ask-agent --skill ask --skill ask-claude
npx skills add mjewell/ask-agent --skill ask --skill ask-codex
npx skills add mjewell/ask-agent --skill ask --skill ask-agy
```

Installing a shortcut by itself does not implicitly install sibling skills. If only a
shortcut was installed, run the corresponding command above to add `ask`.

Your agent proposes a provider, model, and effort for approval, prepares the prompt,
runs the task with network access, and returns the answer. Choices already specified
or approved do not need another confirmation. Provider sessions remain persistent by
default so you can ask follow-up questions later.

Requires Node.js for the installer, macOS or Linux, Python 3.9+, and an installed,
authenticated provider CLI. The runner needs no Python packages.

## Runner reference

The skill handles these commands for your agent. The runner lives at
`skills/ask/scripts/ask-agent.py` in this repository, or `scripts/ask-agent.py` inside
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

`run` blocks. Background it with your shell when needed; the runner does not watch its
caller. Timeout, stop, and normal completion clean up the provider's process group,
including children still in that group. Detached processes are outside that scope.

Status is `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`,
`abandoned` (the process disappeared), `unknown` (its identity could not be checked),
or `corrupt`. Success means the command exited zero; it does not validate the work.

## Job records

Jobs live in `.ask-agent/jobs/` under the caller's current directory. Set
`ASK_AGENT_HOME` to an absolute path to use the same store from other directories.
`ASK_AGENT_JOB` marks a running process so `stop` can verify its identity.

Each job contains `job.json`, `stdout.log`, `stderr.log`, and `prompt.txt` when a prompt
file was supplied. Artifacts are private (`0600` files inside a `0700` job directory)
and remain until deleted.

Logs and answers are untrusted provider output and can contain secrets. Keep the store
out of version control. Ask Agent provides no sandbox; permissions belong to the
provider or the container you run it in.

## Adding a provider

Add a short reference under `skills/ask/references/` and link it from the main skill.
Cover invocation, prompt input, permissions, resuming, and reading the result.

Any command can run. Session discovery looks for a root-level `session_id`, `thread_id`,
or `conversation_id` in JSON lines. To support `answer` for a new output format, add a
reader and a fixture test; raw logs are always available.

## Tests

```sh
sh tests/test_smoke.sh
```
