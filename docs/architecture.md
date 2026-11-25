# Architecture

**Status:** weeks 1-3 complete (cards, comments, assignment, PRD breakdown), a build-free console and S12 signed-token authentication
**Last reviewed:** 2026-11-20
**Out of scope for this version:** the week-4 Vue frontend and Docker

## 1. What this service is

Gantry is an HTTP API for an agentic development funnel. Work is described as a
*card* with a written spec. A card walks a fixed lifecycle: a human approves the
spec, an agent builds it, a human accepts the result. Week 3 adds a *PRD*
resource and an endpoint that turns a PRD into typed draft cards with an LLM.

Two properties drive most of the design:

1. **The state machine is the product.** Illegal moves are rejected with a
   specific status and error code, never silently corrected. An agent cannot
   approve a spec or validate its own work.
2. **The model is an untrusted dependency.** Its output is schema-validated,
   bounded, retried, optionally replaced by a fallback, and scored by an eval
   suite before a prompt change ships.
3. **Identity is signed, not claimed.** A bearer token decides who is calling;
   a header or a chat body field cannot change it.

## 2. Context

```
Console page              curl / PowerShell          evals + scripts
app/web/ (no build)              |                        |
        |                        |                        |
        +---- HTTP + Bearer -----+------------------------+
                                 |
                     FastAPI app (app/main.py)
                     CORS, request id, errors
                                 |
        +------------------------+-------------------------+
        |                        |                         |
   API routers             Services                  AI layer
   app/api/*.py            app/services/*.py         app/ai/*
        |                        |                         |
        +----------+-------------+------------+------------+
                   |                          |
             Repository                 Mock providers (default)
             app/repositories/factory.py picks:  OpenRouter provider (opt-in)
             memory or PostgreSQL
```

There is no external service in the default configuration. That is deliberate:
the repo runs offline, tests are deterministic, and no key is required to review
the work.

## 3. Layers and the rules between them

| Layer | Files | May know about | Must not |
| --- | --- | --- | --- |
| HTTP | `app/api/*.py`, `app/main.py` | schemas, services, errors | contain business rules or touch dicts |
| Service | `app/services/cards.py`, `app/services/breakdown.py`, `app/services/auth.py` | repository, schemas, AI layer, settings | build HTTP responses |
| Repository | `app/repositories/` (memory, postgres, factory) | schemas, actors | enforce permissions or transitions |
| AI | `app/ai/*` | schemas for model output | read the store or raise `AppError` (except the registry) |
| Contracts | `app/schemas/*` | Pydantic only | perform I/O |

The important line is between HTTP and service. Routers translate a request to
typed arguments and a result to a response model; the service owns every rule
that a reviewer would call "the business logic". A test can therefore exercise
the state machine without HTTP, and the eval harness can call a provider without
starting the app.

`app/services/cards.py` is the single owner of the transition matrix. If it is
not in that file, it is not a rule. `app/services/auth.py` is the single owner of
password hashing and token signing; it is the only app module that imports
`jwt` or `argon2`, and an architecture test enforces that.

### 3.1 Target boundaries (week 4)

Dependencies point one way: HTTP -> Service -> Repository -> database. The AI
layer is called by services. Schemas and the framework-free error type are
shared by everyone.

```
HTTP (api)  -->  Service  -->  Repository  -->  PostgreSQL
                    |
                    +--> AI layer (providers)

Shared: schemas (contracts), errors (AppError without a web framework)
```

| Layer | Folder | Job | Allowed | Forbidden |
| --- | --- | --- | --- | --- |
| HTTP | `app/api/`, `app/main.py`, `app/presenters.py` | Receive the request, check its shape, find out who is calling, map the result to a response | Call services; use schemas; read the token; choose status codes; apply presenters | Business rules (paging policy, 404 rules, role rules); calling repository methods; SQL; importing a database driver |
| Service | `app/services/` | Own every rule: state machine, roles, preconditions, orchestration | Call the repository interface; call the AI layer; raise `AppError`; read settings | Importing `fastapi`, `starlette`, `app.api` or `app.presenters`; writing SQL; knowing which database is used |
| Repository | `app/repositories/` | Read and write data; migrations | SQL through the driver; mapping rows to records; one implementation per backend (memory for tests, PostgreSQL) | Business rules; roles; importing services, api or `fastapi`; deciding what is allowed |
| AI | `app/ai/` | Talk to models | Call providers; validate model output shape | Reading the repository; building HTTP responses |
| Contracts | `app/schemas/` | Request and response shapes | Pydantic only | Any I/O |

