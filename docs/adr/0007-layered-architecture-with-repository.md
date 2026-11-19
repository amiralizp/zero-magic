# ADR 0007: Layered architecture with a Repository layer

**Status:** Accepted
**Date:** 2026-11-17
**Deciders:** backend
**Supersedes in part:** [0001](0001-in-memory-store.md)

## Context

ADR 0001 introduced a store interface and ADR 0003 put the state machine in the
service layer. The audit in docs/critique.md shows the boundaries are not
respected everywhere: routers call the store and own rules (paging, 404, chat
validation), services import presenters and, through app/errors.py, fastapi,
and backup code reaches SQL from the HTTP layer. Without a written and tested
boundary, every new feature (and every agent edit) drifts further.

## Decision

Three layers with one allowed direction: HTTP (app/api) -> Service
(app/services) -> Repository (app/repositories) -> database.

- HTTP receives the request, checks its shape, identifies the caller and maps
  results to responses. It contains no business rule and never calls the
  repository.
- Service owns every rule, including who may do what. It uses the repository
  through an interface and never imports fastapi, SQL or presenters.
- Repository is the only layer that touches tables. It contains no rule.
- The store is renamed Repository, with one interface and two implementations
  (memory for tests, PostgreSQL).
- AppError moves to a module without any web framework import.
- The boundary is written in docs/architecture.md section 3.1.

## Consequences

**Good**

- A rule lives in one place; a service can be tested without HTTP or a database.
- Replacing the database touches one layer (see ADR 0008).
- Agents get clear limits, e.g. "change transition rules only in services".

**Bad**

- More folders and an interface to maintain.
- The refactor (S8) touches many files and must keep every error code and
  status unchanged.

**Checked by:** tests/test_architecture.py (import rules, S7) plus the existing
test suite staying green through the refactor (S8).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep the current structure | The audit shows the boundaries erode without enforcement |
| Hexagonal (ports and adapters) everywhere | Same direction of dependencies, more interfaces than this size needs; we keep its useful part, the repository interface |
| Modular monolith by feature | Valid, but code and tests are organised by layer; regrouping is a rewrite with no new behaviour |
