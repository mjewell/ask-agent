---
name: ask-codex
description: Ask Codex CLI to review or implement a coding task through the shared Ask Agent skill. Use when Codex is the requested provider.
---

# Ask Codex

Use the `ask` skill and preselect Codex CLI as the provider. This shortcut chooses
only the provider; it does not approve a model, effort, permissions, or other settings.

The `ask` skill is required and owns all instructions, references, and runner logic.
If it is unavailable, tell the user to install both skills and stop:

```sh
npx skills add mjewell/ask-agent --skill ask --skill ask-codex
```
