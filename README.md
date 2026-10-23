# Zero Magic Funnel API

Backend for an agentic development funnel, built through week 3 of the
internship plan. A card moves through a fixed state machine; humans approve the
spec and the result; agents build and submit; every illegal or unauthorised move
fails loudly instead of being silently corrected. Week 3 adds a PRD-to-cards
breakdown endpoint with structured output, timeouts, retries, fallback, a rate
limit and a measured eval suite.

Weeks 1-3 are intentionally narrow: FastAPI, Pydantic and pytest; an in-memory
store; no Vue, database, Docker or login yet. Those arrive in later weeks.

## Quick start

```powershell
cd zero-magic
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>. The API works with no API key: the default
model providers are deterministic offline mocks.

```powershell
# Health and the seeded identities
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/actors

# Create a card as a human
$body = @{
  title = "Add comments to cards"
  goal = "Let people discuss a card where the work happens."
  acceptance_criteria = @(
    "POST /api/v1/cards/{id}/comments returns 201 with the new comment.",
    "An empty comment returns 422 with error code invalid_payload."
  )
  out_of_scope = @("Editing comments")
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/cards `
  -Headers @{ "X-Actor-Id" = "human:ada" } `
  -ContentType "application/json" -Body $body
```

`X-Actor-Id` is a temporary stand-in for authentication (week 6). Unknown ids
get 401; the role attached to the id decides what is allowed.

Seeded actors: `human:ada`, `human:grace`, `human:linus`, `agent:builder`,
`agent:reviewer`, `agent:planner`.

## Endpoints

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | anyone | Liveness and version |
| GET | `/api/v1/actors` | anyone | Seeded humans and agents |
| GET | `/api/v1/meta` | anyone | Stages, legal moves, models, limits |
| POST | `/api/v1/cards` | human | Create a card in Spec |
| GET | `/api/v1/cards` | anyone | List, filter by stage/assignee, search, paginate |
| GET | `/api/v1/cards/{id}` | anyone | Read one card |
| PATCH | `/api/v1/cards/{id}` | human | Edit the spec while in Spec |
| DELETE | `/api/v1/cards/{id}` | human | Delete a card and its comments |
| POST | `/api/v1/cards/{id}/transition` | human or agent | Move along a legal edge |
| GET | `/api/v1/cards/{id}/comments` | anyone | Oldest first |
| POST | `/api/v1/cards/{id}/comments` | human or agent | Add a comment |
| PUT | `/api/v1/cards/{id}/assignee` | human | Set or clear one assignee |
| POST | `/api/v1/prds` | human | Store a PRD |
| GET | `/api/v1/prds` | anyone | Newest first |
| GET | `/api/v1/prds/{id}` | anyone | Read a PRD |
| POST | `/api/v1/prds/{id}/breakdown` | human | PRD to typed cards in Spec |

### The funnel

```
Spec --(human)--> Ready --(agent)--> Building --(agent)--> Checks
  ^                  |                                        |
  +----(human)-------+                     (human)------------+
                                                     |
                                                     v
                                                 Validation
                                                   |      |
                                          (human)  |      |  (human)
                                                   v      v
                                                  Done   Building
```

- `409 illegal_transition` for any edge outside the matrix, including a move to
  the current stage.
- `403 agent_not_allowed` when an agent tries a human-only edge: approving a
  spec, sending a card back, accepting checks, or passing validation.
- `403 not_assignee` when an agent works a card assigned to someone else.
- `403 self_validation_blocked` when the actor that built a card tries to mark
  it Done.
- `403 human_only` when an agent creates, edits, deletes, assigns, creates a PRD
  or asks for a breakdown.

### Breaking a PRD down

```powershell
$prd = @{
  title = "Card comments"
  body = @"
Users need a way to discuss a card without leaving the board.
- Add comments to every card with a body and an author.
- Reject empty comments with HTTP 422 and an error code.
- List comments oldest first.
"@
} | ConvertTo-Json

$created = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/prds `
  -Headers @{ "X-Actor-Id" = "human:ada" } `
  -ContentType "application/json" -Body $prd

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/prds/$($created.id)/breakdown" `
  -Headers @{ "X-Actor-Id" = "human:ada" } `
  -ContentType "application/json" -Body '{"prompt_version":"v2"}'
```

The response contains the created cards, the model used, whether a fallback was
used, attempts, token estimates, cost and warnings. Cards are created atomically
in Spec: if every attempt fails, no cards are stored.

Limits (configurable through `.env`, see `.env.example`): 15 s deadline, 5
requests per actor per 60 s, 20 000 PRD characters, 10 cards per breakdown, 2
retries per model. A `429` carries `Retry-After`; a `504` means the deadline
fired; a `502` means every model attempt failed.

## Tests and evals

```powershell
cd zero-magic
& .venv\Scripts\python.exe -m pytest
& .venv\Scripts\python.exe -m evals.run_evals
& .venv\Scripts\python.exe scripts\compare_models.py
& .venv\Scripts\python.exe scripts\embedding_ranking.py
& .venv\Scripts\python.exe scripts\agent_loop.py
```

- `pytest`: 164 tests across unit, API integration, contract, security and eval
  gates.
- `evals.run_evals`: 25 PRDs x 2 prompts x 2 models, writes
  [`docs/eval-report.md`](docs/eval-report.md). The v1 naive prompt scores 47.9
  on `mock-strong`; v2 scores 99.2 with a 100% valid rate.
- `scripts/compare_models.py`: quality, tokens, latency and cost per model,
  writes [`docs/model-comparison.md`](docs/model-comparison.md).
- `scripts/embedding_ranking.py`: offline hashing embeddings, cosine ranking,
  writes [`docs/embedding-search.md`](docs/embedding-search.md).
- `scripts/agent_loop.py`: a tool-use loop under 150 lines that repairs a
  sandboxed calculator, with path and step guardrails.

The mocks are not language models. They are deterministic stand-ins that make
the contracts, validators, retries, fallback, evals and demo usable with no key
and no bill. Set `OPENROUTER_API_KEY` and real model ids to call
OpenAI-compatible models through the same interface.

## Project layout

```
zero-magic/
  app/
    api/            FastAPI routers and dependencies
    ai/             prompts, providers, tokens, safety, embeddings
    schemas/        Pydantic request/response and model-output contracts
    services/       state machine, breakdown orchestration
    config.py       environment-backed settings
    errors.py       one error envelope and its handlers
    store.py        in-memory store (PostgreSQL in week 5)
  evals/            25-PRD dataset, metrics, runner
  scripts/          model comparison, embedding search, agent loop
  examples/         broken calculator sandbox
  specs/            the four build cards with testable acceptance criteria
  docs/             architecture, ADRs, test plan, LLM explainer, reports
  tests/            unit, integration, contract, security, eval gate
```

## Documentation

- [Architecture and security](docs/architecture.md)
- [Test plan and bug reports](docs/test-plan.md)
- [LLM explainer: tokens, cost, structured output](docs/llm-explainer.md)
- [Eval report](docs/eval-report.md) and [model comparison](docs/model-comparison.md)
- [Embedding search](docs/embedding-search.md)
- [Decisions (ADRs)](docs/adr/)
- [Build cards](specs/)

## Deliberate limits

- The store is a process-local dictionary with a lock, not a database.
- Identity is a trusted header, not a login. Never run this publicly as-is.
- Rate limits are per process; multiple workers would need Redis.
- Mock token counts and prices are estimates; check vendor prices before
  trusting a bill.
- There is no frontend in this repository yet (weeks 4+).
