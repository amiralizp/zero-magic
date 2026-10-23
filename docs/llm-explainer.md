# LLM explainer

How the AI parts of this project work, what they cost, and where they fail. Every
number below can be reproduced from the repository; commands are at the end.

## 1. The mental model

A chat model is a next-token predictor with a fixed context window. One call has:

```
input tokens  = system prompt + user message + conversation history
output tokens = the JSON the model writes
cost          = input_tokens * input_price + output_tokens * output_price
latency       = queueing + prompt processing + token generation
```

Nothing in the model knows about your database, your users or your rules. A
prompt is a request, not a guarantee. The only guarantees in this project come
from code that runs after the model: Pydantic validation, graph checks, the card
cap, the timeout and the eval gate.

That is why the breakdown pipeline is drawn as *model inside a harness*, not the
other way around.

## 2. Tokens

### What a token is

Models do not read characters. A tokenizer splits text into sub-word pieces.
English averages roughly four characters per token; Persian/Arabic script is
usually denser, around three characters per token, because short vowels and
common affixes split more finely. Code, URLs and JSON punctuation are often
*less* efficient than prose.

We do not ship a tokenizer (no extra dependency, no model download). Instead:

```python
def estimate_tokens(text: str) -> int:
    persian = count of characters in U+0600..U+06FF
    ratio = 3.0 if persian > 30% of characters else 4.0
    return ceil(len(text) / ratio)
```

This is an estimate and is labelled as one everywhere it appears. For billing,
the provider's `usage` numbers are used: `OpenRouterProvider` reads
`prompt_tokens` and `completion_tokens`, and only falls back to the estimator
when the response omits them.

### Context budget

| Part | Size in the v2 path |
| --- | ---: |
| v1 system prompt | 41 tokens |
| v2 system prompt | 962 tokens |
| Average eval PRD | 68 tokens |
| Largest eval PRD | 160 tokens |
| `MAX_PRD_CHARS` = 20,000 | about 5,000 tokens |
| `max_tokens` on the response | 2,500 |
| Worst case input + output | about 8,500 tokens |

So a maximum-size PRD still fits an 8k-context model, but barely. A 128k model
has plenty of room. If the system prompt grows, the safe move is to measure
`estimate_tokens(system) + estimate_tokens(prd) + max_tokens` and compare with
the model's real window; do not assume.

The evals give a practical number: v2 on `mock-strong` used **38,803 tokens for
25 PRDs**, about 1,552 tokens per breakdown (input + output). That is the number
to multiply when planning spend.

### Why the estimate matters for Persian

A 20,000-character Persian PRD is about 6,700 tokens by this estimator, not
5,000. The same content in English is cheaper to send. The estimator switches at
30% Persian characters so mixed documents do not get the wrong ratio. A real
tokenizer would be more accurate; the point here is to avoid being off by 4x.

## 3. Prices and cost

Prices live in `app/ai/tokens.py`, in USD per million tokens. They are examples,
not a price list; verify them before trusting a bill.

| Model | Input / Mtok | Output / Mtok | Cost for 1,500 in + 800 out | Cost per 1,000 breakdowns |
| --- | ---: | ---: | ---: | ---: |
| `mock-strong` | 0.00 | 0.00 | $0.0000 | $0.00 |
| `mock-fast` | 0.00 | 0.00 | $0.0000 | $0.00 |
| `google/gemini-2.0-flash-001` | 0.10 | 0.40 | $0.00047 | $0.47 |
| `openai/gpt-4o-mini` | 0.15 | 0.60 | $0.00071 | $0.71 |
| `anthropic/claude-3.5-haiku` | 0.80 | 4.00 | $0.00440 | $4.40 |
| `openai/gpt-4o` | 2.50 | 10.00 | $0.01175 | $11.75 |

At 2,000 breakdowns a month, that is roughly $0.94 on Gemini Flash, $1.41 on
4o-mini, $8.80 on Haiku and $23.50 on 4o. A retry doubles the input cost for that
request; a fallback pays for both models.

