---
when: Writing or editing a skill (`**/SKILL.md`)
tier: required
---
# Skill authoring

A skill is strategic: it sets the end state and the path to it, and leaves the tactics to the agent. Open with the end state, stated so the agent can check it: what exists, what's true, what the user has seen. Steps are welcome where the path has phases, but each says what to achieve, not how: the mechanism varies too much between the repos and situations a skill runs in to fix in advance.

Pin a tactic only where leaving it open fails:

- an exact command or format the agent would otherwise guess at
- a write to an external system, or anything hard to undo
- a place where agents have gone wrong before
