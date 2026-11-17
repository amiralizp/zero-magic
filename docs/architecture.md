# Architecture

**Status:** weeks 1-3 complete (cards, comments, assignment, PRD breakdown) plus a build-free console
**Last reviewed:** 2026-11-17
**Out of scope for this version:** the week-4 Vue frontend, PostgreSQL, Docker, authentication

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

## 2. Context

```
Console page              curl / PowerShell          evals + scripts
app/web/ (no build)              |                        |
        |                        |                        |
        +-------- HTTP ----------+------------------------+
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
             Store                      Mock providers (default)
             app/db.py picks:           OpenRouter provider (opt-in)
             memory or SQL Server
```

There is no external service in the default configuration. That is deliberate:
the repo runs offline, tests are deterministic, and no key is required to review
the work.

## 3. Layers and the rules between them

| Layer | Files | May know about | Must not |
| --- | --- | --- | --- |
| HTTP | `app/api/*.py`, `app/main.py` | schemas, services, errors | contain business rules or touch dicts |
| Service | `app/services/cards.py`, `app/services/breakdown.py` | store, schemas, AI layer, settings | build HTTP responses |
| Store | `app/store.py`, `app/store_sql.py`, `app/db.py` | schemas, actors | enforce permissions or transitions |
| AI | `app/ai/*` | schemas for model output | read the store or raise `AppError` (except the registry) |
| Contracts | `app/schemas/*` | Pydantic only | perform I/O |

The important line is between HTTP and service. Routers translate a request to
typed arguments and a result to a response model; the service owns every rule
that a reviewer would call "the business logic". A test can therefore exercise
the state machine without HTTP, and the eval harness can call a provider without
starting the app.

`app/services/cards.py` is the single owner of the transition matrix. If it is
not in that file, it is not a rule.

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
| Repository | `app/repositories/` (today `app/store.py`, `app/store_sql.py`, `app/db.py`, `app/backup.py`) | Read and write data; migrations | SQL through the driver; mapping rows to records; one implementation per backend (memory for tests, PostgreSQL) | Business rules; roles; importing services, api or `fastapi`; deciding what is allowed |
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
| Maintainability | Rules live in one place; replacing the database touches one layer; agents get clear limits for what they may edit | Architecture test on imports (planned, S7) |

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

`docs/critique.md` lists where the code does not yet follow 3.1. Until S8 the
3.1 table is the target, not a description of the code. Planned enforcement:
`tests/test_architecture.py` (S7) checks imports, and S8 removes the violations.

## 4. Request lifecycle

1. **CORS middleware** (`app/main.py`) allows exactly `FRONTEND_ORIGIN`, the
   methods the API uses, and the actor/request-id headers.
2. **Request-id middleware** echoes an incoming `X-Request-Id` (truncated to 64
   characters) or generates a 12-character hex id, and attaches it to every
   response, including errors.
3. **Dependency resolution** (`app/api/deps.py`) reads `X-Actor-Id`, looks the
   actor up in the store, and returns 401 `missing_actor` / `unknown_actor` when
   identity is absent or unknown. `require_human` adds a 403 `human_only` gate.
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
  store.py           dictionaries + RLock, audit log, seeded actors (tests)
  store_sql.py       SQL Server tables, parameterised queries, connection pool
  db.py              build_store: memory when DB_USER is empty, SQL otherwise
  actors.py          six seeded identities (three humans, three agents)
  presenters.py      record -> public model
  rate_limit.py      sliding-window limiter, in-process
  api/
    deps.py          store/settings/registry/limiter, actor identity
    meta.py          health, actors, meta
    cards.py         CRUD, list, transition
    comments.py      list/add
    assignment.py    set/clear assignee
    prds.py          create/list/get/breakdown
  services/
    cards.py         transition matrix, guardrails, card/PRD rules
    breakdown.py     timeout, retries, fallback, injection, atomic creation
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
  schemas/           actors, cards, prds, common error envelope
  web/               console.html, console.css, console.js (static, no build)