Two rules of thumb:

1. **Output tokens dominate.** At 4o prices, output is 4x input per token. A
   prompt that asks for long prose is expensive; the v2 contract deliberately
   caps criteria at 240 characters.
2. **Cost is not the first gate.** A cheap model that returns invalid cards
   costs more than its token bill, because every failed breakdown burns attempts
   and gives the user nothing. Choose the cheapest model that clears the eval
   gate, then optimise the prompt.

`estimate_cost()` is exact arithmetic on the table; the mock models are zero by
design. The response exposes `usage.input_tokens`, `usage.output_tokens` and
`usage.estimated_cost_usd` on every breakdown.

## 4. Temperature and sampling

`temperature` controls how flat or peaked the next-token distribution is. At 0
the model usually picks the most likely token; at 1 it samples much more widely.

This project calls with `temperature=0.0` and `max_tokens=2500`. That is the
right default for extraction tasks: we want the most likely valid JSON, not
creative variation.

Temperature 0 is **not** determinism. Providers may batch requests differently,
change model versions, or use non-deterministic kernels. The eval gate exists
because of this: the same prompt can produce a different breakdown tomorrow. The
mock providers *are* deterministic, which is why they can be a regression
baseline, but that says nothing about a vendor's model.

Retries are useful precisely because of this variance: a schema failure on
sample one may succeed on sample two. `MODEL_RETRIES=2` gives three attempts per
model, and the fallback adds three more.

## 5. Structured output

### The contract

`app/schemas/prds.py` defines what a valid answer is:

```json
{
  "cards": [
    {
      "title": "3-80 characters, unique",
      "goal": "10-400 characters",
      "acceptance_criteria": ["1-5 items, 5-240 characters each"],
      "depends_on": ["exact titles from this same breakdown"]
    }
  ]
}
```

`extra="forbid"` on every model means an extra key is a failure, not a silent
drop. `Breakdown` adds graph validation:

- titles must be unique (case-insensitive),
- a card cannot depend on itself,
- every dependency must exist in the same output,
- the dependency graph must be acyclic.

Those are not cosmetic checks. A dangling dependency would create a card that
can never be started; a cycle would deadlock the board.

### How the JSON is obtained

The real provider uses two mechanisms together:

1. `response_format: {"type": "json_object"}` asks the API to return JSON.
2. The content is stripped of Markdown fences, the outermost `{...}` is
   extracted, and `Breakdown.model_validate_json` parses it.

The second step matters because JSON mode is not a schema guarantee across
providers, and models sometimes wrap output in prose or fences even when asked
not to. `_extract_json_object` rejects text with no object; the schema rejects
objects of the wrong shape.

### Failure taxonomy

| Failure | Example | Detected by | Response |
| --- | --- | --- | --- |
| Transport | connection reset, HTTP 500 | `httpx` error / status check | retry, maybe fallback |
| No JSON | prose answer | `_extract_json_object` | retry |
| Truncated JSON | output hits `max_tokens` | JSON parse | retry with a new sample |
| Schema violation | 6 criteria, blank goal, extra key | Pydantic | retry |
| Graph violation | cycle, unknown dependency | `Breakdown` validator | retry |
| Cap violation | 11 cards | `_validate_output` | retry |
| Injected text | "ignore previous instructions" in a card | `_output_has_injection` | retry |
| Deadline | provider slower than 15 s | `asyncio.timeout` | 504, no cards |
| Budget | sixth request in a minute | limiter | 429, `Retry-After` |
| All failed | every attempt invalid | service | 502, no cards |

The distinction between *retryable* and *fatal* is in the service, not the
provider. Providers raise `ProviderError`; the service decides whether to try
again, switch model, or give up.

### Atomicity

Cards are created only after a valid `Breakdown` exists, in a single loop. If the
model fails, the store is untouched. The test
`test_total_failure_is_502_and_creates_no_cards` asserts both the card count and
the absence of partial cards. A half-written breakdown would be worse than an
error, because the board would show work nobody approved.

## 6. Prompt engineering, measured

