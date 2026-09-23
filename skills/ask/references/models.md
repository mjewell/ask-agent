# Model and effort choices

**User-maintained. Verified 2026-09-19 against provider documentation and the local CLI pickers.**

Prices are approximate API cost per million tokens and may be out of date. They exist to compare relative
cost between models, which changes far less than the absolute figures, not to predict a bill — a
subscription-based CLI may not bill this way at all. Availability depends on the user's account. Neither
this table nor the runner checks entitlement: any provider-native model string is accepted, and the provider
rejects what the account cannot use.

When this table looks stale, the CLI's own model picker is the source of truth. Update this file rather than
working around it.

## Codex (`codex exec --model ID -c model_reasoning_effort="LEVEL"`)

| Model | In $/MTok | Out $/MTok | Effort options | Use it for |
| --- | --- | --- | --- | --- |
| `gpt-5.6-sol` | 4.0 | 20.0 | none, low, medium, high, xhigh, max | Flagship general model for complex professional work. The default choice. |
| `gpt-6-astra` | 10.0 | 50.0 | low, medium, high, xhigh, max, ultra | Most capable; reach for it only when `sol` is genuinely not enough. |
| `gpt-5.6-terra` | 2.0 | 12.0 | none, low, medium, high, xhigh, max | Balances intelligence and cost. |
| `gpt-5.6-luna` | 0.2 | 1.2 | none, low, medium, high, xhigh, max | Cost-sensitive, high-volume work. |

## Claude Code (`claude --model ID --effort LEVEL`)

| Model | Alias | In $/MTok | Out $/MTok | Effort options | Use it for |
| --- | --- | --- | --- | --- | --- |
| `claude-sonnet-5` | `sonnet` | 2.0 | 10.0 | low, medium, high, xhigh, max | Efficient routine work. The CLI default. |
| `claude-opus-5` | `opus` | 5.0 | 25.0 | low, medium, high, xhigh, max | Everyday complex work. Roughly 2× Sonnet's usage. |
| `claude-fable-5-1` | `fable` | 10.0 | 50.0 | low, medium, high, xhigh, max | Hardest, longest-running tasks. Requires usage credits. |
| `claude-haiku-4-5` | `haiku` | 1.0 | 5.0 | low, medium, high, xhigh, max | Fastest option for quick answers. |

## agy (Gemini)

See [agy-cli.md](agy-cli.md#models-and-effort) for model discovery and effort selection.

## Choosing

Match the model to the task's difficulty, then set effort for how much thinking it deserves:

| Task | Suggested |
| --- | --- |
| Mechanical extraction, summarizing a file, a quick lookup | cheapest model, `low` |
| Ordinary code review, a focused bug hunt, a contained implementation | mid-tier, `medium` |
| Architecture review, subtle concurrency or security reasoning, a hard debug | flagship, `high` |
| A genuinely hard problem where a second failure is expensive | top model, `xhigh` or above |

Effort costs output tokens roughly proportionally, so `high` on a cheap model is often a better trade than
`low` on an expensive one.

**Cross-provider checks.** When the point is an independent second opinion, provider diversity matters more
than picking the strongest model. A mid-tier model from a different lab catches things a stronger model from
the same lab as the original author will not.
