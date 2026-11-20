# Test plan

**Status:** weeks 1-3
**Suite:** 167 tests, all offline, no API key required
**Command:** `& .venv\Scripts\python.exe -m pytest`

## 1. What we are testing

The risk profile of this service is unusual: the code is small, but the failure
that matters is *a wrong actor being allowed to move work forward*. So the test
plan is weighted towards rules and contracts, not line coverage:

1. **Rules.** Which stage edges exist, which actor may take them, what happens
   to a card when it does.
2. **Contracts.** The HTTP status, error code and public shape a client can rely
   on, for both success and failure.
3. **Failure handling.** Bad payloads, unknown ids, provider failure, timeout,
   rate limits, duplicate output, dependency cycles.
4. **Output quality.** A 25-PRD eval suite with a gate, because "the model
   returned something" is not the same as "the cards are usable".

## 2. Strategy

| Level | What it proves | How |
| --- | --- | --- |
| Unit | Pure rules and helpers | Direct calls to validators, limiter, token/cost estimator, safety scan, mock extractor |
| Integration | The API behaves as documented | `TestClient` against a freshly built app with an in-memory store |
| Contract | Clients can branch on status/code/shape | Assertions on status codes, `error.code`, OpenAPI paths and schemas |
| Eval gate | A prompt change did not make output worse | `evals.run_evals` invoked from `tests/test_evals.py` with thresholds |
| Sandbox | The agent runner cannot escape or loop forever | Path traversal, step cap, write limits, end-to-end repair |

Tests do not mock the store, the service or the state machine. Only the model
provider is replaceable, through `create_app(provider_overrides=...)`, so the
failure paths of a real provider can be simulated deterministically.

## 3. Suite inventory

| File | Tests | Focus |
| --- | ---: | --- |
| `test_stage_machine.py` | 25 | Every edge, every illegal edge, actor rules, self-validation, terminal state |
| `test_cards_crud.py` | 20 | Create/read/patch/delete, validation, filters, paging, hidden fields |
| `test_breakdown.py` | 19 | Happy path, limits, fallback, timeout, atomicity, injection, v1 vs v2 |
| `test_http_contracts.py` | 17 | One error envelope, CORS, request ids, OpenAPI, meta, actors |
| `test_comments.py` | 15 | Typed response, every stage, ordering, limits, no card mutation |
| `test_assignment.py` | 15 | Set/clear, unknown ids, human-only, closed cards, filter composition, agent ownership |
| `test_evals.py` | 9 | Metric correctness and the quality gate |
| `test_agent_loop.py` | 8 | Sandbox escapes, step cap, write bounds, end-to-end repair |
| `test_embeddings.py` | 7 | Determinism, normalisation, ranking, real-dataset probes |
| `test_prds.py` | 7 | PRD storage, human-only, size limit, list order |
| `test_units.py` | 21 | Matrix completeness, graph validation, tokens/cost, limiter, extraction |
| `test_scripts.py` | 1 | Demo scripts start when run by path (BUG-001) |
| `test_console.py` | 3 | Console HTML/assets served, linked from root, absent from OpenAPI |
| **Total** | **167** | |

## 4. Determinism and isolation

- `tests/conftest.py` builds a new application and store for every test, so
  tests cannot leak cards into each other.
- The default providers are deterministic mocks. There is no network call in
  the suite.
- Time-sensitive tests use a configurable deadline (`0.05 s`) and a deliberately
  slow provider rather than sleeping for the production timeout.
- The rate-limit test builds an app with `breakdown_rate_limit=1`; it does not
  mutate module state.
- Settings are injected, not read from the developer's environment, so a local
  `.env` cannot change test behaviour.
- The agent-loop test copies the broken example into `tmp_path`; the source
  example is asserted to stay broken.

## 5. Regression gates

| Gate | Threshold | Where |
| --- | --- | --- |
| Suite | 0 failures | `pytest` |
| Breakdown validity (v2, `mock-strong`) | >= 95% | `test_evals.py` |
| Breakdown score (v2, `mock-strong`) | >= 85 / 100 | `test_evals.py` |
| Improvement over v1 | score and testability strictly higher | `test_evals.py` |
| Agent loop size | file under 150 lines | `test_agent_loop.py` |
| Provider failure | 0 cards written, 502/504 | `test_breakdown.py` |
| Self-validation | builder never reaches `done` alone | `test_stage_machine.py` |

