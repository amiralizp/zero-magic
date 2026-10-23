# PRD breakdown eval report

Generated 2026-10-23T14:59:52+00:00 from `evals/dataset.json` (version 1, 25 PRDs).

## What is measured

Each PRD is sent to every prompt/model pair. The output is validated with the
same Pydantic contract the API uses, then scored from 0 to 100:

| Dimension | Points | Rule |
| --- | ---: | --- |
| Valid output | 40 | Parses as `Breakdown`, at most ten cards, no echoed injection |
| Testable criteria | 20 | 1-5 criteria per card, no vague wording, observable signal |
| Requirement coverage | 25 | Each keyword group from the PRD appears in some card |
| Scope | 10 | Card count inside the PRD's expected range |
| Titles | 5 | Specific, unique, 3-80 characters |

An invalid output scores zero. This mirrors production: the service stores zero
cards when every attempt fails validation.

## Results

| Prompt | Model | Cases | Valid | Score | Testable | Coverage | Scope | Cards | Tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | mock-fast | 25 | 92% | 53.5 | 0% | 33% | 84% | 3.7 | 9320 |
| v1 | mock-strong | 25 | 92% | 47.9 | 0% | 33% | 28% | 2.8 | 7716 |
| v2 | mock-fast | 25 | 100% | 91.7 | 100% | 97% | 24% | 2.8 | 34909 |
| v2 | mock-strong | 25 | 100% | 99.2 | 100% | 97% | 100% | 4.8 | 38803 |

Before/after:

- **mock-strong**: v1 -> v2: score 47.9 -> 99.2 (+51.4), valid 92% -> 100%, testable 0% -> 100%

- **mock-fast**: v1 -> v2: score 53.5 -> 91.7 (+38.2), valid 92% -> 100%, testable 0% -> 100%

## Failed cases that drove the v2 rewrite

**v1/mock-fast** - 2 of 25 cases invalid (showing up to 4)
- `prd-16` Export screen with an injection attempt: ValueError: output echoed instruction-like text from the PRD
- `prd-17` Project workspace: ValidationError: 1 validation error for CardDraft acceptance_criteria List should have at most 5 items after validation, not 8

**v1/mock-strong** - 2 of 25 cases invalid (showing up to 4)
- `prd-16` Export screen with an injection attempt: ValueError: output echoed instruction-like text from the PRD
- `prd-17` Project workspace: ValidationError: 1 validation error for CardDraft acceptance_criteria List should have at most 5 items after validation, not 8

Failing prompt/model combinations: v1/mock-strong, v1/mock-fast.

## Reading the numbers

- The mocks are deterministic stand-ins, not language models. Their scores show
  that the contract, validators, retry path and metrics work; they are a
  regression baseline, not a claim about any vendor's model quality.
- Cost is zero for the mocks. Token counts are estimates from
  `app/ai/tokens.py`; the same columns are filled from the provider response
  when a real model is used.
- Latency for the mocks is process time and is not comparable to a network call.
- The gate used in this project: v2 on `mock-strong` must keep a 100% valid rate
  and a score of at least 85. Anything below that fails CI through
  `tests/test_evals.py`.
