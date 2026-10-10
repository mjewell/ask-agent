---
when: Writing commit messages, PR titles or descriptions, or anything else others will read without session context
tier: required
---
# Writing for humans

For prose read by someone without session context — commit messages, PR titles and descriptions, anything I ask you to draft for others — write for that reader, not the transcript.

- **Start Claude-written text with 🤖** when others will read it as-is — PR descriptions, comments, messages — so they can tell at a glance. Commit messages are exempt; the Co-Authored-By trailer marks them.
- **Open verb-first, gist only.** The first sentence plainly states what changed: "Accept new request params for search scoping", not "Parse-only dark launch of the new scoping contract on search." Qualifiers go in their own later sentences ("No behavior change — nothing reads the params yet") unless the headline misleads without them.
- **Use the reader's words.** Shorthand coined during the work isn't the reader's vocabulary, even with "the" in front ("the flip"): say it plainly or define it at first use. Use a pattern name ("dark launch") only when the pattern itself is the topic; otherwise the plain description ("accepted but not used yet") wins.
