---
when: Adding or changing a rule, an instruction file (AGENTS.md, CLAUDE.md) or a context doc
tier: required
---
# Instruction files and context docs

## Where a rule goes

General rules live in mjewell/agent-config: edit them there when that repo is available, otherwise give me the exact text to add. A rule that applies from the first turn or to most tasks goes inline in `context/agents.md`. One needed only for some kind of task goes in a doc set, `context/<name>/`, marked `tier: required` unless it depends on a repo's stack or kind of project, where a repo might want something different.

Project-specific rules go in the repo's AGENTS.md, outside the agent-config block, or in its context docs, and cover only what's structurally unique to that project — its architecture, commands, and environment quirks such as a test setup that can't run — never general working rules. Instruction files state the current rule or fact, never the history of what changed.

## Project context docs

Knowledge that applies to only some work in a project — one area of the code, one kind of task — goes in its own file under `docs/agents/`, not inline in AGENTS.md; AGENTS.md keeps what applies to every task there. List each doc in a `## Project context` table in AGENTS.md, outside the agent-config block, and create the section along with the first doc:

| When | Read |
|---|---|
| Editing `src/billing/**` | `docs/agents/billing.md` |

`When` names what the agent will be doing or touching, as a path glob or a kind of task, so a row's relevance shows before its doc is read.

Every doc must be reachable from the table, directly or through an index doc that a row points to; an index doc uses the same table. Keep it flat: each level is another read an agent can skip, so nest only when an area has enough docs that one row serves better than several.
