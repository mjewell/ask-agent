# agy CLI (Gemini)

**User-maintained, verified 2026-09-19.** Short by design — it will lag the CLI. Run `agy --help` when you
need a flag this file does not cover, or when something here does not work.

The binary is `agy`, not `gemini`.

## Recommended invocation

```sh
python3 <skill-root>/scripts/xagent.py run --cwd /repo --timeout 900 \
  -- agy --output-format stream-json --model gemini-3.8-flash-low --mode plan \
     --print 'the full prompt text goes here'
```

Piece by piece:

| Part | Why |
| --- | --- |
| `--print 'TEXT'` | Non-interactive mode **and** the prompt. It takes the prompt as its value, not as a separate argument. |
| `--output-format stream-json` | Structured event stream. Needed for session recovery and for parsing the result. |
| `--mode plan` | Execution mode. See the table below. |
| `--model` | Always explicit, so the job record says what ran. |

## The prompt goes in argv, not stdin

`--print` consumes the next token as its prompt, so **the prompt must be attached to the flag** and other
flags must come before it:

```sh
agy --output-format stream-json --print 'my prompt'   # correct
agy --print --output-format stream-json 'my prompt'   # --print eats "--output-format"
```

agy tells you when you get this wrong:

> `Error: --print took "--output-format" as its prompt, so the intended prompt was left as an argument and ignored.`

Because of that, **`--prompt-file` is not used for agy.** Omit it. XAgent pipes `/dev/null` to stdin, the
command gets a clean EOF rather than hanging, and the prompt is still captured in the job record — in the
`argv` field instead of `prompt.txt`. Use safe argument passing rather than interpolating
the prompt into shell code.

Two consequences worth knowing:

- A long prompt is subject to the OS argv size limit, and is visible to other users on the machine via `ps`.
  Prefer Codex or Claude Code for a prompt carrying anything sensitive.
- There is no `prompt.txt` in the job directory for an agy job. Read `argv` in `job.json` instead.

`--input-format stream-json` does read NDJSON from stdin, and accepts messages with an `"event": "user"`
field, but the message schema is not documented in `--help` and the obvious shapes produce an empty turn.
Treat it as unverified; use `--print` until it is documented.

## Execution modes

| Flag | Effect | Use for |
| --- | --- | --- |
| `--mode plan` | Plans without applying edits | Reviews, audits, analysis. The default choice. |
| `--mode accept-edits` | Applies edits without prompting | Implementation tasks. |
| `--dangerously-skip-permissions` | Auto-approves every tool request | Only inside a container or VM. |

`--sandbox` is a separate boolean that enables terminal restrictions, and composes with a mode. Without any
of these the session runs in `request-review`, which waits for an approval nobody is there to give — so
always pass a mode under xagent.


## Other flags worth knowing

| Flag | Effect |
| --- | --- |
| `--add-dir PATH` | Adds a directory to the workspace. Repeatable. |
| `--effort low\|medium\|high` | Reasoning effort. Narrower than other providers — three levels only. |
| `--conversation ID` | Resumes a previous conversation. |
| `-c`, `--continue` | Continues the most recent conversation. Avoid under xagent; name the id explicitly. |
| `--json-schema` | Enforces a structured final result. |
| `--disable-slash-commands` | Stops slash-command and skill expansion in print mode. |
| `--print-timeout` | agy's own time limit. Leave it at 0 and let xagent's `--timeout` own this. |

## Models and effort

`agy models` lists what the account can actually use, live — prefer it over any table here. Note that most
model ids already encode an effort tier (`gemini-3.8-flash-high`, `-medium`, `-low`) *and* `--effort` exists
separately, so pick the tier in the model id and leave `--effort` alone unless you have a reason.

The catalog also exposes non-Gemini models. Choosing one of those makes this a poor cross-provider check —
if the point is an independent second opinion, that comes from a different lab, not just a different CLI.

## Resuming

```sh
sid=$(python3 <skill-root>/scripts/xagent.py session JOB)
python3 <skill-root>/scripts/xagent.py run --cwd /repo --parent JOB \
  -- agy --output-format stream-json --model gemini-3.8-flash-low --mode plan \
     --conversation "$sid" --print 'the follow-up prompt'
```

agy calls it a conversation id. It appears as a root-level `conversation_id` on the `init` event, which
`xagent session` recovers; `status` prints it too. To pull it out yourself:

```sh
jq -r 'select(.event == "init") | .conversation_id' "$dir/stdout.log"
```

Re-pass the mode on a resume, the same as for the initial run. agy has no flag for assigning a conversation
id up front, so recovery is the only route to one.

## Reading the result

agy emits a single `result` event carrying the complete final response, so no aggregation is needed:

```sh
jq -r 'select(.event == "result") | .result.response' "$dir/stdout.log"
```

That event also carries status, turn count, duration, and token usage:

```sh
jq -r 'select(.event == "result") | .result | {status, num_turns, duration_seconds, usage}' "$dir/stdout.log"
```

A failed turn still emits `result` with `"status": "ERROR"` and an `error` field, so check `status` rather
than assuming a non-empty `response`.
