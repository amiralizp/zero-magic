# Gantry API

Gantry is the backend for an agentic development funnel, built through week 3 of
the internship plan. A card moves through a fixed state machine; humans approve
the spec and the result; agents build and submit; every illegal or unauthorised
move fails loudly instead of being silently corrected. Week 3 adds a
PRD-to-cards breakdown endpoint with structured output, timeouts, retries,
fallback, a rate limit and a measured eval suite.

The name is the design: a gantry guides work along fixed rails, and the gates —
spec approval, checks, validation — are held by humans, not agents.

Weeks 1-3 stay intentionally narrow: FastAPI, Pydantic and pytest, with an
in-memory store by default and PostgreSQL when `DATABASE_URL` is configured.
S12 adds signed-token login; Vue and Docker are still ahead.

## Quick start

```powershell
cd zero-magic
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the API reference and
<http://127.0.0.1:8000/console> for the interactive console. The API works with
no API key: the default model providers are deterministic offline mocks.

To run without a terminal, double-click **`start-gantry.bat`** in this folder.
It starts the server on port 8010, opens the console in your browser, and keeps
the logs visible; close the window or press Ctrl+C to stop it. Pass
`--no-browser` if you only want the server.

```powershell
# Sign in first; the password comes from your local .env, never from code.
$login = @{
  username = "ada"
  password = "replace-with-your-GANTRY_HUMAN_PASSWORD"
} | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType "application/json" -Body $login).access_token
$auth = @{ "Authorization" = "Bearer $token" }

# Health is public; everything else needs the token.
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/actors -Headers $auth

# Create a card as the signed-in human
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
  -Headers $auth `
  -ContentType "application/json" -Body $body
```

Every request except `/api/v1/health` needs `Authorization: Bearer <token>`.
`X-Actor-Id` is ignored; the signed token, not a header or a chat body field,
decides who you are. Its `role` claim is checked against the stored actor on
every request; a mismatch gives 401 `invalid_token`. A wrong password gives 401
`invalid_credentials`.

Seeded actors: `human:ada`, `human:grace`, `human:linus`, `agent:builder`,
`agent:reviewer`, `agent:planner`. The initial login accounts are `ada` (human)
and `builder` (agent); they map to those actor ids. Humans create cards and
validate; agents comment and build. Role rules live in `app/services/`, so
chat and direct service calls obey the same limits as HTTP.

## Authentication setup

Set these in your local `.env` (see `.env.example`) before starting the server:

```powershell
JWT_SECRET=replace-with-at-least-32-random-characters
TOKEN_TTL_SECONDS=3600
GANTRY_HUMAN_PASSWORD=replace-with-a-strong-password
GANTRY_AGENT_PASSWORD=replace-with-a-different-strong-password
```

Keep real values out of code, logs and commits. After the Alembic migration,
create the two users yourself:

```powershell
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe scripts\setup_auth.py
```

The script reads the environment, hashes both passwords with Argon2id and
prints usernames only; it never prints passwords or hashes. It is safe to rerun:
existing users are not overwritten. Tokens expire after `TOKEN_TTL_SECONDS`;
there is no refresh or logout endpoint yet, so the browser discards its token on
log out.

## Interactive console

`/console` is a build-free page served by the app: plain HTML, CSS and
JavaScript, no bundler and no new dependency. It is a convenience for using the
API by hand, not the week-4 frontend.

- Sign in as `ada` or `builder`; the token is kept in `localStorage` as
  `zm.token` and sent as `Authorization: Bearer ...`. Log out clears it. The
  standalone `/chat` page reuses the same token.
- Drag cards across the six columns to attempt transitions. Illegal edges and
  agent attempts at human-only edges fail with the real 409/403 error, shown as
  a toast.
- Open a card to edit its spec, set or clear the assignee, comment, or delete.
- Create and list PRDs, then run a breakdown with a chosen prompt and model; the
  result links straight to the created cards.
- Read the live transition matrix, limits, actors and models from
  `/api/v1/meta`.
- Chat with the AI assistant from the floating panel in the corner. The
  conversation is kept in `localStorage` and streamed token by token; the model
  list comes from the provider, never from a hardcoded menu.

The console hides nothing the API enforces. Every button and drop calls the
same endpoint a curl client would, so the server remains the source of truth.
It is deliberately absent from OpenAPI: the API is the product.

## AI chat

The console's chat panel and `/chat` talk to an OpenAI-compatible chat API.
DeepSeek is the default; any vendor with the same shape works by changing the
base URL.

```powershell
# zero-magic/.env
CHAT_API_KEY=sk-...
CHAT_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-flash
CHAT_PROVIDER=DeepSeek
```

Keys are created at <https://platform.deepseek.com/api_keys>. The key stays in
`.env`, which is not committed. Without a key the panel still opens and says why
it cannot answer.

OpenCode Go is the same shape, with two extras: the model list lives beside the
gateway rather than under it, and Go refuses a completion that has no session
id.