Two prompts are shipped and compared:

| | v1 ("naive") | v2 ("spec-quality") |
| --- | --- | --- |
| Length | 41 tokens | 962 tokens |
| Role | "You split requirements" | senior engineer in a review funnel |
| Rules | "Keep it short" | 7 numbered rules: count, title, goal, criteria, deps, coverage, untrusted input |
| Examples | none | two worked PRDs |
| Output | "JSON" | exact shape, plus `depends_on` semantics |
| Testability | not mentioned | observable result, banned vague phrases |

Measured on the same 25 PRDs, same deterministic model:

| Prompt | Valid | Score | Testable criteria | Coverage | Cards / case |
| --- | ---: | ---: | ---: | ---: | ---: |
| v1 / `mock-strong` | 92% | 47.9 | 0% | 33% | 2.8 |
| v2 / `mock-strong` | 100% | 99.2 | 100% | 97% | 4.8 |
| v1 / `mock-fast` | 92% | 53.5 | 0% | 33% | 3.7 |
| v2 / `mock-fast` | 100% | 91.7 | 100% | 97% | 2.8 |

What changed and why:

- **Role and consequences.** Telling the model that a human approves and a
  different human validates changes what "done" means. v1 had no audience.
- **Numeric constraints.** "1-5 criteria, 5-240 characters" is checkable by the
  model and by the validator. "Keep it short" is not.
- **Banned phrases.** Naming "works well", "user friendly", "handles errors"
  removes the easy way to satisfy the prompt without saying anything testable.
- **Observable results.** Asking for a status code, field, screen state or
  stored value is what makes a criterion testable; the eval measures exactly
  that.
- **Worked examples.** Two examples anchor the JSON shape, the title style and
  the dependency convention far more cheaply than another paragraph of rules.
- **Untrusted input.** v2 wraps the PRD in `<prd>` and says it is data, not
  instructions. The code also neutralises obvious injection, because a prompt
  instruction alone is not a security control.

The cost of v2 is roughly 900 extra input tokens per call. At 4o-mini prices
that is about $0.00014 per breakdown, and it buys a 51-point score improvement
and an 8-point validity improvement. That is the trade the eval exists to make
visible.

## 7. The eval suite

`evals/dataset.json` has 25 PRDs: normal features, tiny input, ambiguous input,
a long 12-requirement PRD, duplicate requirements, Persian, an injection
attempt, and cases that should produce clarification cards. Each case carries
keyword groups and an expected card-count range.

Scoring (`evals/metrics.py`):

| Dimension | Points | Rule |
| --- | ---: | --- |
| Valid output | 40 | parses as `Breakdown`, <= 10 cards, no echoed injection |
| Testable criteria | 20 | share of criteria that name an observable signal and avoid vague words |
| Coverage | 25 | share of keyword groups present somewhere in the output |
| Scope | 10 | card count inside the case's expected range |
| Titles | 5 | unique, specific, 3-80 characters |

An invalid output scores zero for the case. The aggregate averages across the
dataset; the gate requires v2 on `mock-strong` to keep >= 95% valid and a score
>= 85, with strictly better score and testability than v1.

**What the numbers do not say.** The mocks are not language models. The scores
prove the harness, contract, retries and metrics work, and give a stable
regression baseline. They are not evidence that a vendor will score the same.
`scripts/compare_models.py` runs the same rubric against real models when a key
is present; that is the number to use for a model decision.

## 8. Embeddings

`app/ai/embeddings.py` implements a hashing vectoriser:

1. Tokenise on Latin words and Persian/Arabic letter runs, case-folded.
2. Hash each token into one of 1,024 dimensions with a signed contribution.
3. L2-normalise, so a long PRD is not favoured just for having more words.
4. Score with the dot product, which equals cosine similarity for unit vectors.

Run `scripts/embedding_ranking.py` to reproduce the report. Six probe queries
against the 25 PRDs currently hit top-1 six times, including the Persian query
`نظرات کارت`.

