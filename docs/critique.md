# Architecture critique of `app/`

Read-only audit, 2026-11-17. Intended dependency direction (AGENTS.md):
**HTTP -> services -> store/AI -> schemas**. Schemas import nothing from the
app except other schemas; the AI layer must not read the store or build HTTP
responses. Line numbers refer to the working tree at the time of the audit.

## 1. Concepts, one real example each

### Coupling

`app/services/cards.py:7` imports `AppError` from `app/errors.py`, and
`app/errors.py:16-19` imports `fastapi` and `starlette`. The service layer is
therefore coupled to the web framework through a module that mixes a
framework-free exception type with framework-specific handler installation.
Same pattern in `app/services/breakdown.py:21` and
`app/services/chat_agent.py:19`. Fix: split `AppError` into a module with no
fastapi import; keep `install_error_handlers` at the HTTP edge.

### Cohesion

`app/backup.py` does four unrelated jobs in one module: path resolution
(`29-31`), SQL connection and `BACKUP DATABASE` execution (`34-43`, `68-81`),
log-file writing (`46-51`), and retention/pruning policy (`86-90`). The
retention rule is business policy, the SQL is persistence plumbing, and they
change for different reasons. Fix: policy to `app/services/backup.py`, SQL
execution behind the store layer, logging as a cross-cutting concern.

### Layering

`app/api/ops.py:37` calls `run_backup` from `app/backup.py`, which opens a
`pytds` connection (`app/backup.py:35-43`) and executes SQL
(`app/backup.py:71-74`). The HTTP layer reaches SQL directly, skipping both
the services layer and the store layer. Fix: router -> `services/backup.py`
-> store-layer SQL execution.

### Dependency direction

`app/services/chat_agent.py:20` and `app/services/breakdown.py:22` import
`card_to_read` from `app/presenters.py` — the record-to-public-model mapping
that belongs to the HTTP edge. A lower layer (services) depends upward on a
presentation concern. Fix: services return records/domain objects; presenters
are applied only in routers. Related: `app/services/cards.py:10` and
`app/services/chat_agent.py:23` import record types from `app/store.py` (the
in-memory implementation module) instead of a neutral records module.

## 2. Findings

| Where | Problem | Target layer |
| --- | --- | --- |
| `app/api/cards.py:61` | Router calls `store.list_cards(...)` directly | services (`card_service.list_cards`) |
| `app/api/cards.py:62` | Pagination window + `total` policy in the router | services (return page + total) |
| `app/api/cards.py:81-83` | `store.get_card` + inline 404 duplicates `_card_or_404` (`app/services/cards.py:38`) | services (public `get_card_or_404`) |
| `app/api/prds.py:66` | Router calls `store.list_prds()` directly | services (`card_service.list_prds`) |
| `app/api/meta.py:24,29` | `request.app.state.store` bypasses `Depends(get_store)`; `getattr(store, "kind", "memory")` fallback is dead code (`store.py:62`, `store_sql.py:150` both set `kind`) | HTTP wiring: inject store, use `store.kind` |
| `app/api/meta.py:37` | Router calls `store.list_actors()` directly | services (actors/meta read) |
| `app/api/chat.py:119` | Body-claim actor fallback does `store.get_actor` in the router | HTTP deps (`optional_actor`, `app/api/deps.py:34`) or services/actors |
| `app/api/chat.py:100-112` | Hand-rolled body/messages validation instead of a strict schema | schemas (`extra="forbid"` request model) |
| `app/api/chat.py:127-129` | Raw `float()`/`int()` coercion of temperature/max_tokens; bad input raises `ValueError` -> unhandled 500 | schemas (typed fields, defaults, bounds) |
| `app/api/chat.py:68-69,131-136` | `missing_chat_key` precondition checked twice in the router | services/chat or `app/ai/chat/client.py` |
| `app/api/chat.py:159-181` | Upstream 401/403/402/429 -> hint/error policy in the router | services/chat or ai/chat; router only frames SSE events |
| `app/api/ops.py:37` + `app/backup.py:20,35-43,71-74` | HTTP reaches pytds SQL with no service or store layer between | services/backup + store-layer SQL |
| `app/api/ops.py:30-35` | `backup_unavailable` precondition duplicates `app/backup.py:57-58` | services/backup (one check, one code) |
| `app/backup.py:86-90` | Retention/pruning policy (`backup_keep_days`) outside services | services/backup |
| `app/api/deps.py:64-73` | `require_human` role gate duplicates `_require_human` (`app/services/cards.py:45`) | judgment: endpoint authz may stay in HTTP, but define the role rule once in services and reference it |
| `app/presenters.py:13,27` | Presenters query the store (`get_actor`) for enrichment on every call | services resolve actors, or presenters take pre-resolved inputs |
| `app/services/cards.py:7`, `breakdown.py:21`, `chat_agent.py:19` + `app/errors.py:16-19` | Indirect fastapi dependency via `AppError` | framework-free error module; handlers stay at HTTP edge |
| `app/services/breakdown.py:22`, `chat_agent.py:20` | Services import presenters (upward dependency) | services return records; mapping at HTTP edge |
| `app/services/cards.py:10`, `chat_agent.py:23` | Record types imported from `app/store.py`, the in-memory implementation module | neutral records module shared by both stores |

