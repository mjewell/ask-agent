---
when: Drafting a design doc, RFC, proposal, ticket or bug report for people to read
---
# Docs and tickets

## Length and structure

Keep docs short: people don't read long ones. When a doc has to be long, structure it so a reader can skim its shape, drill into the parts that matter to them, and skip the rest. Lead with the takeaway, and mark what's context, what's detail and what's a recommendation, so the reader can choose what to engage with.

Pick the format that carries the content best: bullets, prose, tables or collapsible sections.

Nested numbered points need a `- ` prefix and indentation under their parent, or Markdown renderers collapse them into one paragraph:

```markdown
1. **Top-level point**
   - 1.1. First sub-point
   - 1.2. Second sub-point
```

## Stories

- **Title**: clear and specific, describing the outcome.
- **Format**: `As a <role>, I can <capability>, so that I can <benefit>`, framed around the person or thing being served. Make the role as specific as it needs to be, such as "an admin" or "a signed-in user".
- **Scope**: the smallest shippable slice. A story needn't deliver user-facing value on its own, as long as it doesn't degrade what already works and moves toward a slice that does.
- **Description**: three tiers, in order of how broad their audience is.
  - 1. **Summary**: a few plain sentences on the user outcome, written for the product owner and team. Say what changes for the user and what doesn't. Keep the how high-level: name what changes, but leave out the mechanics and which code it touches.
  - 2. **Reference material**: related tickets, design docs, discussion threads, and people to talk to. It's useful to any reader, so keep it near the top or middle, unless a link is purely implementation detail, in which case it goes in the next tier. Put extensive context in a linked doc, not inline.
  - 3. **Implementation notes**, if any: detailed logs and mechanics go last, under their own heading, never mixed into the tiers above. A reader skimming the ticket should be able to stop before this section without missing anything meant for them.
- **Acceptance criteria**: 1–5 items, phrased from the role's point of view, such as "Admins can delete old conversations".
- **Out of scope**, optionally: what the ticket deliberately leaves out, when its scope could be misread.

## Bugs

The story format doesn't fit a bug. Use:

```
Steps to Reproduce:
- A
- B

Observed:
- C

Desired:
- D
```

"Desired" is the acceptance criteria: the bug is fixed when the desired behavior holds.
