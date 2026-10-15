---
when: Adding or changing a rule, an instruction file (AGENTS.md, CLAUDE.md) or a context doc
---
# Instruction files and context docs

## Where a rule goes

General rules live in mjewell/agent-config: edit them there when that repo is available, otherwise give me the exact text to add. A rule that applies from the first turn or to most tasks goes inline in `packs/core/pack.md`. One needed only for some kind of task goes in a doc, `packs/core/<name>.md`, which every repo gets. One that depends on a repo's stack or kind of project, where a repo might want something different, goes in a pack of its own instead, which each repo installs only if it applies: a `packs/<name>/` folder whose `pack.md` holds its rules, with front matter saying when to read it, beside any docs it needs.

Project-specific rules go in the repo's AGENTS.md, outside the context-packs block, or in its context docs, and cover only what's structurally unique to that project — its architecture, commands, and environment quirks such as a test setup that can't run — never general working rules. Instruction files state the current rule or fact, never the history of what changed.

## Project context docs

Knowledge that applies to only some work in a project — one area of the code, one kind of task — goes in its own doc in the repo's `context-packs/` folder, not inline in AGENTS.md; AGENTS.md keeps what applies to every task there. Start each doc with front matter saying when to read it:

```markdown
---
when: Editing `src/billing/**`
---
```

`when` names what the agent will be doing or touching, as a path glob or a kind of task, so a row's relevance shows before its doc is read. A folder of docs needs no index: each doc gets its own row. Give a folder a `pack.md`, with the same front matter, only when an area has enough docs that one row serves better than several, since the folder then gets one row pointing at a generated index of its docs, and each such level is another read an agent can skip.

The sync lists these docs in AGENTS.md, generated from their `when` lines. After adding a doc or changing its `when`, resync so the table matches:

```bash
npx context-packs
```
