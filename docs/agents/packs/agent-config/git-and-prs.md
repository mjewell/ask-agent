---
when: Committing, pushing, creating a git worktree, or opening or updating a PR
tier: required
---
# Git and pull requests

## Worktrees

Create git worktrees in the repo's `.claude/worktrees/`, each named after its branch with `/` replaced by `-` (`claude/add-scrolls` → `claude-add-scrolls`). Use no generated names and no `wt-` or other prefix, so each name says what the worktree is for.

## Pull Requests

Plan a large story up front as a sequence of smaller PRs. Each may be incomplete on its own, but none may break features already in use; an unfinished feature behind a flag is fine.

Open PRs as drafts (`gh pr create --draft`). Mark one ready for review only when I ask.

Whenever you push to a branch with an open PR, check that the title and description still match the diff, and update them if they've drifted.

To edit a title or description, fetch the current text (`gh pr view <n> --json title,body`) and make the smallest edit that restores accuracy — I edit descriptions too, and rewriting from your earlier copy discards my changes. If the description no longer starts with 🤖, I've taken it over: leave it alone and tell me what's stale.

## Revising PRs Under Review

Keep changes made after a review reviewable on their own, so the reviewer sees what moved without re-reading the whole diff. Once a PR has a review — a comment, or a status change like approval — fix things in new commits instead of amending commits that predate it. A commit pushed after a review can be amended until the next review covers it; before any review, amend freely.

Reviews land while you work, so check right before amending on a branch with an open PR: `gh pr view <n> --json reviews,comments`.

Force-pushing is fine when the reviewed commits' content stays put — rebasing onto the latest main, or reparenting branches above a revised PR in a stack. Their SHAs may change.
