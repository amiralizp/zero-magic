# AGENTS.md

Guidance for coding agents and new contributors working on Gantry in
`zero-magic/`.

## What this is

Gantry is a FastAPI backend for an agentic development funnel, weeks 1-3 of an
internship plan. Cards move through a strict lifecycle; humans approve and
validate, agents build. Week 3 adds PRD-to-cards breakdown with a model that is
validated, retried, rate-limited and scored. A build-free console at `/console`
exercises the same HTTP API.

Not present yet: Docker, authentication, the week-4 frontend, PostgreSQL. Persistence is
SQL Server when `DB_USER` is set and the in-memory repository otherwise; both live
behind one interface (`app/repositories/factory.py` picks). The console in `app/web/` is a
convenience page, not that frontend; do not add a bundler or a new dependency
for it.

## Commands

Windows PowerShell, from `zero-magic/`:

```powershell
& .venv\Scripts\python.exe -m pytest
& .venv\Scripts\python.exe -m pytest tests\test_stage_machine.py -q
& .venv\Scripts\python.exe -m evals.run_evals
& .venv\Scripts\python.exe scripts\compare_models.py
& .venv\Scripts\python.exe scripts\embedding_ranking.py
& .venv\Scripts\python.exe scripts\agent_loop.py
& .venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Database migrations (user-run, need `DATABASE_URL` in the environment):
```powershell
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe -m alembic downgrade -1
& .venv\Scripts\python.exe -m alembic current
```
Run these yourself, not through an agent.

There is no Makefile. `python -m` is preferred for modules; `uvicorn app.main:app`
is the supported server entry point. Never run `python app/main.py` (see
BUG-001 in `docs/test-plan.md`).

## Hard constraints

1. **The state machine lives in `app/services/cards.py`.** Do not add transition
   rules to routers, schemas or the store. Update `ALLOWED_TRANSITIONS` and
   `HUMAN_ONLY_TRANSITIONS` together, and update `/api/v1/meta` and the
   parametrised tests.
2. **Human-only edges are non-negotiable.** Agents may only take
   `ready -> building` and `building -> checks`. Approving a spec, accepting
   checks, sending back and validating are human actions.
3. **The builder cannot validate its own card.** Keep the `built_by` check, and
   keep the guard order: legal edge (409), human-only (403), assignee (403),
   self-validation (403).
4. **Every failure uses `AppError` and the envelope** from `app/errors.py`:
   `{"error": {"code", "message", "details"?}}`. Codes are the contract; do not
   change one without a test and a note.
5. **Schemas are strict.** Keep `extra="forbid"` on request and model-output
   models. Public card models must not expose `built_by` or history.
6. **Model output is untrusted.** Any new provider must return a validated
   `Breakdown`. Do not bypass `_validate_output`, the card cap, the deadline or
   the injection check.
7. **Atomicity.** A breakdown creates cards only after a valid output exists. A
   failure must leave the store unchanged.
8. **No secrets in code, logs or responses.** The OpenRouter key comes from the
   environment; never print it.
9. **CORS stays a single origin.** No `allow_origins=["*"]`.
10. **The mocks are not models.** Any doc or comment that reports their scores
    must say so.

## Architecture map

| Concern | File |
| --- | --- |
| App factory, middleware, routers | `app/main.py` |
| Settings from env | `app/config.py` |
| Error types and handlers | `app/errors.py` |
| In-memory repository and audit log | `app/repositories/memory.py` |
| SQL Server repository, schema, pool | `app/repositories/sql_server.py` |
| Repository selection from settings | `app/repositories/factory.py` |
| Seeded actors | `app/actors.py` |
| Record -> public model | `app/presenters.py` |
| Actor identity and dependencies | `app/api/deps.py` |
| Routes | `app/api/*.py` |
| Rules | `app/services/cards.py` |
| Breakdown orchestration | `app/services/breakdown.py` |
| Prompts | `app/ai/prompts.py` |
| Providers | `app/ai/providers/` |
| Token and cost estimates | `app/ai/tokens.py` |
| Injection scan | `app/ai/safety.py` |
| Embeddings | `app/ai/embeddings.py` |
| Contracts | `app/schemas/` |
| Evals | `evals/` |
| Interactive console (HTML/CSS/JS) | `app/web/` |
| Demos | `scripts/` |
| Specs | `specs/` |
| Decisions | `docs/adr/` |

Dependency direction is one way: HTTP -> services -> repository/AI -> schemas.
Schemas import nothing from the app except other schemas. The AI layer must not
read the store or build HTTP responses.

## Testing rules

- Every behaviour change gets a test that fails without it.
- Prefer the HTTP level for contracts and the unit level for pure rules.
- Build isolated apps with `tests.helpers.make_client(...)`; pass settings
  explicitly instead of mutating environment variables.
- Never call a real model in the suite. Use the mocks or a local failing/slow
  provider.
- Assert status codes and `error.code`, not message prose.
- Keep the eval gate green. A prompt change that lowers validity is a
  regression, even if the average score rises.
- Run the full suite before finishing: `python -m pytest`.
- The suite must never require SQL Server. Tests use the in-memory store; the
  SQL path is checked by hand against a real server.

## Style

- Python 3.11+, `from __future__ import annotations`, full type hints.
- Small functions, docstrings that explain *why*, comments only where the code
  cannot say it.
- No new runtime dependency without a reason and a note. The current list is
  FastAPI, Uvicorn, Pydantic, httpx, pytest.
- Names follow the domain: card, stage, transition, assignee, PRD, breakdown,
  draft.
- Keep docs and code in the same change when a rule or a command changes.

## Docs to update when you change behaviour

| Change | Update |
| --- | --- |
| Transition edge or actor rule | `docs/architecture.md`, `/api/v1/meta`, tests, `specs/` |
| Endpoint or status code | `README.md`, `docs/architecture.md`, OpenAPI test |
| Prompt or provider | `docs/llm-explainer.md`, `docs/eval-report.md`, eval gate |
| Limit or setting | `README.md`, `.env.example`, `docs/architecture.md` |
| New decision with trade-offs | a new ADR in `docs/adr/` |
| Console page or asset | `README.md`, `tests/test_console.py` |

## Architecture rules (target for week 4; see docs/architecture.md section 3.1)

Read docs/architecture.md and docs/adr/ before changing structure. Dependencies
point one way: HTTP (app/api) -> Service (app/services) -> Repository
(app/repositories) -> database. Until the S8 refactor the code does not follow
this everywhere; docs/critique.md lists the violations. New code must follow it.

- HTTP: receives the request, checks its shape, identifies the caller, maps the
  result to a response. No business rule, no repository call, no SQL.
- Service: owns every rule, including roles. Never import fastapi, starlette,
  app.api, app.presenters or a SQL driver. Do not name a concrete database.
- Repository: the only layer that touches tables. No business rule, no role
  check. Never import services or api.
- AI layer: talks to models only. Never reads the repository.
- AppError lives in a module without a web framework import.
- Authentication (who are you) is HTTP; authorization (what may you do) is
  checked in services on every call.

Never edit or weaken a test to make it pass. If a test and a rule disagree, stop
and ask. Do not read, print or edit .env; never commit .env, backups/ or *.bak.
Do not change the public error codes or status codes: they are the contract.
Make one small change at a time and run `pytest -q` after each module.

## Git protocol (follow exactly)

- Work only on a branch named step/<ID>-<slug> (example: step/S4-architecture). Never commit to main.
- Do ONE roadmap step per session, then stop and wait for me.
- Before any commit run `pytest -q`. If anything is red, stop and report.
- Stage specific files only: `git add <path>`. Never `git add .` or `git add -A`.
- Never stage .env, backups/, .venv, *.bak, *.log.
- Before committing, show me: `git status`, `git diff --stat` and the proposed commit message. Wait for my OK.
- Commit message format: type(scope): short summary. Types: feat, fix, refactor, test, docs, chore.
- After the commit, tick the step in docs/ROADMAP.md.
- Never push, merge, rebase, `reset --hard` or force-push unless I explicitly say so.
- Never edit a test just to make it pass.
