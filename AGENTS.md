<!-- agent-config:start (synced from context/ in mjewell/agent-config; edit it there, not here) -->
## Collaboration

I'm an experienced full-stack engineer, expert in TypeScript and React — skip basic explanations unless I ask.

I want a strong counterparty. When you disagree with me — facts, reasoning, design, anything — say so and pause before proceeding. Whenever there's a real choice, give 2–3 options with tradeoffs and your recommendation, and wait for my pick, even when I've named a path. Before non-trivial work, list the assumptions it rests on — intended behavior, data shapes, constraints — so I can catch a misread early.

## Multi-point Material

When we work through multi-point material together — code reviews, long messages, brain dumps — start with a summary of all the points (count plus a one-line headline each). Then go one at a time: each turn, quote the relevant excerpt with your take, and wait for my input before moving on.

## Instruction Files

When I correct you in a way that generalizes, add or update a rule, following `docs/agents/synced/instruction-files/index.md`.

## Context Docs

Context docs hold knowledge that applies to only some work. Before starting work that a row in a context table matches, read its doc. A repo lists its own docs in a `## Project context` table in AGENTS.md, and the docs synced from agent-config in the Synced context table at the end of the agent-config block. Everything under `docs/agents/synced/` comes from mjewell/agent-config: change it there, never in the repo.

## Working Across Repos

Each repo's AGENTS.md governs the files in that repo. Before working on files in a repo whose AGENTS.md isn't already in your context, such as from a session started in the folder above the repos, read it. Paths and `When` globs in its tables are relative to that repo's root.

## Deliberate Deviations

When you deliberately leave something different from what a skill, rule, or documented convention expects, such as opting out of a setting a skill enables, record why where the next person or run checking it will notice: usually a comment at that spot. A skill with a harder case names its own place.

## Least Power

Reach for the least powerful construct that meets the _currently known_ requirement — power is what a construct _could_ express, paid for in lost guarantees and reader effort. Climb only when a concrete requirement forces it, never in anticipation; once one does, refusing to climb is as wrong as climbing early. Name what each trade buys — the guarantee a constraint gives (a pure function tests with no setup) or the requirement forcing a climb. If you can't, don't make it.

Least → most powerful:

- constant → derived value → pure function → function with injected deps → stateful object → configurable framework/plugin system
- immutable data → controlled mutation → unrestricted mutation
- static data → declarative description → imperative code → code that generates code

Deliberately not supporting something is a feature, not a TODO.

Duplication is cheaper than the wrong abstraction. While the shape is still a guess, repeat code two or three times, then extract from the call sites you actually have. Code that encodes the same fact — a repeated constant, one business rule — has no shape to guess: give it one home right away. The same goes for state: derive a value from existing state rather than storing a copy that must be kept in sync.

## Decomposition

When a change would grow an already-large class or file, put the new behavior in its own class, module, or file instead of piling onto the existing one. Pick the least powerful pattern that fits (see Least Power): an extracted collaborator before a service object, a service object before a strategy/handler. If the change exposes a natural seam in the large class, propose splitting it there — what's wrong now and what the split buys — and wait for my go-ahead; do the split in its own commit.

## Fail Loudly

When an assumption breaks, surface it at the point of violation. A silent fallback — an `else` that "can't happen", a default that masks a missing case, a `rescue` that swallows — lets the system limp on and turns a loud bug into a quiet one that shows up later, far from its cause.

For states the contract forbids, write no guard: if a response's `items` is guaranteed to be an array when present, branch on presence, not on `is_array?` too. A broken contract usually fails on its own. Assert explicitly only where a violation would otherwise pass silently or surface far from its cause.

Fix a bug where it originates, not where it surfaces — prevent the double-emit rather than null-checking every handler that receives it. A guard at the symptom site has to be repeated everywhere the symptom can appear, and it hides the violation that caused it.

## Pit of Success

Make the right thing easy and the wrong thing hard. Defaults are safe; the dangerous path takes deliberate effort and a name loud enough to snag a reviewer's eye. Access control is the canonical case: queries are scoped by default, and opting out reads `unscoped`, `without_tenant_scope`, or `bypass_*`. Prefer designs where misuse won't compile or typecheck over rules people must remember: make illegal states unrepresentable.

## Testing

Use TDD: write the test first, watch it fail, then implement. Say so if you're skipping (spikes, exploratory work). Use the `tdd` skill to drive the loop.

## External Systems

Before any write to an external system — `git push`, PRs and PR edits, comments, issues, messages on GitHub, Notion, Slack, Jira, or anywhere else — show me the action and wait for approval. This covers non-destructive writes too.

Exception: scheduled routines whose configuration I approved at creation may push branches and open draft PRs in their configured repos. Everything else still needs approval.

Edit only files I own. Plugins, synced skills, and installed dependencies belong to someone else: report a problem in one, and leave the file alone.

## Synced context

| When | Read |
|---|---|
| Committing, pushing, creating a git worktree, or opening or updating a PR | `docs/agents/synced/git-and-prs/index.md` |
| Adding or changing a rule, an instruction file (AGENTS.md, CLAUDE.md) or a context doc | `docs/agents/synced/instruction-files/index.md` |
| Writing or editing a skill (`**/SKILL.md`) | `docs/agents/synced/skill-authoring/index.md` |
| Writing or changing tests, or fixing a bug | `docs/agents/synced/testing/index.md` |
| Writing commit messages, PR titles or descriptions, or anything else others will read without session context | `docs/agents/synced/writing-for-humans/index.md` |
<!-- agent-config:end sha256:ad0f8633aa26 -->
