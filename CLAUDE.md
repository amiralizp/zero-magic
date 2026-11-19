# CLAUDE.md

This repository's agent guide is [`AGENTS.md`](AGENTS.md). Read it first. The
short version:

## Run

```powershell
cd zero-magic
& .venv\Scripts\python.exe -m pytest
& .venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Do not run `python app/main.py`; it fails on relative imports (BUG-001 in
`docs/test-plan.md`).

The build-free console is served at `/console` from `app/web/`; it uses only the
same HTTP API and adds no build step or dependency.

## Non-obvious rules

- The funnel's transition matrix and human-only edges live in
  `app/services/cards.py`. Routers must not encode rules.
- Agents may only take `ready -> building` and `building -> checks`. Never let an
  agent approve a spec, accept checks, send a card back, or reach `done`.
- The actor that built a card cannot validate it (`built_by` check).
- Every error goes through `AppError` and the envelope in `app/errors.py`.
- Keep `extra="forbid"` on Pydantic models and never serialise `built_by`.
- Model output is validated, capped, timed out and injection-checked. Do not
  bypass `app/services/breakdown.py`.
- A failed breakdown writes zero cards.
- The default providers are deterministic mocks. Their eval scores are not
  evidence about a real model.
- Tests must not call real APIs or need a key.

## Before you finish

1. `python -m pytest` is green (currently 167 tests).
2. If you changed a rule, update `/api/v1/meta`, `docs/architecture.md` and the
   relevant spec.
3. If you changed a prompt or provider, regenerate the eval report and check the
   gate in `tests/test_evals.py`.
4. Update `README.md` if a command, endpoint or limit changed.

## Architecture (week 4)

Follow docs/architecture.md section 3.1 and the ADRs in docs/adr/. Direction:
HTTP -> Service -> Repository -> database. No business rule in routers, no SQL
or fastapi in services, no rules in the repository. Do not change error codes
or status codes. Never edit a test just to make it pass. Never touch .env.
Before finishing: pytest -q green and the docs updated.