Authentication and authorization are separate jobs. The HTTP layer answers
"who are you?" (token to actor). The service layer answers "what may you do?"
and checks it on every call, so no entry point (HTTP, chat agent, script) can
skip a rule.

### 3.2 Top three qualities

| Quality | Why it matters here | How it is checked |
| --- | --- | --- |
| Security | Agents and model output are untrusted; one missed check lets an agent approve its own work | 401/403 tests, OWASP checklist, no SQL outside the repository |
| Testability | The state machine is the product; its rules must run without a web server or a database | Service tests with the in-memory repository |
| Maintainability | Rules live in one place; replacing the database touches one layer; agents get clear limits for what they may edit | Architecture test on imports (enforcing) |

What we give up: some raw speed and a little extra code (interfaces, one more
folder) in return for clear boundaries.

### 3.3 Chosen style

A layered monolith: one FastAPI process, one PostgreSQL database, no message
queue. Creating all cards of a breakdown must be atomic, which is simplest in
one database transaction. Breakdown and chat run inside the request with a
deadline (section 10), so no separate worker exists. If breakdown regularly
exceeds the deadline, or jobs must survive a restart, add a worker and queue
through a new ADR.

### 3.4 Rejected options

| Option | Why not now | What would change the decision |
| --- | --- | --- |
| Microservices | Breakdown needs all-or-nothing card creation; splitting adds network failures and distributed transactions for one small team | Independent scaling or separate teams |
| Event-driven with queue and worker | No work is longer than the request deadline today; harder to test and debug | Jobs longer than the deadline or that must survive restarts |
| Hexagonal (ports and adapters) everywhere | Same dependency direction, but more interfaces than this size needs; we keep its one useful part, the repository interface | Many more external systems |
| Modular monolith by feature | Valid, but code and tests are organised by layer; regrouping would be a rewrite with no new behaviour | The codebase grows into many independent features |

### 3.5 Known violations

The 3.1 table is enforced by tests/test_architecture.py. Injection points
(app/main.py and app/api/deps.py) are an explicit allowlist, and
app/presenters.py is a named known debt. Open debts are tracked in
docs/ROADMAP.md as S8.9 and S8.11.

## 4. Request lifecycle

1. **CORS middleware** (`app/main.py`) allows exactly `FRONTEND_ORIGIN`, the
   methods the API uses, and the `Authorization`/request-id headers.
2. **Request-id middleware** echoes an incoming `X-Request-Id` (truncated to 64
   characters) or generates a 12-character hex id, and attaches it to every
   response, including errors.
3. **Dependency resolution** (`app/api/deps.py`) reads `Authorization: Bearer`,
   verifies the token through `services/auth.py`, then resolves the actor in the
   store. The token's `role` claim must match the stored actor's role; a
   mismatch is a 401 `invalid_token` with `WWW-Authenticate: Bearer`, so a
   signed token cannot claim a role the store does not grant. Missing or
   invalid tokens give 401 `missing_token` / `invalid_token`; `require_human`
   adds a 403 `human_only` gate. A legacy `X-Actor-Id` header is ignored, as is
   any `actor` field in a body.
4. **Body validation** by Pydantic. `extra="forbid"` everywhere means a typo or
   an attempt to set an internal field is a 422, not a silent no-op.
5. **Service call.** The service loads records, applies rules, mutates through
   the store, and writes an audit entry.
6. **Presentation.** `app/presenters.py` resolves actor ids to full actors and
   builds `CardRead` / `CommentRead`. Internal fields such as `built_by` never
   cross this boundary.
7. **Error translation.** `app/errors.py` installs handlers for `AppError`,
   Pydantic validation errors, Starlette HTTP errors and unexpected exceptions.
   Every failure has the same envelope.
8. **Response.** The request id is added on the way out.

## 5. Module map

