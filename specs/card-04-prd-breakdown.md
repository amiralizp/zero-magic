# Card 04: Break a PRD into draft cards

**Status:** Done (week 3)
**Depends on:** Card 01 (cards API)
**Source:** internship plan, days 11-14

## Goal

Turn a written PRD into typed draft cards in `spec`, with a measured quality bar.
The model is an untrusted component: its output is validated, retried, bounded by
a deadline, optionally replaced by a fallback, and scored before a prompt change
ships.

## Acceptance criteria

- [x] `POST /api/v1/prds` stores a PRD for a human; agents get 403.
- [x] `GET /api/v1/prds` lists newest first; `GET /api/v1/prds/{id}` reads one.
- [x] `POST /api/v1/prds/{id}/breakdown` returns 201 with the created cards,
      `model_used`, `fallback_used`, `prompt_version`, `attempts`, `usage`,
      `duration_ms` and `warnings`.
- [x] Created cards are in `spec`, reference `prd_id`, present `source: "prd"`,
      and use exact card titles for `depends_on`.
- [x] The model output is validated by Pydantic: 1-10 cards, unique titles,
      1-5 testable criteria per card, known dependencies, no self-reference, no
      cycles.
- [x] A dependency cycle, unknown dependency or duplicate title is rejected and
      retried; it is never stored.
- [x] Validation failures are retried (`MODEL_RETRIES`), then the fallback model
      is tried; the response says which model won and why.
- [x] If all attempts fail, the endpoint returns 502 `provider_error` and
      creates zero cards (atomicity).
- [x] The whole call is bounded by `BREAKDOWN_TIMEOUT_SECONDS`; exceeding it
      returns 504 `provider_timeout`.
- [x] The endpoint is rate limited per actor; exceeding it returns 429 with
      `Retry-After` and limit details.
- [x] An unknown model returns 422 `unknown_model` with the available models.
- [x] PRDs over `MAX_PRD_CHARS` return 422 `prd_too_large`.
- [x] Obvious prompt injection in the PRD is neutralised, flagged in `warnings`
      as `prompt_injection_detected:<labels>`, and never echoed into cards.
- [x] The v2 prompt is measurably better than v1 on the 25-PRD suite: valid rate,
      testability and coverage all improve.
- [x] The eval suite fails CI if v2 on `mock-strong` drops below 95% valid or a
      score of 85.

## Out of scope

Streaming, background jobs, human review of drafts before creation, real model
fine-tuning, embedding-based duplicate detection, cost billing.

## Tests

| Criterion | Test |
| --- | --- |
| Happy path and card shape | `test_breakdown.py::test_breakdown_creates_typed_cards_in_spec` |
| Model override | `test_breakdown.py::test_breakdown_model_override` |
| Unknown model/prompt | `test_breakdown.py::test_unknown_model_is_422`, `test_unknown_prompt_version_is_422` |
| Human only | `test_breakdown.py::test_agents_cannot_request_a_breakdown` |
| Rate limit | `test_breakdown.py::test_breakdown_is_rate_limited_per_actor` |
| Fallback | `test_breakdown.py::test_primary_failure_falls_back_and_says_so` |
| Total failure and atomicity | `test_breakdown.py::test_total_failure_is_502_and_creates_no_cards` |
| Timeout | `test_breakdown.py::test_timeout_is_504_and_creates_no_cards` |
| Output cap | `test_breakdown.py::test_output_limit_is_enforced_against_the_configured_maximum` |
| Injection handling | `test_breakdown.py::test_prompt_injection_is_flagged_and_not_echoed` |
| v1 fails, v2 succeeds | `test_breakdown.py::test_naive_prompt_fails_validation_on_a_multi_requirement_prd` |
| Eval quality gate | `test_evals.py::test_full_eval_shows_the_v2_rewrite_matters` |

## Notes

The service, not the provider, owns retries, fallback and persistence. That
keeps providers small and lets the eval harness call them directly with the same
contract.

`depends_on` stores titles rather than ids because draft ids do not exist until
the whole breakdown is accepted. The validator proves the graph is sound before
anything is written. A later migration can replace titles with ids without
changing the public contract.

Offline, `mock-strong` and `mock-fast` are deterministic stand-ins. They simulate
two quality tiers and two prompt behaviours so the eval and failure paths are
repeatable. They are not evidence about any vendor's model; the harness accepts
real OpenAI-compatible models through the same interface.
