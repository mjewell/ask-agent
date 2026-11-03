---
when: Adding or changing a rule, an instruction file (AGENTS.md, CLAUDE.md) or a context doc
---
# Instruction files and context docs

Use the `pack-rule` skill to place and write a rule. This doc covers the choices it leaves to the repo's instructions.

## Where a rule goes

A rule that fits an existing pack goes in that pack, at its source. Edit it there when that repo is available, otherwise give me the exact text to add. A rule that holds across repos but fits no existing pack goes in a new pack, which each repo installs only if it applies.

Project-specific rules go in the repo's own instruction file or docs. They cover only what's structurally unique to that project — its architecture, commands, and environment quirks — never general working rules.

## How it's written

Instruction files state the current rule or fact, never the history of what changed. They describe a pattern in general terms rather than pointing at files that show it, since a committed doc outlives the files it names and the pointer goes stale unnoticed. Writing used right away, such as a plan or a handoff, can point at files, since they're still where it says.

Illustrate a rule with a general case, not one taken from a particular codebase or framework, such as a named field or one language's idiom. A reader without that context can't tell what the example stands for, and an agent may treat it as the whole rule. A project's own docs, or a pack for one stack, can draw on that project or stack, since everyone reading them works in it.
