# ADR 0001: In-memory store for weeks 1-3

**Status:** Accepted (temporary) — superseded in part by [ADR 0006](0006-sql-server-store.md)
**Date:** 2026-10-23
**Deciders:** backend

## Context

Weeks 1-3 are about the funnel's rules, the API contract and the model harness.
A database would add migrations, connection handling, container setup and test
fixtures before a single rule is proven. The internship plan schedules
PostgreSQL for week 5, after the frontend starts consuming the API.

The risk of a dictionary store is that business logic leaks into it or that the
HTTP layer starts depending on its shape. Either would make the week 5
replacement expensive.

## Decision

Use a process-local `InMemoryStore` with:

- plain dataclass records (`CardRecord`, `CommentRecord`, `PRDRecord`),
- dictionaries keyed by generated ids (`card_<10 hex>`, `cmt_...`, `prd_...`),
- one `threading.RLock` around every mutation and read,
- an append-only audit log,
- seeded actors constructed once.

All access goes through methods. Services never touch the dictionaries, and no
router imports `CardRecord`. Records are replaced immutably with `dataclasses.replace`,
which increments `version` and `updated_at`.

The store interface is the seam: `get_card`, `list_cards`, `create_card`,
`update_card`, `delete_card`, and the comment/PRD equivalents.

## Consequences

**Good**

- The whole suite runs in about eight seconds with no services.
- Tests get a clean store per application instance.
- Rules can be exercised without a database driver.
- The week 5 replacement has one file to implement behind an existing interface.

**Bad**

- Everything is lost on restart; there is no durability story.
- One process only; two workers have separate data.
- No transactions beyond the lock, no indexes, no query planner.
- `list_cards` filters and searches in Python, which will not scale.
- `version` is an in-process counter, not optimistic concurrency across clients.

These limits are stated in the README and architecture doc. The API does not
pretend the store is durable.

## Alternatives considered

| Option | Why not now |
| --- | --- |
| SQLite + SQLAlchemy | Adds a dependency and migration questions without teaching the funnel rules; still not the week 5 target |
| PostgreSQL immediately | Pulls Docker, migrations and fixtures into week 1 and delays the contract work |
| Repository pattern with abstract base classes | More indirection than one concrete store needs at this size; the method surface is already the seam |

## Follow-up

Week 5 replaces the implementation, not the callers. At that point `version`
becomes a real optimistic-concurrency check and `created_at` ordering becomes an
indexed query.
