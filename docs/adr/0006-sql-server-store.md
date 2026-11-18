# ADR 0006: SQL Server behind the existing store interface

**Status:** Superseded
**Superseded by:** [0008](0008-postgresql-and-alembic.md)
**Date:** 2026-11-02
**Deciders:** backend
**Supersedes in part:** [0001](0001-in-memory-store.md)

## Context

ADR 0001 chose a dictionary store so the funnel rules could be proven without a
database. That decision cost durability: every restart erased the board. The
plan named PostgreSQL for week 5, but the machine this project runs on already
has SQL Server 2022, and the team works in SSMS. A database nobody can open in
the tool they use every day would not be used.

Two constraints shaped the implementation:

- The store interface from ADR 0001 is the seam. Services must not learn SQL.
- `pyodbc` has no wheel for this interpreter (3.15) and its build toolchain is
  not installed, so the usual SQL Server driver is unavailable.

## Decision

Add a second implementation behind the same methods:

- `app/store_sql.py` — `SqlServerStore` with parameterised queries, a small
  connection pool and the same method surface as `InMemoryStore`.
- `app/db.py` — `build_store(settings)`: no `DB_USER` means the in-memory store,
  a configured login means SQL Server.
- `app/db.py` also creates the schema on startup. Every statement is idempotent
  (`IF OBJECT_ID ... IS NULL`), so restarts are free and existing rows survive.

Driver: `python-tds` (pure Python TDS). It needs no compiler and speaks to the
same server SSMS reads.

Tables: `actors`, `cards`, `comments`, `prds`, `audit_log`, with foreign keys
(`comments` cascades on card delete) and indexes on the columns the API filters
by. Lists are stored as JSON text; timestamps as `DATETIME2` in UTC.

`InMemoryStore` stays. It keeps the suite at eight seconds with no service
running, and it remains the default for `Settings()` in tests.

## Consequences

**Good**

- A restart no longer erases the board; SSMS and `sqlcmd` see the same rows.
- Services and routers are unchanged: the seam from ADR 0001 held.
- Tests still run without a database; only production settings touch SQL Server.
- Schema creation at startup means a fresh clone needs one login, not a
  migration tool.

**Bad**

- `SqlServerStore` does blocking I/O inside async endpoints. At this scale the
  pool and a lock are enough; a busy deployment would move to a thread pool.
- Schema changes are append-only `IF OBJECT_ID` guards, not versioned
  migrations. The first column rename will need a real migration story.
- `version` is still an in-process counter; it increments in SQL but is not an
  optimistic-concurrency check across clients.
- SQL Server is now the only durable target; another engine needs a third store
  or a real repository abstraction.

## Alternatives considered

| Option | Why not |
| --- | --- |
| PostgreSQL (the week 5 plan) | The team's tool is SSMS and the server is already installed; Docker is out of scope |
| SQLite | No SSMS story, and the request was explicitly "open it in SSMS" |
| SQLAlchemy + pyodbc | `pyodbc` cannot be built here; an ORM also hides the SQL a reviewer wants to see |
| `pyodbc` with a compiled wheel | No 3.15 wheel; building needs MSVC, which the project does not require |
| Keep memory only | Loses data on every restart and cannot be queried from SSMS |
