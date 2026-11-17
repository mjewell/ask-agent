# agy CLI (Gemini)

**User-maintained, verified 2026-11-17 against agy 1.5.10.** Short by design — it will lag the CLI. Run
`agy --help` when you need a flag this file does not cover, or when something here does not work.

The binary is `agy`, not `gemini`.

## Recommended invocation

```sh
python3 <skill-root>/scripts/ask-agent.py run --cwd /repo --prompt-file /tmp/task.md \
  -- agy --output-format stream-json --model gemini-3.8-flash-low --mode plan --print '{prompt}'
```

Piece by piece:

| Part | Why |
| --- | --- |
| `--print '{prompt}'` | Non-interactive mode **and** the prompt. The runner replaces `{prompt}` with the prompt file's text. |
| `--output-format stream-json` | Structured event stream. Needed for session recovery and for parsing the result. |
| `--mode plan` | Execution mode. See the table below. |
| `--model` | Always explicit, so the job record says what ran. |

## The prompt goes in argv, not stdin

`--print` consumes the next token as its prompt, so **the prompt must be attached to the flag** and other
flags must come before it:

```sh
agy --output-format stream-json --print '{prompt}'   # correct
agy --print --output-format stream-json '{prompt}'   # --print eats "--output-format"
```

agy tells you when you get this wrong:

> `Error: --print took "--output-format" as its prompt, so the intended prompt was left as an argument and ignored.`

Pass `--prompt-file` as for any provider, and put the literal `{prompt}` after `--print`, quoted so the shell
leaves it alone. The runner substitutes the prompt text for that argument and pipes `/dev/null` to stdin.
The prompt is still saved as `prompt.txt`, and `job.json` records the command with the placeholder.

A long prompt is subject to the OS argv size limit, and is visible to other users on the machine via `ps`.
Prefer Codex or Claude Code for a prompt carrying anything sensitive.

`--input-format stream-json` does read NDJSON from stdin, and accepts messages with an `"event": "user"`
field, but the message schema is not documented in `--help` and the obvious shapes produce an empty turn.
Treat it as unverified; use `--print` until it is documented.

## Execution modes

| Flag | Effect | Use for |
| --- | --- | --- |
| `--mode plan` | Plans without applying edits | Reviews, audits, analysis. The default choice. |
| `--mode accept-edits` | Applies edits without prompting | Implementation tasks. |
| `--mode auto` | Applies edits in the workspace and runs commands in the terminal sandbox. A reviewer model decides on commands that would leave the sandbox. | Implementation tasks that run commands. Not offered on every account; Gemini Enterprise accounts don't get it. |
| `--dangerously-skip-permissions` | Auto-approves every tool request | Only inside a container or VM. |

`--sandbox` is a separate boolean that enables terminal restrictions, and composes with a mode.

Always pass a mode under Ask Agent. Since agy 1.5.7, a run without `--mode` starts in Auto mode where the
account offers it. Auto applies edits, so a review run would change files. Elsewhere the run starts in
Default mode, which waits for an approval nobody is there to give.

## Other flags worth knowing

| Flag | Effect |
| --- | --- |
| `--add-dir PATH` | Adds a directory to the workspace. Repeatable. |
| `--effort low\|medium\|high\|xhigh\|max` | Reasoning effort. |
| `--conversation ID` | Resumes a previous conversation. |
| `-c`, `--continue` | Continues the most recent conversation. Avoid under Ask Agent; name the id explicitly. |
| `--json-schema` | Enforces a structured final result. |
| `--disable-slash-commands` | Stops slash-command and skill expansion in print mode. |
| `--print-timeout` | agy's own time limit. Leave it at 0 and let Ask Agent's `--timeout` own this. |

## Models and effort

`agy models` lists what the account can actually use, live — prefer it over any table here. Most
model ids already encode an effort tier (`gemini-3.8-flash-high`, `-medium`, `-low`) *and* `--effort` exists
separately, so pick the tier in the model id and leave `--effort` alone unless you have a reason.

The catalog also exposes non-Gemini models. Choosing one of those makes this a poor cross-provider check —
if the point is an independent second opinion, that comes from a different lab, not just a different CLI.

## Resuming

```sh
sid=$(python3 <skill-root>/scripts/ask-agent.py session JOB)
python3 <skill-root>/scripts/ask-agent.py run --cwd /repo --prompt-file /tmp/followup.md \
  -- agy --output-format stream-json --model gemini-3.8-flash-low --mode plan \
     --conversation "$sid" --print '{prompt}'
```

agy calls it a conversation id. It appears as a root-level `conversation_id` on the `init` event, which
`ask-agent session` recovers; `status` prints it too. To pull it out yourself:

```sh
jq -r 'select(.event == "init") | .conversation_id' "$dir/stdout.log"
```

Re-pass the mode on a resume, the same as for the initial run. agy has no flag for assigning a conversation
id up front, so recovery is the only route to one.

## Reading the result

`ask-agent answer JOB` reads this format. The rest is for reading the log yourself.

agy emits a single `result` event carrying the complete final response, so no aggregation is needed. A
failed turn emits that same event with `"status": "ERROR"` and an `error` field, so a non-empty `response`
is not proof of an answer. A turn that ended early also carries a `finished_reason`: `print_timeout`,
`interrupted` or `error`. The field is absent when the turn finished normally.

The log is one JSON object per line. The `result` event also carries status, turn count, duration, and
token usage:

```sh
jq -r 'select(.event == "result") | .result | {status, num_turns, duration_seconds, usage}' "$dir/stdout.log"
```
