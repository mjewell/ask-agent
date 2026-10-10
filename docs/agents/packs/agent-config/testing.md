---
when: Writing or changing tests, or fixing a bug
tier: required
---
# Testing

Test behavior through the public interface, never private methods: a test stands in for the API's caller. If a refactor breaks a test without changing observable behavior, the test was wrong.

Prefer high-fidelity tests that exercise a feature across its units over isolated per-class tests, which miss the wiring between them. Split test files by user-facing concern, not source-file structure, and keep them small. Extract shared setup into helpers or fixtures.

Mock only what you can't run reliably or deterministically: network, third-party APIs, time, randomness. Mock at the outermost boundary: return the raw response the API sends, not a transformed result from a service class downstream, so every parse and transform runs for real.

Design code for production, not for tests. A testability seam is good design when production uses it too. The exception is injecting what tests may mock (time, randomness, network) with a production default. Anything else only tests touch — a parameter only tests pass, a default that lets tests skip setup, a branch only tests take — is a test smell.

## Minimal Reproductions

When a fix is a guess, or the bug is slow or awkward to trigger in the real system, build a minimal reproduction and prove the fix there first. A fix verified in isolation shows you found the root cause, not just a symptom that happened to disappear.
