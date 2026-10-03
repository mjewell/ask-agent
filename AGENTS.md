<!-- agent-config:start (synced from mjewell/agent-config; edit it there, not here) -->
## Collaboration

I'm an experienced full-stack engineer, expert in TypeScript and React — skip basic explanations unless I ask.

I want a strong counterparty. When you disagree with me — facts, reasoning, design, anything — say so and pause before proceeding. Whenever there's a real choice, give 2–3 options with tradeoffs and your recommendation, and wait for my pick, even when I've named a path. Before non-trivial work, list the assumptions it rests on — intended behavior, data shapes, constraints — so I can catch a misread early.

## Multi-point Material

When we work through multi-point material together — code reviews, long messages, brain dumps — start with a summary of all the points (count plus a one-line headline each). Then go one at a time: each turn, quote the relevant excerpt with your take, and wait for my input before moving on.

## Instruction Files

When I correct you in a way that generalizes, add or update a rule. General rules live in `shared/instructions.md` in mjewell/agent-config: edit it there when that repo is available, otherwise give me the exact text to add. Project-specific rules go in the repo's AGENTS.md, outside the agent-config block, and cover only what's structurally unique to that project — its architecture, commands, and environment quirks such as a test setup that can't run — never general working rules. Instruction files state the current rule or fact, never the history of what changed.

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

Test behavior through the public interface, never private methods: a test stands in for the API's caller. If a refactor breaks a test without changing observable behavior, the test was wrong.

Prefer high-fidelity tests that exercise a feature across its units over isolated per-class tests, which miss the wiring between them. Split test files by user-facing concern, not source-file structure, and keep them small. Extract shared setup into helpers or fixtures.

Mock only what you can't run reliably or deterministically: network, third-party APIs, time, randomness.

Design code for production, not for tests. A testability seam is good design when production uses it too. The exception is injecting what tests may mock (time, randomness, network) with a production default. Anything else only tests touch — a parameter only tests pass, a default that lets tests skip setup, a branch only tests take — is a test smell.

## Minimal Reproductions

When a fix is a guess, or the bug is slow or awkward to trigger in the real system, build a minimal reproduction and prove the fix there first. A fix verified in isolation shows you found the root cause, not just a symptom that happened to disappear.

## Worktrees

Create git worktrees in the repo's `.claude/worktrees/`, each named after its branch with `/` replaced by `-` (`claude/add-scrolls` → `claude-add-scrolls`). Use no generated names and no `wt-` or other prefix, so each name says what the worktree is for.

## Pull Requests

Keep PRs small: aim for under 250 changed lines, with 500 as the ceiling. If a PR must exceed it, say why. Generated changes (lockfiles, regenerated schemas) don't count.

Plan a large story up front as a sequence of smaller PRs. Each may be incomplete on its own, but none may break features already in use; an unfinished feature behind a flag is fine.

Open PRs as drafts (`gh pr create --draft`). Mark one ready for review only when I ask.

Whenever you push to a branch with an open PR, check that the title and description still match the diff, and update them if they've drifted.

To edit a title or description, fetch the current text (`gh pr view <n> --json title,body`) and make the smallest edit that restores accuracy — I edit descriptions too, and rewriting from your earlier copy discards my changes. If the description no longer starts with 🤖, I've taken it over: leave it alone and tell me what's stale.

## Revising PRs Under Review

Keep changes made after a review reviewable on their own, so the reviewer sees what moved without re-reading the whole diff. Once a PR has a review — a comment, or a status change like approval — fix things in new commits instead of amending commits that predate it. A commit pushed after a review can be amended until the next review covers it; before any review, amend freely.

Reviews land while you work, so check right before amending on a branch with an open PR: `gh pr view <n> --json reviews,comments`.

Force-pushing is fine when the reviewed commits' content stays put — rebasing onto the latest main, or reparenting branches above a revised PR in a stack. Their SHAs may change.

## Writing for Humans

For prose read by someone without session context — commit messages, PR titles and descriptions, anything I ask you to draft for others — write for that reader, not the transcript.

- **Start Claude-written text with 🤖** when others will read it as-is — PR descriptions, comments, messages — so they can tell at a glance. Commit messages are exempt; the Co-Authored-By trailer marks them.
- **Open verb-first, gist only.** The first sentence plainly states what changed: "Accept new request params for search scoping", not "Parse-only dark launch of the new scoping contract on search." Qualifiers go in their own later sentences ("No behavior change — nothing reads the params yet") unless the headline misleads without them.
- **Use the reader's words.** Shorthand coined during the work isn't the reader's vocabulary, even with "the" in front ("the flip"): say it plainly or define it at first use. Use a pattern name ("dark launch") only when the pattern itself is the topic; otherwise the plain description ("accepted but not used yet") wins.

## External Systems

Before any write to an external system — `git push`, PRs and PR edits, comments, issues, messages on GitHub, Notion, Slack, Jira, or anywhere else — show me the action and wait for approval. This covers non-destructive writes too.

Exception: scheduled routines whose configuration I approved at creation may push branches and open draft PRs in their configured repos. Everything else still needs approval.

Edit only files I own. Plugins, synced skills, and installed dependencies belong to someone else: report a problem in one, and leave the file alone.
<!-- agent-config:end sha256:5cfd9fce5f87 -->
