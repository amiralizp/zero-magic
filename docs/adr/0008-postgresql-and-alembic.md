# ADR 0008: PostgreSQL with Alembic migrations replaces SQL Server

**Status:** Accepted (implementation in S9-S11)
**Date:** 2026-11-17
**Deciders:** backend
**Supersedes:** [0006](0006-sql-server-store.md)

## Context

ADR 0006 chose SQL Server because SSMS was the daily tool and Docker was out of
scope. It listed its own costs: schema changes are append-only IF OBJECT_ID
guards, not versioned migrations; python-tds is a pure-Python driver; SQL
Server is the only durable target. Week 4 requires PostgreSQL and two Alembic
migrations, and a real migration story is needed before any column changes.

## Decision

- PostgreSQL is the durable database. The repository (ADR 0007) gets a
  PostgreSQL implementation using SQLAlchemy and the psycopg driver.
- Schema changes are made only through Alembic migrations. Migration 1 creates
  the current tables (actors, cards, comments, prds, audit_log); migration 2
  adds a users table (needed by ADR 0009). Each migration must downgrade and
  upgrade cleanly.
- Connection settings come from DATABASE_URL in the environment (.env, never
  committed).
- SqlServerStore, python-tds and the startup schema guards are removed after the
  PostgreSQL repository passes the same repository tests.
- The in-memory repository stays for fast tests.
- Backups: pg_dump or no backup endpoint. This is decided in S11 and recorded
  here.

## Consequences

**Good**

- Versioned, reversible schema changes.
- Durable data across restarts; a standard engine for deployment.

**Bad**

- The team loses the SSMS workflow of ADR 0006; psql or pgAdmin replaces it.
- A running PostgreSQL is now required for non-test runs.
- The driver must install on this interpreter (ADR 0006 hit a wheel problem
  with pyodbc); this is checked first in S9.
- The backup feature and its tests (python-tds, backup.py) are rewritten or
  removed.

**Checked by:** the same repository tests run against memory and PostgreSQL; a
test that data survives a restart; alembic upgrade head and downgrade -1 on a
fresh database.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep SQL Server (ADR 0006) | Does not meet the PostgreSQL and Alembic requirement; no versioned migrations |
| SQLite | Not the target engine; weaker fit for concurrent writers |
| psycopg with hand-written SQL files | Works, but Alembic gives ordered, reversible history and is the stated requirement |
| Keep memory only | Loses data on every restart |
