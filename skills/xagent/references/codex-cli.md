# Codex CLI

**User-maintained, verified 2026-09-19.** Short by design — it will lag the CLI. Run `codex exec --help`
when you need a flag this file does not cover, or when something here does not work.

## Recommended invocation

```sh
python3 <skill-root>/scripts/xagent.py run \
  --cwd /repo --timeout 900 --prompt-file /tmp/task.md \
  -- codex exec --json -s read-only -C /repo --model gpt-5.6-sol -c model_reasoning_effort="medium" -
```

Piece by piece:

| Part | Why |
| --- | --- |
| `exec` | Non-interactive mode. Interactive mode will hang under xagent. |
| `--json` | Structured event stream. Needed for session recovery and for parsing the result. |
| `-s read-only` | Sandbox. See the table below; start read-only and widen only when the task writes. |
| `-C /repo` | Working directory for the agent. Match it to xagent's `--cwd`. |
| `--model` | Always explicit, so the job record says what ran. |
| `-c model_reasoning_effort="…"` | Effort. Codex sets this through config rather than a flag. |
| `-` (trailing) | Read the prompt from stdin, explicitly. |

On the trailing `-`: Codex reads stdin whenever no `[PROMPT]` argument is given, so `-` is not strictly
required. Pass it anyway — it makes the recorded command say where the prompt came from. Note that if you
pass *both* a prompt argument and stdin, Codex appends stdin as a `<stdin>` block rather than ignoring it.

## Sandbox modes

| Mode | Effect | Use for |
| --- | --- | --- |
| `read-only` | Reads the filesystem, no writes, no network | Reviews, audits, analysis. The default. |
| `workspace-write` | Writes within the working directory | Implementation tasks. |
| `danger-full-access` | No restriction | Only inside a container or VM. |

## Other flags worth knowing

| Flag | Effect |
| --- | --- |
| `--add-dir PATH` | Makes an extra directory writable alongside the working directory. Composes with `workspace-write`. |
| `-c KEY="VALUE"` | Any config setting. This is also how effort is set; repeat for more. |
| `-o FILE` | Writes just the final agent message to `FILE`. Often easier than parsing the log. |
| `--output-schema FILE` | JSON Schema for the final response, when you need a specific shape back. |
| `-p, --profile NAME` | Layers `$CODEX_HOME/<name>.config.toml` over the user's base config. |
| `--skip-git-repo-check` | Required when the working directory is not a Git repository. |
| `exec resume THREAD_ID` | Continues an existing thread. Takes `-c` but **not** `-s`. |

## Resuming

```sh
sid=$(python3 <skill-root>/scripts/xagent.py session JOB)
python3 <skill-root>/scripts/xagent.py run --cwd /repo --prompt-file /tmp/followup.md --parent JOB \
  -- codex exec resume "$sid" --json -c sandbox_mode="read-only" -
```

Codex calls this a thread id. `xagent session` recovers it, and `status` prints it too.
To pull it out yourself:

```sh
jq -r 'select(.type == "thread.started") | .thread_id' "$dir/stdout.log"
```

Codex has no flag for assigning a thread id up front, so recovery is the only route to one here — unlike
Claude Code, where `--session-id` can be set on the first run.

**`resume` does not accept `-s/--sandbox`** — it rejects the flag outright. Re-pin the sandbox with
`-c sandbox_mode="…"` instead. Do re-pin it: a resumed thread does not necessarily keep the original
session's settings, and the recorded command should show what the continuation actually ran under.

## Reading the result

Simplest option: add `-o /tmp/last-message.txt` to the command and read that file afterwards. Codex writes
the final agent message there directly, with no parsing.

Otherwise, the log is one JSON object per line. The final assistant message:

```sh
jq -rs 'map(select(.item.type == "agent_message")) | last | .item.text' "$dir/stdout.log"
```

Everything the agent did, in order:

```sh
jq -r 'select(.item.type) | "\(.item.type): \(.item.text // .item.command // "")"' "$dir/stdout.log"
```
