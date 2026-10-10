---
when: Adding or changing a rule, an instruction file (AGENTS.md, CLAUDE.md) or a context doc
tier: required
---
# Instruction files and context docs

## Where a rule goes

General rules live in mjewell/agent-config: edit them there when that repo is available, otherwise give me the exact text to add. A rule that applies from the first turn or to most tasks goes inline in `context/agents.md`. One needed only for some kind of task goes in a doc set, `context/<name>.md` (or a `context/<name>/` folder whose `index.md` links to the rest, if it needs several files), marked `tier: required` unless it depends on a repo's stack or kind of project, where a repo might want something different.

Project-specific rules go in the repo's AGENTS.md, outside the context-packs blocks, or in its context docs, and cover only what's structurally unique to that project — its architecture, commands, and environment quirks such as a test setup that can't run — never general working rules. Instruction files state the current rule or fact, never the history of what changed.

## Project context docs

Knowledge that applies to only some work in a project — one area of the code, one kind of task — goes in its own doc in `docs/agents/project/`, not inline in AGENTS.md; AGENTS.md keeps what applies to every task there. Start each doc with front matter saying when to read it:

```markdown
---
when: Editing `src/billing/**`
---
```

`when` names what the agent will be doing or touching, as a path glob or a kind of task, so a row's relevance shows before its doc is read. A doc is a single `<name>.md`, or a `<name>/` folder whose `index.md` links to the rest. Keep it flat: each level is another read an agent can skip, so nest only when an area has enough docs that one entry serves better than several.

The repo's `project` context pack lists these docs in AGENTS.md, generated from their `when` lines. After adding a doc or changing its `when`, resync so the table matches, and the first time, install the pack:

```bash
npx github:mjewell/context-packs . add project . --path docs/agents/project  # first doc only
npx github:mjewell/context-packs .
```