```
app/
  main.py            app factory, middleware, routers, lifespan-free state
  config.py          frozen Settings read from environment (once)
  errors.py          AppError and the four exception handlers
  repositories/
    memory.py        dictionaries + RLock, audit log, seeded actors (tests)
    postgres.py      PostgreSQL tables, parameterised queries, SQLAlchemy Core
    factory.py       build_repository: Postgres when DATABASE_URL is set, else memory
  actors.py          six seeded identities (three humans, three agents)
  presenters.py      record -> public model
  rate_limit.py      sliding-window limiter, in-process
  api/
    deps.py          store/settings/registry/limiter, token identity and actors
    auth.py          login and current identity
    meta.py          health, actors, meta
    cards.py         CRUD, list, transition
    comments.py      list/add
    assignment.py    set/clear assignee
    prds.py          create/list/get/breakdown
  services/
    cards.py         transition matrix, guardrails, card/PRD rules
    breakdown.py     timeout, retries, fallback, injection, atomic creation
    auth.py          Argon2 hashing, HS256 tokens, initial users
  ai/
    prompts.py       v1 (naive) and v2 (strict) prompts
    registry.py      provider map and ordered fallback
    tokens.py        token and cost estimates
    safety.py        injection scan and neutralisation
    embeddings.py    hashing embedder, cosine, ranking
    providers/
      base.py        ProviderOutput / ProviderError / Protocol
      mock.py        deterministic offline quality tiers
      openrouter.py  OpenAI-compatible HTTP client
  schemas/           actors, auth, cards, prds, common error envelope
  web/               console.* and chat/* (static, no build)
  scripts/
    setup_auth.py    user-run creation of the two initial users
```

## 6. Endpoints

| Method | Path | Actor | Success | Main failures |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 | - |
| POST | `/api/v1/auth/login` | none | 200 | 401 `invalid_credentials`, 500 `auth_misconfigured` |
| GET | `/api/v1/auth/me` | token | 200 | 401 `missing_token` / `invalid_token` |
| GET | `/api/v1/actors` | token | 200 | 401 |
| GET | `/api/v1/meta` | token | 200 | 401 |
| POST | `/api/v1/cards` | human | 201 | 401, 403 `human_only`, 422 |
| GET | `/api/v1/cards` | token | 200 | 401, 422 (bad paging) |
| GET | `/api/v1/cards/{id}` | token | 200 | 401, 404 |
| PATCH | `/api/v1/cards/{id}` | human | 200 | 401, 403, 404, 409 `spec_locked`, 422 |
| DELETE | `/api/v1/cards/{id}` | human | 204 | 401, 403, 404 |
| POST | `/api/v1/cards/{id}/transition` | human or agent | 200 | 401, 403, 404, 409, 422 |
| GET | `/api/v1/cards/{id}/comments` | token | 200 | 401, 404 |
| POST | `/api/v1/cards/{id}/comments` | human or agent | 201 | 401, 404, 422 |
| PUT | `/api/v1/cards/{id}/assignee` | human | 200 | 401, 403, 404, 409 `card_closed`, 422 |
| POST | `/api/v1/prds` | human | 201 | 401, 403, 422 `prd_too_large` |
| GET | `/api/v1/prds` | token | 200 | 401 |
| GET | `/api/v1/prds/{id}` | token | 200 | 401, 404 |
| POST | `/api/v1/prds/{id}/breakdown` | human | 201 | 401, 403, 404, 422, 429, 502, 504 |
| GET | `/api/v1/chat/models` | token | 200 | 401, 502 |
| POST | `/api/v1/chat/completions` | token | 200 (SSE) | 400 `invalid_json`/`invalid_body`/`invalid_messages`, 401, 422 `invalid_payload`, 429 `rate_limited`, 502 |
| POST | `/api/v1/chat/confirm` | token | 200 | 400, 401, 403 `invalid_proposal`/`forbidden`, 409 `proposal_used`, 422 |
| GET | `/console` | none | 200 | - (static console, outside OpenAPI) |
| GET | `/chat` | none | 200 | - (static chat, outside OpenAPI) |

All API routes except `/api/v1/health` require a valid bearer token. Roles are
still checked in services, so the token only establishes identity; see ADR 0009.
Workspace scoping remains a later step (ADR 0002).

The console and chat pages are mounted from `app/web/` with `StaticFiles` under
`/console/assets` and `/chat/assets`. Both are excluded from OpenAPI because
they are not part of the API contract; they sign in through `/auth/login`, keep
the token under `zm.token`, and send it on every API call, so the server's rules
stay authoritative.

Chat flow (Z-1/Z-2): `POST /api/v1/chat/completions` validates limits (max 30
messages, 8000 chars/message, 24000 total, allowed model, capped `max_tokens`,
per-actor rate limit). Read-only tools run immediately and emit `gantry_tool`
frames. Write tools emit signed `gantry_proposal` frames and do not execute;
`POST /api/v1/chat/confirm` verifies the proposal token, actor, arguments hash,
and used-id set, then executes the same service function under normal service
rules.

## 7. The state machine

