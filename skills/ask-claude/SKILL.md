---
name: ask-claude
description: Ask Claude Code to review or implement a coding task through the shared Ask Agent skill. Use when Claude is the requested provider.
---

# Ask Claude

Use the `ask` skill and preselect Claude Code as the provider. This shortcut chooses
only the provider; it does not approve a model, effort, permissions, or other settings.

The `ask` skill is required and owns all instructions, references, and runner logic.
If it is unavailable, tell the user to install both skills and stop:

```sh
npx skills add mjewell/ask-agent --skill ask --skill ask-claude
```