Clean checks (no findings):

- No store/db module imports services: `store.py:15-17`, `store_sql.py:22-26`,
  `db.py:10-12` import only actors/config/schemas/store.
- No service imports fastapi or a SQL library directly.
- `assignment.py`, `comments.py`, and the breakdown endpoint
  (`prds.py:94-100`) are thin routers delegating to services.
- `chat_agent.execute_tool` runs every mutation through the same service
  functions the HTTP API uses (`app/services/chat_agent.py:24-34`).

## 3. Agent audit vs my review

### What the agent saw that a quick review would miss
The agent found an indirect coupling: services import AppError from
app/errors.py, and errors.py imports fastapi, so the service layer depends on
the web framework even though no service imports fastapi directly. A plain
search for "import fastapi" in app/services finds nothing. The agent also
noticed that presenters query the store, so the mapping layer is a second
consumer of persistence.

### What I verified myself
I had the agent re-check eight claims read-only. Seven were confirmed exactly
(file and line numbers, the dead getattr fallback, the presenters imports).
The chat bug is real: a request with temperature="abc" raises ValueError at
app/api/chat.py:128 and returns HTTP 500 with the generic internal_error
envelope, before any model call and without needing an API key.

### Where I disagree or want more care
The agent called the duplicated require_human check "acceptable"; I treat it as
a duplication to resolve in S8 by defining the role rule once. The phrase
"unhandled 500" in the findings table is slightly off: a catch-all handler
returns the standard error envelope. Also, the permission rules in
opencode.json did not prompt for git add or echo, so they are not enforced as
written; for now I rely on AGENTS.md and my own review of each diff.

## 4. Impact on S7/S8

Per docs/ROADMAP.md, S7 adds the architecture test (marked xfail, the Git
protocol's stated exception) and S8 is the refactor that makes it pass and
removes the xfail.

What an import-level architecture test can catch mechanically:

- services -> presenters (`chat_agent.py:20`, `breakdown.py:22`).
- pytds imported outside the store layer (`backup.py:20`), if the rule is
  "only store modules may import SQL drivers".
- services -> `app/store.py` record imports, if the rule forbids naming a
  store implementation from services.
- services -> fastapi only with transitive import analysis; a direct-import
  scan misses it because the hop goes through `app/errors.py`.

What an import-only test will miss:

- Routers calling store methods (`cards.py:61,81`, `prds.py:66`,
  `meta.py:37`, `chat.py:119`): routers legitimately import `Store` for
  dependency injection, so these need call-site/AST analysis or an explicit
  allowlist, not an import ban.
- Business rules in routers (validation, pagination, error-hint policy):
  not import violations at all; they need review or targeted contract tests.

Consequences for the steps:

- S7 should encode the rules above and stay `xfail` while the findings table
  is unresolved. Per the Git protocol, the test must not be edited just to
  make it pass; removing the `xfail` is S8's job, after real moves.
- S8 ordering that retires findings cheaply first: (1) service reads for
  cards/prds/meta + DI fix, (2) chat request schema + chat service for key
  check and error policy, (3) services/backup + store-layer SQL, (4) split
  `AppError`, remove services->presenters imports, neutral records module.
- Contract risk during S8: error codes are the contract (AGENTS.md rule 4).
  Moving validation/preconditions must keep every `error.code` and status
  identical; the chat 500-on-bad-number fix is the one deliberate behaviour
  change and needs its own failing test first. Presenter decoupling touches
  every router call site, so land it last with the full suite green.
