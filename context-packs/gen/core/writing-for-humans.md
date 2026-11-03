---
when: Writing commit messages, PR titles or descriptions, changelog entries, READMEs, or anything else others will read without session context
---
# Writing for humans

For prose read by someone without session context — commit messages, PR titles and descriptions, anything I ask you to draft for others — write for that reader, not the transcript.

- **Start Claude-written text with 🤖** when others will read it as-is — PR descriptions, comments, messages — so they can tell at a glance. Commit messages are exempt; the Co-Authored-By trailer marks them.
- **Lead with what changed.** The first sentence states the change plainly. Qualifiers such as scope, rollout state or caveats go in later sentences, unless the opening misleads without them.
- **Use the reader's words.** Shorthand coined during the work isn't the reader's vocabulary, even when it reads like an established term. Say it plainly or define it at first use. Use the name of a pattern or technique only when it's the topic, and otherwise describe what the change does.