```
            human                agent                agent
  Spec -----------> Ready -----------> Building -----------> Checks
   ^                  |                                       |
   |    human         |                   human               | human
   +------------------+              +----------------------> Validation
                                     |    human                  |
                                     |                           | human
                                     +---- Building <------------+
                                                                 |
                                                                 v
                                                                Done
```

Formal matrix (`ALLOWED_TRANSITIONS` in `app/services/cards.py`):

| From | To | Actor | Effect |
| --- | --- | --- | --- |
| spec | ready | human | spec approved |
| ready | spec | human | sent back for rework |
| ready | building | human or agent | records `built_by`; claims an unassigned card |
| building | checks | human or agent | submitted for review |
| checks | validation | human | checks accepted |
| checks | building | human | defects found |
| validation | done | human | accepted, unless the actor is the builder |
| validation | building | human | rejected |

Everything else is `409 illegal_transition`, including moving to the current
stage and any move out of `done`.

### Guardrails

| Rule | Enforced in | Failure |
| --- | --- | --- |
| Closed stage enum and edge list | `services/cards.py` | 409 `illegal_transition` |
| Agents may only take `ready→building`, `building→checks` | `HUMAN_ONLY_TRANSITIONS` | 403 `agent_not_allowed` |
| An agent never moves a card to `Done` | `transition_card` explicit target check | 403 `agent_not_allowed` |
| An agent works only its own card | `transition_card` | 403 `not_assignee` |
| The builder cannot validate its own card | `built_by` comparison | 403 `self_validation_blocked` |
| Creating/editing/deleting/assigning/PRDs/breakdown is human-only | `require_human` + service | 403 `human_only` |
| The spec is editable only in `spec` | `update_spec` | 409 `spec_locked` |
| A card in `done` cannot be reassigned | `assign_card` | 409 `card_closed` |
| At most one assignee | `AssigneeUpdate` + store field | shape-level |
| Model output is bounded and sound | `schemas/prds.py`, `_validate_output` | retry, then 502 |

The guardrail order matters and is tested: for an agent trying to validate, the
human-only check fires before the self-validation check, so the error code is
`agent_not_allowed`, not `self_validation_blocked`. The explicit `Done` check
sits between the human-only edge check and the assignee check, so it holds even
if a future edge into `Done` is not marked human-only.

## 8. Error model

Every failure, including framework-level ones, looks like:

```json
{"error": {"code": "illegal_transition", "message": "...", "details": {...}}}
```

`details` is optional and never contains stack traces, SQL or model prompts.

| Status | Code | Meaning |
| --- | --- | --- |
| 401 | `missing_token` | no `Authorization` header |
| 401 | `invalid_token` | bad scheme, signature, claims, issuer, expiry, unknown actor or role mismatch |
| 401 | `invalid_credentials` | wrong username or password at login |
| 500 | `auth_misconfigured` | signing secret shorter than 32 characters |
| 403 | `human_only` | an agent tried a human action |
| 403 | `agent_not_allowed` | an agent tried a human-only edge |
| 403 | `not_assignee` | an agent tried another actor's card |
| 403 | `self_validation_blocked` | the builder tried to pass validation |
| 404 | `card_not_found` / `prd_not_found` / `not_found` | missing resource or path |
| 405 | `method_not_allowed` | wrong verb |
| 409 | `illegal_transition` | edge outside the matrix |
| 409 | `spec_locked` | editing a card after Spec |
| 409 | `card_closed` | reassigning a Done card |
| 422 | `invalid_payload` | schema failure, with field-level details |
| 422 | `unknown_assignee` / `unknown_model` / `unknown_prompt_version` | value not in the configured set |
| 422 | `prd_too_large` | PRD over `MAX_PRD_CHARS` |
| 429 | `rate_limited` | breakdown budget spent, with `Retry-After` |
| 500 | `internal_error` | unexpected; logged with the request id, details hidden |
| 502 | `provider_error` | every model attempt failed; zero cards written |
| 504 | `provider_timeout` | the breakdown deadline fired; zero cards written |

The code is the contract. The message is for humans and may change. Tests assert
codes, not prose.

## 9. Data model and invariants

| Record | Key fields | Invariants |
| --- | --- | --- |
| `CardRecord` | id, title, goal, criteria, stage, assignee, created_by, prd_id, depends_on, built_by, version, timestamps | `stage` is a `Stage`; `version` increments on every mutation; `built_by` is internal |
| `CommentRecord` | id, card_id, author_id, body, created_at | append-only; never mutates the card; deleted with the card |
| `PRDRecord` | id, title, body, created_by, created_at | body immutable after creation |
| `UserRecord` | username, actor_id, role, password_hash | unique username; hash only, never plaintext; role maps to a seeded actor |
| `AuditEntry` | event, subject_id, actor_id, at, extra | append-only; records transitions, assignment, comments, PRDs |

