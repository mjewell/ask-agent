# Claude Code CLI

**User-maintained, verified 2026-09-19.** Short by design — it will lag the CLI. Run `claude --help` when
you need a flag this file does not cover, or when something here does not work.

## Recommended invocation

```sh
python3 <skill-root>/scripts/ask-agent.py run \
  --cwd /repo --timeout 900 --prompt-file /tmp/task.md \
  -- claude --print --verbose --output-format stream-json \
     --permission-mode plan --permission-prompts none \
     --model claude-opus-5 --effort high
```

Piece by piece:

| Part | Why |
| --- | --- |
| `--print` | Non-interactive mode. Without it the CLI will hang under Ask Agent. |
| `--verbose --output-format stream-json` | Structured event stream. Needed for session recovery and for parsing the result. |
| `--permission-mode plan` | Permission posture. See the table below. |
| `--permission-prompts none` | Never block waiting for an approval nobody is there to give. |
| `--model` / `--effort` | Always explicit, so the job record says what ran. |

Claude Code reads the prompt from stdin under `--print`, so there is no trailing `-` to remember.

## Permission modes

| Mode | Effect | Use for |
| --- | --- | --- |
| `plan` | Reads and analyses, does not edit | Reviews, audits, analysis. The default. |
| `acceptEdits` | Applies file edits without asking | Implementation tasks. |
| `bypassPermissions` | No prompts at all | Only inside a container or VM. |

`auto`, `manual`, and `dontAsk` also exist; run `claude --help` if one of those fits better.

`--permission-prompts none` is separate from the mode: it decides who answers a prompt that does come up.
With `none`, anything that would prompt is denied automatically and the run does not block — which is what
you want unattended. The permission mode still governs everything else.

## Other flags worth knowing

| Flag | Effect |
| --- | --- |
| `--tools LIST` | Restricts the agent to exactly these tools, e.g. `Read,Glob,Grep` for a read-only review. |
| `--allowed-tools LIST` / `--disallowed-tools LIST` | Narrows tool access without replacing the whole set. |
| `--add-dir PATH` | Grants access to a directory outside the working directory. |
| `--restricted` | Extra-constrained mode. Conflicts with `bypassPermissions`. |
| `--resume SESSION_ID` | Continues an existing session. |
| `--session-id UUID` | Sets the session id up front instead of discovering it afterwards. |
| `--no-session-persistence` | Disables saving the session. Never use unless the user explicitly requests an ephemeral session. |
| `--output-format json` | One final JSON result instead of a stream, when you do not need the steps. |

Narrowing tools is often a better fit than loosening the permission mode. A review that only needs to read
files can take `--permission-mode plan --tools Read,Glob,Grep` and be tightly scoped without giving up
anything the task needs.

## Resuming

```sh
sid=$(python3 <skill-root>/scripts/ask-agent.py session JOB)
python3 <skill-root>/scripts/ask-agent.py run --cwd /repo --prompt-file /tmp/followup.md --parent JOB \
  -- claude --print --verbose --output-format stream-json --resume "$sid" \
     --permission-mode plan --permission-prompts none
```

The session id appears as `session_id` on the `system`/`init` event. `ask-agent session` recovers it, and `status` prints
it too. To pull it out yourself:

```sh
jq -r 'select(.type == "system" and .subtype == "init") | .session_id' "$dir/stdout.log"
```

**When deterministic resumption matters, prefer setting the id yourself.** Pass
`--session-id "$(uuidgen | tr A-Z a-z)"` on the first run and you know the id up front, with nothing to
recover. Ask Agent's recovery is a generic scan — it takes the first root-level `session_id`/`thread_id` it
sees in the output — which is right for today's CLIs but is inference, not a contract.

Re-pass the permission mode on a resume. A resumed session does not necessarily keep the original's posture,
and the recorded command should show what the continuation actually ran under.

## Reading the result

The log is one JSON object per line. The final assistant message:

```sh
jq -rs 'map(select(.type == "assistant")) | last | .message.content[] | select(.type == "text") | .text' \
  "$dir/stdout.log"
```

The `result` event carries the final text plus cost and duration:

```sh
jq -r 'select(.type == "result")' "$dir/stdout.log"
```
