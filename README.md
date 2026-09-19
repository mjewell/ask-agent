# XAgent (cross-agent)

XAgent is a local, provider-neutral launcher for coding-agent CLIs. It is deliberately a small execution and audit layer, not an agent-to-agent conversation protocol. The calling agent decides what to ask and whether to continue a conversation; XAgent preserves that choice reliably.

First choose the provider. When it is unspecified, recommend one based on the task and note when the other available harness offers a useful independent perspective; ask the user to confirm or change that choice. Then choose the delegation mechanism: prefer a native subagent for ordinary work targeting the current harness, and use XAgent for another provider, resumability, a complete local audit record, or explicit background/lifecycle control.

## What it guarantees

- Every job gets a durable ID and directory under `.xagent/jobs/` (or `$XAGENT_HOME`). `job.json` records the exact invocation, working directory, policy, timeout, timestamps, PID, exit state, parent job, prompt-file reference, and captured native session ID.
- `prompt.txt` contains the exact submitted prompt and is streamed to configured provider CLIs on stdin, avoiding shell quoting and OS argv-length limits. `events.jsonl` preserves stdout and stderr with timestamps. All three are mode `0600` within a mode `0700` job directory; never include secrets unless this local audit store is appropriate for them.
- `--resume JOB` maps to the provider's native resume mechanism. A resume is a new auditable bridge job linked to the earlier one, not an overwrite of history.
- Child CLIs run in their own process group. Timeout and `stop` terminate the complete group, rather than only the immediate CLI process. `--detach` makes concurrent jobs possible and, by default, watches the invoking parent PID and cancels the job if it exits. Use `--survive-parent` for intentionally independent work.
- New jobs require explicit `--model` and `--effort`; the calling agent chooses and passes them after inspecting the catalog. Resumes inherit their prior recorded choice unless explicitly overridden.
- Permission modes remain honest translations to native flags. They are guardrails, not a container boundary; use OS/container sandboxing for strong isolation.

## Examples

```sh
XAGENT="python3 /path/to/xagent/scripts/xagent.py"
$XAGENT doctor
$XAGENT run codex "Review this diff. Report findings only." --cwd /repo --mode read-only --model gpt-5.6-sol --effort medium --timeout 900 --detach
$XAGENT status
$XAGENT logs 20260101-120000-a1b2c3
$XAGENT run codex "Reconsider finding 2 with this additional context..." --cwd /repo --mode read-only --resume 20260101-120000-a1b2c3
$XAGENT stop 20260101-120000-a1b2c3
$XAGENT models claude
$XAGENT run claude "Threat-model this authentication flow." --cwd /repo --mode read-only --model claude-opus-5 --effort high
```

## Model choice

Each `providers/<provider>.json` carries a small, user-maintained catalog, stamped with `catalog_as_of`. `xagent models PROVIDER` presents a table of CLI choice/alias, model ID, input/output API-token cost, supported effort options, and purpose. The first catalog is based on official provider documentation and the local CLI picker as of 2026-09-19; update the JSON when your available models, pricing, or account changes. It is not an entitlement check: the runner accepts any provider-native model string. The catalog has no hidden recommendation metadata.

If a new task has no model/effort, the calling agent should run `xagent models`, compare the task’s complexity and cost sensitivity with the table, choose and pass the best clear option, and proceed. Ask the user only when the provider is unknown or the quality/cost tradeoff is materially ambiguous. The runner declines to launch until both are specified (or until `--model default --effort default` explicitly requests provider defaults). The selected model and effort are persisted in each job record for auditability.

## Native CLI passthrough

Use repeated `--provider-arg` (or `--passthrough`) for any underlying CLI argument XAgent does not own. Each occurrence is one literal argv item, so it is shell-safe and does not reinterpret quoting:

```sh
$XAGENT run codex "Review the diff." --cwd /repo --mode read-only --model gpt-5.6-sol --effort medium \
  --provider-arg=--profile --provider-arg ci --provider-arg=--add-dir --provider-arg ../shared
```

The adapter reserves only flags essential to its guarantees: provider output format, session resume, model/effort, directory, and permission/sandbox. It rejects attempts to override them, while the exact final command remains in the audit record. Update `reserved_args` and `passthrough_position` in a provider adapter only after reviewing that provider CLI’s current help.

## Fine-grained provider controls

Yes—both currently configured CLIs have narrower controls that compose with XAgent's coarse mode, provided they do not override the coarse policy itself. Pass them with `--provider-arg`:

| Provider | Compatible native controls | Notes |
| --- | --- | --- |
| Codex | `--add-dir PATH` | Makes an additional directory writable alongside the selected working directory. XAgent owns `--sandbox` and `-c/--config`, since either can defeat the recorded policy. |
| Claude Code | `--restricted`, `--add-dir PATH`, `--allowed-tools LIST`, `--disallowed-tools LIST`, `--tools LIST` | These can narrow tool/filesystem access further. `--restricted` conflicts with an unrestricted/bypass session, so use it only with a constrained XAgent mode. |

For example, a read-only Claude review that permits only file-reading tools can add `--provider-arg=--tools --provider-arg Read,Glob,Grep`. A container/VM remains necessary where directory confinement must be a hard security boundary.

## Permission model

| Bridge mode | Codex | Claude Code |
| --- | --- | --- |
| `read-only` | `--sandbox read-only` | `--permission-mode plan` |
| `workspace-write` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `unrestricted` | `--sandbox danger-full-access` | `--permission-mode bypassPermissions` |

The adapters do not fabricate a claim that `workspace-write` works as a security boundary for every host. For hard directory confinement, run the bridge itself in a container/VM or provider-supported sandbox, and pass only the intended working directory. Review the exact `command` in the private job record. A resumed provider session retains provider-native session settings; start a new job when the permission boundary must change.

## Add a provider

Add one JSON file to `providers/`. It defines the executable, argv templates for a new and resumed task, a regex that captures the provider's native session ID from output, model/effort argument templates, the maintained model table, passthrough placement/reserved flags, and a minimal mapping for the three XAgent policy names. Templates may use `{cwd}`, `{prompt}`, `{session_id}`, and fields defined in a policy. Start from the provider's current `--help`; do not copy broad generic agent advice into the adapter.

When adding a provider, extend the provider-selection guidance with the capabilities that actually distinguish it. Keep that guidance in this README rather than the runtime skill until the provider is installed and supported; the skill should only describe currently usable choices.

For a provider with no resumable session ID, omit `session_id_regex` and document that `--resume` is unavailable. A production expansion should add a provider-specific parser when a provider emits a more structured session event.

## Operational notes

The transcript can contain prompt injection, untrusted code suggestions, and secrets printed by a provider. Restrict the state directory (`umask 077` is recommended), put it outside the repository when needed, and treat it as sensitive audit data. Do not place credentials in prompts or provider arguments. Avoid `unrestricted` outside an external sandbox.

Parent-PID watching covers normal local process lifecycles, but PID reuse and remote/IDE session teardown need a host supervisor or cgroup for a strong guarantee. The job log makes either cancellation path visible.