Cards are ordered by `(created_at, id)` so two cards created in the same
microsecond still have a deterministic order. PRDs and audit reads are newest
first.

`depends_on` stores **titles**, not ids, because draft ids do not exist until the
whole breakdown is accepted. `Breakdown._graph_is_sound` proves uniqueness,
dependency existence and acyclicity before anything is written.

## 10. The breakdown pipeline

```
POST /prds/{id}/breakdown
  -> require human
  -> rate limiter (per actor)
  -> load PRD (404)
  -> resolve prompt version (422)
  -> registry.ordered(model) -> [primary, fallback]
  -> scan + neutralise injected instructions
  -> asyncio.timeout(deadline)
        for each model:
            for attempt in 0..retries:
                provider.generate(...)
                validate Breakdown (schema + graph + cap + injection)
        winner = first valid output
  -> no winner: 502, nothing written
  -> winner: create all cards in one pass, present, return usage
```

Important properties:

- **Atomicity.** Cards are created only after a valid output exists. A failure
  leaves the store unchanged; tests assert the card count before and after.
- **Bounded.** One deadline wraps every attempt, so a slow provider cannot hold
  the request past `BREAKDOWN_TIMEOUT_SECONDS`.
- **Honest.** `model_used`, `fallback_used`, `attempts`, `warnings`, token
  estimates and cost are in the response. A fallback is never silent.
- **Injection-aware.** Instructions in the PRD are removed before the model sees
  the body, detected labels are reported in `warnings`, and any instruction-like
  text in the output invalidates that attempt.

Failure modes: `ProviderError`/timeouts are retryable; schema and graph failures
are retryable with a different sample; both models failing produce 502; the
deadline produces 504; the limiter produces 429.

## 11. Configuration

Read once in `Settings.from_env()`. Tests build their own `Settings`, so no
global patching is needed.

| Variable | Default | Effect |
| --- | --- | --- |
| `APP_ENV` | `local` | label only |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | the only CORS origin |
| `JWT_SECRET` | unset | HS256 signing key; at least 32 characters, required for login |
| `TOKEN_TTL_SECONDS` | `3600` | token lifetime |
| `GANTRY_HUMAN_PASSWORD` | unset | used once by `scripts/setup_auth.py` for `ada` |
| `GANTRY_AGENT_PASSWORD` | unset | used once by `scripts/setup_auth.py` for `builder` |
| `BREAKDOWN_TIMEOUT_SECONDS` | `15` | whole-call deadline |
| `BREAKDOWN_RATE_LIMIT` | `5` | requests per actor per window |
| `BREAKDOWN_RATE_WINDOW_SECONDS` | `60` | window length |
| `MAX_PRD_CHARS` | `20000` | PRD body limit |
| `MAX_CARDS_PER_BREAKDOWN` | `10` | output cap |
| `MODEL_RETRIES` | `2` | attempts per model |
| `DEFAULT_PROMPT_VERSION` | `v2` | prompt when the request omits one |
| `MODEL_PRIMARY` | `mock-strong` | first model tried |
| `MODEL_FALLBACK` | `mock-fast` | second model tried |
| `OPENROUTER_API_KEY` | unset | enables real models |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | fixed upstream |

The two `GANTRY_*_PASSWORD` variables are read by the user-run bootstrap script,
not by the app; no credential is compiled into the server.

## 12. Security checklist (OWASP API Top 10, 2025)