```powershell
CHAT_API_KEY=oc_sk_...
CHAT_BASE_URL=https://opencode.ai/inference/go/openai/v1
CHAT_MODELS_URL=https://opencode.ai/inference/go/v1/models
CHAT_MODEL=glm-5.3-flash
CHAT_PROVIDER=OpenCode
CHAT_SESSION=ses_gantry
```

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/chat/models` | Models this key can use, plus the default |
| POST | `/api/v1/chat/completions` | Streamed completion, SSE `data:` frames |

The assistant acts as the signed-in user. It can create a
spec, edit one, move a card, assign it, comment, delete it, or store a PRD.
Those calls go through the same service rules as the buttons, so an agent still
cannot approve a spec and the builder still cannot validate their own card. A
successful action refreshes the board while the reply streams.

`402` from the provider means the account has no balance: the stream reports
that in an `{"error": ...}` frame, because the response has already started.
`401` is a missing or rejected key; `502` is an unreachable or blocked provider.
Those three failures are deliberately distinguishable.

## Endpoints

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | anyone | Liveness and version |
| POST | `/api/v1/auth/login` | anyone | Exchange username/password for a token |
| GET | `/api/v1/auth/me` | token | Describe the signed-in caller |
| GET | `/api/v1/actors` | token | Seeded humans and agents |
| GET | `/api/v1/meta` | token | Stages, legal moves, models, limits |
| POST | `/api/v1/cards` | human token | Create a card in Spec |
| GET | `/api/v1/cards` | token | List, filter by stage/assignee, search, paginate |
| GET | `/api/v1/cards/{id}` | token | Read one card |
| PATCH | `/api/v1/cards/{id}` | human token | Edit the spec while in Spec |
| DELETE | `/api/v1/cards/{id}` | human token | Delete a card and its comments |
| POST | `/api/v1/cards/{id}/transition` | human or agent token | Move along a legal edge |
| GET | `/api/v1/cards/{id}/comments` | token | Oldest first |
| POST | `/api/v1/cards/{id}/comments` | human or agent token | Add a comment |
| PUT | `/api/v1/cards/{id}/assignee` | human token | Set or clear one assignee |
| POST | `/api/v1/prds` | human token | Store a PRD |
| GET | `/api/v1/prds` | token | Newest first |
| GET | `/api/v1/prds/{id}` | token | Read a PRD |
| POST | `/api/v1/prds/{id}/breakdown` | human token | PRD to typed cards in Spec |
| GET | `/console` | anyone | Interactive board (outside OpenAPI) |
| GET | `/chat` | anyone | Standalone chat (outside OpenAPI) |

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
  spec, sending a card back, accepting checks, or passing validation. The
  service rejects every agent move into `Done`, whatever the edge list says.
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
  -Headers $auth `
  -ContentType "application/json" -Body $prd

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/prds/$($created.id)/breakdown" `
  -Headers $auth `
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

- `pytest`: unit, API integration, contract, auth, security, console serving and
  eval gates; the suite needs no database server or real credentials.
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

## Database (PostgreSQL)

PostgreSQL is the durable store. `DATABASE_URL` selects it; with an empty
`DATABASE_URL` the app uses `InMemoryRepository`, so tests and a quick look at
the API need no database server.

Create the local database and role once with `scripts/setup-local-db.ps1`, then
set the URL in `.env`:

```powershell
DATABASE_URL=postgresql+psycopg://gantry_app:...@127.0.0.1:5432/gantry
```

Schema changes go through Alembic. Run the migrations yourself (they need
`DATABASE_URL` in the environment):

```powershell
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe -m alembic downgrade -1
& .venv\Scripts\python.exe -m alembic current
```

There is no backup endpoint; revisit backups with `pg_dump` after S15.


## Project layout

```
zero-magic/
  app/
    api/            FastAPI routers and dependencies, including auth.py
    ai/             prompts, providers, tokens, safety, embeddings
    schemas/        Pydantic contracts, including auth.py
    services/       state machine, breakdown, auth (hashing, signed tokens)
    config.py       environment-backed settings
    errors.py       one error envelope and its handlers
    repositories/
      memory.py     in-memory repository (tests, no server)
      postgres.py   PostgreSQL repository: same interface, durable rows
      factory.py    selects the repository from settings

    web/            build-free console and chat: HTML, CSS, JS
  evals/            25-PRD dataset, metrics, runner
  scripts/          model comparison, embedding search, agent loop, setup_auth.py
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
- [Decisions (ADRs)](docs/adr/), including
  [ADR 0009: token authentication](docs/adr/0009-token-authentication-and-roles.md)
- [Build cards](specs/)

## Deliberate limits

- Without `DATABASE_URL` the store is a process-local dictionary with a lock.
  With it configured, the data survives a restart in PostgreSQL.
- Identity is a short-lived signed token with no refresh or revocation list yet;
  protect `JWT_SECRET` and the bootstrap passwords, and use HTTPS in public.
- Rate limits are per process; multiple workers would need Redis.
- Mock token counts and prices are estimates; check vendor prices before
  trusting a bill.
- The console is a static convenience page, not a frontend application; the
  week-4 Vue client is still ahead.
