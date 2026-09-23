# Ask Agent

Ask another coding agent for a second opinion or give it a task. Ask Agent runs the
provider's CLI exactly as your agent builds it, stops jobs that run too long, and keeps
every prompt, log, and session id so the work can be audited and followed up.

It is deliberately small: a skill that tells your agent how to drive each CLI, and a
single-file runner that records what ran. Build richer cross-agent workflows on top.

## Quickstart

Install the skill with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add mjewell/ask-agent --skill ask
```

Choose your agent in the installer, then ask naturally:

> /ask claude to review my changes

> /ask codex to implement this feature

Your agent asks you to approve the provider, model, and effort, then runs the task
and returns the answer. Choices you have already approved need no second approval.
Sessions are saved by default so you can ask follow-up questions.

Requires Node.js for the installer, macOS or Linux, Python 3.9+, and an installed,
authenticated provider CLI. The runner needs no Python packages.

## How it works

The [`ask` skill](skills/ask/SKILL.md) holds the instructions your agent follows, and a
reference per provider under [`skills/ask/references/`](skills/ask/references/). The
agent builds the provider command itself and passes it, unchanged, to the runner at
`skills/ask/scripts/ask-agent.py`. The skill documents the runner's commands;
`ask-agent.py --help` lists them too.

## What gets recorded

Jobs live in `~/.ask-agent/jobs/`, one store for every project, so a job started in
one directory stays listable and resumable from anywhere. Set `ASK_AGENT_HOME` to an
absolute path for a separate store.

Each job directory holds:

| File | Contents |
| --- | --- |
| `job.json` | The argv as given, working directory, timeout, timestamps, status, exit code, session id. |
| `prompt.txt` | The prompt, for every job. |
| `stdout.log`, `stderr.log` | The provider's output, verbatim. |
| `runner.lock` | Held by the runner while it lives, which is how a live job is told from a dead one. |

Files are private (`0600` inside `0700` directories). Jobs in one conversation share a
`session_id`, so filtering `status` output on it recovers the chain in order.

Logs are untrusted provider output and can contain secrets. Ask Agent provides no
sandbox; permissions belong to the provider or the container you run it in.

Nothing is deleted automatically. To remove jobs finished more than 30 days ago:

```sh
find ~/.ask-agent/jobs -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

A deleted job cannot be resumed through Ask Agent, though the provider's own session
survives; save any `session_id` you may want from `status` first.

## Adding a provider

Add a short reference under `skills/ask/references/` and link it from the skill. Cover
invocation, prompt input, permissions, resuming, and reading the result. If the CLI
takes its prompt as an argument rather than on stdin, use the `{prompt}` placeholder,
as the [agy reference](skills/ask/references/agy-cli.md) does.

Any command can run. Session discovery looks for a root-level `session_id`, `thread_id`,
or `conversation_id` in JSON lines. To support `answer` for a new output format, add a
reader to the runner and a fixture test; raw logs are always available. The reader
belongs in the runner because it decides whether a job has an answer at all: each
provider marks a failed turn differently.

## Tests

```sh
python3 tests/test_runner.py
```

## License

[MIT](LICENSE).
