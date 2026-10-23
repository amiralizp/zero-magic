# ADR 0004: Deterministic mock providers plus an eval gate

**Status:** Accepted
**Date:** 2026-10-23
**Deciders:** backend, AI

## Context

The week 3 deliverable requires a PRD-to-cards endpoint, a before/after
comparison of two prompts, and evidence that a prompt change is an improvement.
Three constraints shape the choice:

- The project must be reviewable with no API key, no account and no bill.
- The test suite must be deterministic; a CI run cannot depend on a vendor's
  latency, quota or model version.
- The provider interface must be the same one a real model uses, or the offline
  evidence proves nothing about the real path.

Using only a real model fails the first two. Using only a fake that returns
canned cards fails the third: it would not exercise validation, retries,
fallback, token accounting or prompt sensitivity.

## Decision

Ship two deterministic providers, `mock-strong` and `mock-fast`, behind the same
`BreakdownProvider` protocol as the real `OpenRouterProvider`.

- **Prompt sensitivity.** The mock reads the prompt version. Under `v1` it emits
  shallow cards with vague criteria and does not neutralize injection. Under
  `v2` it emits one card per requirement with observable criteria, wraps
  dependencies as titles and neutralizes injection. This is a simulation of the
  effect we measured, not a model.
- **Quality tiers.** `mock-strong` produces one card per requirement;
  `mock-fast` groups two requirements per card, producing fewer, coarser cards.
- **Determinism.** Same input and prompt -> same output, byte for byte. Token
  counts come from `estimate_tokens`; latency is local process time.
- **Default.** Both are always registered, and they are the default models when
  no key is present. `build_providers` fails fast at startup if a configured
  real model has no key, rather than failing at request time.
- **Eval gate.** `evals/dataset.json` has 25 PRDs; `evals/metrics.py` scores
  validity, testability, coverage, scope and titles; `tests/test_evals.py` fails
  the suite if v2 drops below 95% valid or a score of 85, or if it stops beating
  v1 on score and testability.

The README and the generated reports state plainly that the mocks are not
language models.

## Consequences

**Good**

- `git clone && pytest` works offline in seconds.
- The failure paths (invalid output, retry, fallback, timeout) are reproducible
  on demand, including a provider that always fails or always sleeps.
- Prompt changes have a numeric regression signal before a real call is made.
- The real provider is exercised by the same contract, so the integration point
  is narrow.

**Bad**

- Mock scores are not evidence about any vendor. A reviewer could misread the
  99.2 as a model quality claim; the docs must keep saying otherwise.
- The mock encodes our assumptions about prompt behaviour. If v2 changes in a
  way the mock does not model, the eval will not notice.
- The mock's own bugs look like model behaviour. BUG-003 (Markdown headings
  counted as requirements) is exactly this failure mode.
- Real latency and real token counts are absent from the default report.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Real model only | Non-deterministic, costs money, needs a key, fails offline |
| Canned responses | Does not exercise validators, retries or prompt sensitivity |
| Recorded real responses (VCR) | Good for regression, but the recording needs a key and ages badly; a useful addition later |
| A tiny local model | Heavy download, slow tests, quality unrelated to hosted models |
| Skip the evals | The week 3 deliverable is specifically before/after evidence |

## Follow-up

`scripts/compare_models.py` already runs the same rubric against real ids when
`OPENROUTER_API_KEY` is set. The next step is a scheduled job that records real
scores and costs, so the mock baseline and the vendor baseline are reported side
by side instead of being confused.
