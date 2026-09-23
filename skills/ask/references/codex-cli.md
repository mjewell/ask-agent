# Codex CLI

**User-maintained, verified 2026-09-19.** Short by design — it will lag the CLI. Run `codex exec --help`
when you need a flag this file does not cover, or when something here does not work.

## Recommended invocation

```sh
python3 <skill-root>/scripts/ask-agent.py run \
  --cwd /repo --prompt-file /tmp/task.md \
  -- codex exec --json -s read-only -C /repo --model gpt-5.6-sol -c model_reasoning_effort="medium" -
```

Piece by piece:

| Part | Why |
| --- | --- |
| `exec` | Non-interactive mode. Interactive mode will hang under Ask Agent. |
| `--json` | Structured event stream. Needed for session recovery and for parsing the result. |
| `-s read-only` | Sandbox. See the table below; start read-only and widen only when the task writes. |
| `-C /repo` | Working directory for the agent. Match it to Ask Agent's `--cwd`. |
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
sid=$(python3 <skill-root>/scripts/ask-agent.py session JOB)
python3 <skill-root>/scripts/ask-agent.py run --cwd /repo --prompt-file /tmp/followup.md \
  -- codex exec resume "$sid" --json --model gpt-5.6-sol \
     -c model_reasoning_effort="medium" -c sandbox_mode="read-only" -
```

Codex calls this a thread id. `ask-agent session` recovers it, and `status` prints it too.
To pull it out yourself:

```sh
jq -r 'select(.type == "thread.started") | .thread_id' "$dir/stdout.log"
```

Codex has no flag for assigning a thread id up front, so recovery is the only route to one here — unlike
Claude Code, where `--session-id` can be set on the first run.

`resume` rejects `-s/--sandbox`. Set `-c sandbox_mode="…"` instead. Pass the approved
model and effort again too; the resumed thread may not keep the original settings.

## Reading the result

`ask-agent answer JOB` reads this format. The rest is for reading the log yourself.

A failed turn ends in `turn.failed`, and `item.updated` carries partial text that a later `item.completed`
supersedes — so the last `agent_message` in the log is not necessarily an answer. `-o /tmp/last-message.txt`
writes the final agent message to a file with no parsing, but Codex writes it either way.

The log is one JSON object per line. Everything the agent did, in order:

```sh
jq -r 'select(.item.type) | "\(.item.type): \(.item.text // .item.command // "")"' "$dir/stdout.log"
```