| ID | Risk | Gantry position | Gap / next step |
| --- | --- | --- | --- |
| A01 | Broken Access Control | Roles are checked in services on every call; agents never reach `done`; default deny | None |
| A02 | Security Misconfiguration | Single CORS origin, no debug flag, `.env` gitignored | Add security headers at the proxy |
| A03 | Software Supply Chain Failures | Versions pinned in `requirements.txt`; browser CDN assets in `app/web` are pinned and verified (SRI or vendored locally) | Z-7 remains open; nine spec questions remain open |
| A04 | Cryptographic Failures | Argon2id-hashed passwords; `JWT_SECRET` only in `.env`; placeholder/weak secrets rejected at startup/auth path (500 `auth_misconfigured`, no detail) | Nine spec questions remain open |
| A05 | Injection | Parameterised queries only; `app/ai/safety.py` scans model prompts | None |
| A06 | Insecure Design | The builder cannot validate its own card; no design-level bypass; chat write tools return signed proposals and execute only after human confirmation via `/api/v1/chat/confirm`; chat input/models/tokens/rate are limited | Z-1 and Z-2 fixed; remaining gaps Z-7, Z-8, Z-9, Z-11 and the nine spec questions remain open |
| A07 | Authentication Failures | Hashed login, expiring tokens, per-client-IP and per-username-and-IP login rate limits, browser token kept only in memory (no localStorage), role read from repository on every request; unknown-user login does dummy argon2 verify | Week 7: Redis limiter shared across workers; Z-11 remains open |
| A08 | Software or Data Integrity Failures | Alembic migrations only; no backup endpoint | Verify a backup before restore |
| A09 | Security Logging and Alerting Failures | `audit_log` records transitions and `auth.login_failed` | None |
| A10 | Mishandling of Exceptional Conditions | Uniform error envelope; `details` carries no file paths or SQL; chat error frames/logs do not expose raw upstream/exception text | Z-1, Z-2 remain open; nine spec questions remain open |

### S15 audit findings

The S15 audit (`step/S15-owasp-audit`) closed the two real gaps and recorded the
rest:

| Finding | OWASP | Decision | Where |
| --- | --- | --- | --- |
| Login had no rate limit | A07 | Fixed | `app/api/auth.py`, `app/api/deps.py`, `app/main.py`, `app/config.py` |
| Failed logins were not audited | A09 | Fixed | `app/services/auth.py` |
| Placeholder `JWT_SECRET` in `.env.example` | A04 | Fixed in S20 (placeholder/weak secrets rejected, 500 `auth_misconfigured`, no detail) | `app/services/auth.py`, `.env.example` |
| Old `prd_id` finding in `docs/ROADMAP.md` | A06/A10 | Closed as obsolete | `CardCreate` has no `prd_id`; breakdown validates with `get_prd_or_404` |

The review is reproducible with the read-only subagent in
`.opencode/agents/security-reviewer.md`:

```text
Use the security-reviewer subagent to review the diff of this branch against the OWASP checklist. List findings with file:line. Fix the ones I approve.
```

Additional hygiene:

- The OpenRouter key is read from the environment and never logged or returned.
- Passwords and `JWT_SECRET` come from the environment too; neither is logged,
  returned or committed. Test fixtures use fake values only.
- `Settings` is frozen; there is no runtime path that changes limits.
- The mock providers are the default, so a missing key degrades to a documented
  offline mode instead of a crash at request time.
- Every mutation writes an audit entry with the actor id and timestamp, and a
  failed login writes `auth.login_failed`.

## 13. Observability

- **Request id** on every response, echoed from the client when supplied, so a
  browser error can be matched to a server log line.
- **Audit log** in the store: `card.created`, `card.updated`, `card.transitioned`,
  `card.assigned`, `card.deleted`, `comment.created`, `prd.created` and
  `auth.login_failed`, each with actor, subject, timestamp and relevant extras.
- **Breakdown warnings** carry per-attempt failures, injection labels, fallback
  and attempt counts to the caller.
- Unexpected exceptions are logged with `logger.exception`, and the client only
  receives `internal_error`.

There are no metrics or traces yet. The natural next step is a request counter
and a breakdown latency histogram per model.

## 14. Known limits and the week 4+ path

| Limit | Consequence | Planned change |
| --- | --- | --- |
| In-memory repository (tests) | Data disappears on restart by design; one process only | PostgreSQL via `DATABASE_URL` is the durable store |
| Token lifetime only | Tokens expire but cannot yet be revoked or refreshed; only `ada` and `builder` have accounts | Add refresh, revocation and user management |
| In-process limiter | Limits are per worker | Redis in week 7 |
| No frontend | API-only | Vue board in week 4 |
| Mock models by default | Quality numbers describe the harness, not a vendor | Run the same evals with real ids |
| Hashing embeddings | Lexical matching only | pgvector + a real embedding model |
| Alembic migrations are user-run | Schema changes are not applied automatically | Keep migrations reviewed and run them before `setup_auth.py` |

PostgreSQL is the durable store; the in-memory repository is for tests and quick
local runs. The interfaces are drawn so these replacements do not touch the HTTP
layer: the store is behind methods, providers behind a protocol, and limits behind
`SlidingWindowLimiter`.