```

## 6. Endpoints

| Method | Path | Actor | Success | Main failures |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 | - |
| GET | `/api/v1/actors` | none | 200 | - |
| GET | `/api/v1/meta` | none | 200 | - |
| POST | `/api/v1/cards` | human | 201 | 401, 403 `human_only`, 422 |
| GET | `/api/v1/cards` | none | 200 | 422 (bad paging) |
| GET | `/api/v1/cards/{id}` | none | 200 | 404 |
| PATCH | `/api/v1/cards/{id}` | human | 200 | 403, 404, 409 `spec_locked`, 422 |
| DELETE | `/api/v1/cards/{id}` | human | 204 | 403, 404 |
| POST | `/api/v1/cards/{id}/transition` | human or agent | 200 | 403, 404, 409, 422 |
| GET | `/api/v1/cards/{id}/comments` | none | 200 | 404 |
| POST | `/api/v1/cards/{id}/comments` | human or agent | 201 | 401, 404, 422 |
| PUT | `/api/v1/cards/{id}/assignee` | human | 200 | 403, 404, 409 `card_closed`, 422 |
| POST | `/api/v1/prds` | human | 201 | 401, 403, 422 `prd_too_large` |
| GET | `/api/v1/prds` | none | 200 | - |
| GET | `/api/v1/prds/{id}` | none | 200 | 404 |
| POST | `/api/v1/prds/{id}/breakdown` | human | 201 | 403, 404, 422, 429, 502, 504 |
| GET | `/console` | none | 200 | - (static console, outside OpenAPI) |

Read endpoints are public *in this iteration*. They become workspace-scoped when
authentication lands in week 6; see ADR 0002.

The console is mounted from `app/web/` with `StaticFiles` under
`/console/assets`. It is deliberately excluded from OpenAPI because it is not
part of the API contract; every action it takes goes through the endpoints above
with the selected `X-Actor-Id`, so the server's rules stay authoritative.

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
| An agent works only its own card | `transition_card` | 403 `not_assignee` |
| The builder cannot validate its own card | `built_by` comparison | 403 `self_validation_blocked` |
| Creating/editing/deleting/assigning/PRDs/breakdown is human-only | `require_human` + service | 403 `human_only` |
| The spec is editable only in `spec` | `update_spec` | 409 `spec_locked` |
| A card in `done` cannot be reassigned | `assign_card` | 409 `card_closed` |
| At most one assignee | `AssigneeUpdate` + store field | shape-level |
| Model output is bounded and sound | `schemas/prds.py`, `_validate_output` | retry, then 502 |

The guardrail order matters and is tested: for an agent trying to validate, the
human-only check fires before the self-validation check, so the error code is
`agent_not_allowed`, not `self_validation_blocked`.

## 8. Error model

Every failure, including framework-level ones, looks like:

```json
{"error": {"code": "illegal_transition", "message": "...", "details": {...}}}
```

`details` is optional and never contains stack traces, SQL or model prompts.

| Status | Code | Meaning |
| --- | --- | --- |
| 401 | `missing_actor` / `unknown_actor` | no or unregistered `X-Actor-Id` |
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

## 12. Security checklist (OWASP API Top 10, 2023)

| Risk | Current position | Gap / next step |
| --- | --- | --- |
| API1 Broken object level authorisation | No cross-tenant objects exist yet; ids are unguessable random hex | Week 6: workspace membership check on every read/write |
| API2 Broken authentication | Explicit temporary header identity, documented as insecure; unknown ids are 401 | Week 6: real sessions, hashed passwords, expiry |
| API3 Broken object property authorisation | `CardRead` whitelists fields; `built_by` and history never serialised; `extra="forbid"` blocks mass assignment | Add response tests per new field |
| API4 Unrestricted resource consumption | Per-actor rate limit, 20k PRD cap, 10-card cap, 15 s deadline, 2k comment cap, paging cap | Week 7: Redis limiter shared across workers |
| API5 Broken function level authorisation | `require_human`, agent-only edges, agent assignment rule | Add role matrix tests when roles multiply |
| API6 Unrestricted business flows | Closed state machine, no skip edges, self-validation block, one assignee | Add per-actor transition rate limit if abuse appears |
| API7 SSRF | No user-supplied URLs; the only outbound host is `OPENROUTER_BASE_URL` | Never let a request override the base URL |
| API8 Security misconfiguration | Single CORS origin, no `*`, unexpected errors return a generic body, no debug flag, no secrets in logs | Add security headers at the proxy |
| API9 Improper inventory management | OpenAPI at `/docs` and `/openapi.json`; `/api/v1/meta` lists stages, edges, models and limits | Version the API before week 4 frontend work |
| API10 Unsafe consumption of third-party APIs | Model output is schema-validated and graph-checked; injection is scanned; prompts treat PRD text as data | Add output moderation and per-model budgets |

Additional hygiene:

- The OpenRouter key is read from the environment and never logged or returned.
- `Settings` is frozen; there is no runtime path that changes limits.
- The mock providers are the default, so a missing key degrades to a documented
  offline mode instead of a crash at request time.
- Every mutation writes an audit entry with the actor id and timestamp.

## 13. Observability

- **Request id** on every response, echoed from the client when supplied, so a
  browser error can be matched to a server log line.
- **Audit log** in the store: `card.created`, `card.updated`, `card.transitioned`,
  `card.assigned`, `card.deleted`, `comment.created`, `prd.created`, each with
  actor, subject, timestamp and relevant extras.
- **Breakdown warnings** carry per-attempt failures, injection labels, fallback
  and attempt counts to the caller.
- Unexpected exceptions are logged with `logger.exception`, and the client only
  receives `internal_error`.

There are no metrics or traces yet. The natural next step is a request counter
and a breakdown latency histogram per model.

## 14. Known limits and the week 4+ path

| Limit | Consequence | Planned change |
| --- | --- | --- |
| Process-local store | Data disappears on restart; one process only | PostgreSQL + migrations in week 5 |
| Header identity | Anyone can claim any seeded actor | Login and sessions in week 6 |
| In-process limiter | Limits are per worker | Redis in week 7 |
| No frontend | API-only | Vue board in week 4 |
| Mock models by default | Quality numbers describe the harness, not a vendor | Run the same evals with real ids |
| Hashing embeddings | Lexical matching only | pgvector + a real embedding model |
| No migration framework | Schema changes are code changes | Alembic with the database |

The interfaces are drawn so these replacements do not touch the HTTP layer: the
store is behind methods, providers behind a protocol, and limits behind
`SlidingWindowLimiter`.
