# Model comparison

Generated 2026-10-23T14:49:54+00:00 by `scripts/compare_models.py`.
PRDs: prd-01, prd-13, prd-17, prd-18. Prompts: v2.

| Model | Prompt | Valid | Score | Avg cards | Avg latency | Tokens | Cost / 1k breakdowns |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mock-strong | v2 | 100% | 100.0 | 6.0 | 0.73 ms | 6818 | $0.0000 |
| mock-fast | v2 | 100% | 92.5 | 3.5 | 0.62 ms | 6122 | $0.0000 |

## What this comparison does and does not say

- The mocks are deterministic stand-ins. Their latency is local process
  time, not a network round trip, and their cost is zero by design.
- With a real key and real model ids the same table is filled from the
  provider's usage numbers. Prices in `app/ai/tokens.py` are examples and
  must be checked against the vendor before they are trusted.
- Quality is the eval score, not an opinion. A model that produces valid
  but vague cards scores low on testability and coverage.
- Cost per 1,000 breakdowns uses the selected PRDs, so it is a planning
  number, not an invoice.

## Choosing a default

Use the cheapest model that clears the eval gate for the prompt version in
production. The fallback exists for availability, not for quality: if the
primary fails validation, the fallback is tried and the response says so in
`fallback_used` and `warnings`.