A prompt change that raises the score but lowers the valid rate is rejected: the
valid rate is checked first because a breakdown that cannot be stored is worth
zero.

## 6. Bug reports

Three defects were found and fixed during weeks 1-3. They are recorded here
because the fix and the regression test are the deliverable, not the commit.

### BUG-001: Direct file execution crashes on relative imports

| Field | Value |
| --- | --- |
| Severity | Medium (developer experience; blocks a first run) |
| Found | Week 1, first manual run |
| Component | Entry points, `app/main.py`, `scripts/*.py` |
| Status | Fixed |

**Steps to reproduce**

```powershell
cd zero-magic
& .venv\Scripts\python.exe app\main.py
```

**Expected:** the server starts, or the command prints a clear instruction to
use `uvicorn`.

**Actual:**

```
ImportError: attempted relative import with no known parent package
```

(A sibling message, `attempted relative import beyond top-level package`, appears
when the same file is invoked through a launcher that sets `__package__` to the
empty string. The same class of failure hits `scripts/embedding_ranking.py`,
which crashed with `ModuleNotFoundError: No module named 'app'`.)

**Root cause:** `app/main.py` uses package-relative imports (`from .ai...`).
Executing a file gives it no package, so the relative import has nowhere to
resolve. Demo scripts live outside the package and did not put the repository
root on `sys.path`, so they could not import `app` either. The code was correct
for `uvicorn app.main:app` and `python -m ...`, but nothing said so.

**Fix:**

- Documented the supported entry point (`uvicorn app.main:app --reload`) in the
  README quick start.
- Added a path bootstrap to the standalone scripts:

  ```python
  if __package__ in (None, ""):
      sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
  ```

- Kept the package imports relative, because the package layout is the reason
  the app can be imported by tests and the eval harness without path tricks.

**Regression test:** `test_scripts.py::test_demo_scripts_start_when_run_as_files`
runs both scripts with `--help` as subprocesses and requires exit code 0. The
app entry point is covered by every API test importing `create_app`.

**Prevention:** one documented way to start each artifact; scripts are tested
through the same interface a reviewer will use.

### BUG-002: Agents could validate their own work

| Field | Value |
| --- | --- |
| Severity | Critical (breaks the core promise of the funnel) |
| Found | Week 2, while writing the state-machine tests |
| Component | `app/services/cards.py` |
| Status | Fixed |

**Steps to reproduce** (before the fix):

1. Create a card as a human.
2. Move it `spec → ready` as a human.
3. Move it `ready → building → checks` as `agent:builder`.
4. Move it `checks → validation` as `agent:builder`.
5. Move it `validation → done` as `agent:builder`.

**Expected:** steps 4 and 5 return `403 agent_not_allowed`. Accepting checks and
passing validation are human decisions.

**Actual:** both returned 200. The matrix only encoded *structural* edges; it had
no notion of which actor may take an edge. An agent could walk a card from
`building` all the way to `done`, which is exactly the failure the funnel exists
to prevent. The self-validation check did not help, because `built_by` matched
and the check ran only for `done` — but the agent never needed a human at all.

**Root cause:** role rules were enforced only for CRUD (`human_only`) and
assignment. Transition authorisation stopped at "is this a legal edge?", not
"may this actor take it?". The missing abstraction was a set of human-only
edges.

**Fix:**

```python
HUMAN_ONLY_TRANSITIONS = frozenset({
    (Stage.SPEC, Stage.READY),
    (Stage.READY, Stage.SPEC),
    (Stage.CHECKS, Stage.VALIDATION),
    (Stage.CHECKS, Stage.BUILDING),
    (Stage.VALIDATION, Stage.BUILDING),
    (Stage.VALIDATION, Stage.DONE),
})
```

Agent-legal edges are now exactly `ready → building` and `building → checks`.
The check runs after the legal-edge check (so an impossible move is still 409)
and before the self-validation check (so an agent gets `agent_not_allowed`, not
`self_validation_blocked`). `/api/v1/meta` publishes the same set, and a unit
test asserts every human-only edge is also a legal edge.

