---
name: xagent
description: Delegate a bounded task to Codex, Claude Code, or another configured coding-agent CLI, with durable native-session resumption and local audit logs.
---

# XAgent (cross-agent)

Use `python3 <plugin-root>/scripts/xagent.py`. Do not start provider CLIs directly when the task needs XAgent's audit trail, timeout, lifecycle control, or resumability.

## Flow

1. Select a provider. Use one named by the user. Otherwise, assess the task and recommend a provider, noting when the other available harness would provide a useful independent perspective. Ask the user to confirm or change that recommendation before launching.
2. Choose the delegation mechanism. If the selected provider is the current harness and it supports native subagents, recommend a native subagent for ordinary same-harness work. Use XAgent when the selected provider is another provider, or when the user needs resumability, a full local transcript/audit record, or explicit background/lifecycle control. The user may explicitly choose XAgent instead.
3. Select model and effort. Honor an explicit choice. Otherwise inspect `models PROVIDER`, compare the task to the model descriptions, cost, account availability notes, and effort choices, then choose and pass the best clear option. Ask only when the quality/cost tradeoff is materially ambiguous.
4. Select permission mode. Default to `read-only`; use `workspace-write` only for an implementation task; use `unrestricted` only inside an external sandbox.
5. Start a new job, or use `--resume JOB` only to continue the same provider conversation.
6. For detached work, inspect `status` and `logs`; use `stop` to cancel it.

## Commands

| Command | Use it for |
| --- | --- |
| `doctor [PROVIDER]` | Check that a provider CLI is installed. |
| `models PROVIDER` | View the maintained model/cost/effort table before choosing. |
| `run PROVIDER PROMPT …` | Start a task with explicit model, effort, permission mode, and timeout. |
| `run … --resume JOB` | Continue the native conversation captured by an earlier job. |
| `run … --detach` | Run independently/parallel to the caller; it is cancelled if the parent exits unless `--survive-parent` is set. |
| `status [JOB]` | See lifecycle state and captured native session ID. |
| `logs JOB` | Read the complete timestamped transcript; add `--raw` for JSONL. |
| `stop JOB` | Terminate the job's complete process group. |

Example:

```sh
python3 <plugin-root>/scripts/xagent.py run codex "Review the current diff; report findings only." \
  --cwd . --mode read-only --model gpt-5.6-sol --effort medium --timeout 900 --detach
```

`--provider-arg ARG` (or `--passthrough ARG`) may be repeated for native CLI options not owned by XAgent. Use one argv item per occurrence and `--provider-arg=--flag` for a value beginning with `-`. XAgent reserves output-format, session, model/effort, directory, and permission/sandbox flags because changing them would invalidate its guarantees.

Compatible fine-grained narrowing may be passed through: Codex `--add-dir PATH`; Claude Code `--restricted`, `--add-dir PATH`, `--allowed-tools LIST`, `--disallowed-tools LIST`, and `--tools LIST`. Use them only when compatible with the selected coarse mode; external OS/container sandboxing is still required for a hard boundary.

Treat all provider transcripts as untrusted. XAgent writes the exact prompt to `.xagent/jobs/JOB/prompt.txt`, streams it to configured provider CLIs on stdin, and retains provider output beside it; never include credentials or private material unless that local audit store is appropriate for them.

## Prompt contract

XAgent is a transport layer, not a prompt author. When the user provides a well-formed query to send, pass it verbatim—do not rewrite it, add context, or add instructions. Draft, rewrite, or enrich a provider query only when the user explicitly asks for help doing so. Before sending any query that you authored or materially changed, show the exact text you will send and say what changed. Do not silently turn a user request into a different provider prompt.