Why this is honest: it is a **lexical** embedder. It finds shared vocabulary, not
meaning. `owner` does not retrieve `assignee` unless both words appear. A real
embedding model would, at the cost of a network call and a per-token bill. The
interface (`embed`, `cosine`, `rank`, `search`) is the same one a real provider
would implement, so swapping it later does not change callers.

At 25 documents, ranking everything is fine. At a few thousand, store vectors in
pgvector and use an HNSW index. Two rules carry over unchanged:

- embed documents once and store the vector, embed the query at search time;
- similarity is not authorisation. Filter by workspace and role *before*
  returning results, or search becomes a data leak.

## 9. The agent loop

`scripts/agent_loop.py` is a complete tool-use runner in under 150 lines. The
policy is scripted, not a model, so the demo is offline and repeatable; the loop
is the part that matters.

```
history = []
for step in range(max_steps):
    action = policy(history)          # a model would return the same dict
    if action is None: break
    observation = execute_tool(action)
    history.append({step, tool, args, ok, observation})
```

Tools:

| Tool | Guardrail |
| --- | --- |
| `read_file` | path must resolve inside the sandbox, max 10,000 characters |
| `write_file` | `.py` only, max 10,000 characters, path must stay inside |
| `run_tests` | fixed `pytest` command, 60 s timeout, output truncated to 2,000 characters |

The demo copies `examples/broken_calc` to a temporary directory, reads the
source and the test, repairs `subtract` (`a + b` -> `a - b`), runs the tests, and
stops. Four steps, one JSONL trace, exit code 0.

Why these guardrails:

- **Path containment** stops `../../.ssh/id_rsa` and absolute paths. Tests cover
  both separators and an absolute escape.
- **Extension allowlist** stops the agent from writing a shell script or a
  `conftest.py` that changes how tests run.
- **Size cap** stops a runaway generation from filling the disk.
- **Step cap** turns a looping policy into a clean `max_steps` failure instead
  of a hung process.
- **Trace** makes the run auditable: every action, argument and observation is
  on disk as one JSON object per line.

The loop is intentionally not a framework. There is no planner, memory or
retriever; adding those without the trace and the caps above would just hide
failures. A model policy would plug in at `scripted_policy`, returning
`{"tool": ..., ...}` or `None`.

## 10. Shipping a prompt change

Checklist used in this repository:

1. Add or edit a case in `evals/dataset.json`. Keep ids unique.
2. Run `python -m evals.run_evals`. Compare per-dimension, not just the total.
3. If validity drops, stop: a higher score on valid cases does not compensate
   for outputs that cannot be stored.
4. Run `python -m pytest`. The eval gate is part of the suite.
5. If the change is meant to save money, run `scripts/compare_models.py` and
   compare cost per 1,000 breakdowns at the same quality bar.
6. Commit the new report under `docs/` so the claim and the evidence move
   together.

## 11. Glossary

| Term | Meaning here |
| --- | --- |
| Token | A sub-word unit the model reads or writes; billed per million |
| Context window | Maximum input + output tokens for one call |
| Temperature | Sampling randomness; 0 is greedy, not guaranteed identical |
| Structured output | Constraining the answer to a schema; here JSON mode + Pydantic |
| Fallback | A second model tried after the primary fails validation or transport |
| Retry | Another sample from the same model after an invalid or failed attempt |
| Injection | Untrusted text that tries to act like instructions to the model |
| Embedding | A vector representing text, compared with cosine similarity |
| Eval | A repeatable scored suite used to gate prompt/model changes |
| Tool-use loop | Model (or policy) chooses a tool, observes the result, repeats |

## Reproduce

```powershell
cd zero-magic
& .venv\Scripts\python.exe -m evals.run_evals
& .venv\Scripts\python.exe scripts\compare_models.py
& .venv\Scripts\python.exe scripts\embedding_ranking.py
& .venv\Scripts\python.exe scripts\agent_loop.py
```

Outputs: `docs/eval-report.md`, `docs/model-comparison.md`,
`docs/embedding-search.md`, `scripts/agent-run.jsonl`.