**Regression test:**
`test_stage_machine.py::test_agents_cannot_take_human_only_edges` is
parametrised over all six edges from every reachable source stage.
`test_stage_machine.py::test_agent_that_built_the_card_still_cannot_validate_it`
pins the guard order.

**Prevention:** the matrix and the role set are now two explicit tables, and
`test_units.py::test_human_only_edges_are_legal_edges` prevents an edge being
marked human-only without existing in the matrix.

### BUG-003: The mock provider counted Markdown headings as requirements

| Field | Value |
| --- | --- |
| Severity | Medium (inflated cards; could exhaust the card cap) |
| Found | Week 3, first run of the breakdown tests |
| Component | `app/ai/providers/mock.py::extract_requirements` |
| Status | Fixed |

**Steps to reproduce:**

```powershell
& .venv\Scripts\python.exe -m pytest tests\test_breakdown.py -k typed_cards
```

With a PRD shaped like the sample (`# Card comments`, an intro paragraph, four
bullets), the strict mock produced one card per extracted requirement.

**Expected:** one card per requirement, 3-5 cards for this input.

**Actual:** the heading itself became a requirement, so every breakdown had one
extra card. A six-requirement PRD produced seven cards, and a long PRD could hit
the ten-card cap and be rejected on every retry — a `502` caused entirely by a
test double, not by the prompt.

**Root cause:** `extract_requirements` treated every non-empty line as a
requirement unless it was a short line or ended with `:`. Markdown headings are
document structure, not requirements. The tests had encoded the wrong expected
count as well, which is why the defect first looked like a flaky assertion.

**Fix:**

```python
if line.startswith("#"):
    # Markdown headings describe the document, not a requirement.
    continue
```

The two affected assertions were corrected only after counting the real
requirements (4 bullets plus the intro paragraph, not 4 total).

**Regression test:**
`test_units.py::test_requirement_extraction_skips_markdown_headings` pins the
extraction rule directly, and the breakdown tests pin the card counts.

**Prevention:** a test double is still code. Its helpers get unit tests, and a
count mismatch is treated as a possible extractor bug before the expectation is
adjusted.

## 7. Manual and exploratory checks

Run before a release or demo:

- [ ] `uvicorn app.main:app --reload`, open `/docs`, every route renders.
- [ ] `GET /api/v1/meta` matches the matrix in this repository.
- [ ] Create a card as `human:ada`; try the same as `agent:builder` (403).
- [ ] Drag a card through every legal edge with the right actor; try one illegal
      edge (409) and one agent-only violation (403).
- [ ] Create a PRD, run a breakdown, confirm all cards are in `spec` and
      `source: "prd"`.
- [ ] Stop the network / unset the key and confirm the mocks still work.
- [ ] Set `BREAKDOWN_RATE_LIMIT=1`, call twice, confirm 429 and `Retry-After`.
- [ ] Set `BREAKDOWN_TIMEOUT_SECONDS=0.001`, confirm 504 and zero cards.
- [ ] Send Persian text as a comment and a PRD; confirm it round-trips.
- [ ] Send a PRD containing "ignore previous instructions"; confirm the warning
      and that the phrase does not appear in any card.

## 8. Known gaps

| Gap | Risk | Next step |
| --- | --- | --- |
| No test against a real model | Mock behaviour is not vendor behaviour | Run `compare_models.py` with a key in a scheduled job |
| No multi-process test | In-process limiter and store diverge under workers | Redis + PostgreSQL tests in weeks 5-7 |
| No load test | Latency under concurrency unknown | k6 or locust after the database lands |
| No browser tests | There is no frontend yet | Playwright in week 4 |
| No mutation testing | Coverage can be green with weak assertions | Optional `mutmut` run on `services/cards.py` |
| No fuzzing | Random payloads may find envelope gaps | Hypothesis on create/transition schemas |
| No refresh/revocation tests | Tokens expire but cannot be renewed or revoked yet | Add them when the refresh story lands |

## 9. Proposed CI

The suite is designed to run in one job with no services:

```yaml
name: test
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python -m pytest
      - run: python -m evals.run_evals --quiet
```

The eval runner is part of the gate already (`test_evals.py`), so the last step
is for the artifact, not the verdict.
