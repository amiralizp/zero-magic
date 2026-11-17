# ADR 0010: Top three qualities and a layered monolith

**Status:** Accepted
**Date:** 2026-11-17
**Deciders:** backend

## Context

Several decisions (layers, database, authentication) depend on what matters
most. The service lets agents change cards and executes untrusted model output,
and a missed check lets an agent approve its own work.

## Decision

The three qualities, in priority order: security, testability,
maintainability.

The style is a layered monolith: one FastAPI process, one PostgreSQL database,
no message queue and no separate worker. Creating all cards of a breakdown must
be atomic, which is simplest in one database transaction. Breakdown and chat run
inside the request with a deadline, so no worker is needed today.
docs/architecture.md sections 3.2 to 3.4 hold the details and rejected options.

## Consequences

**Good**

- Simple to run, test and explain; transactions stay local.

**Bad**

- No independent scaling per component.
- Long jobs cannot outlive the request deadline.

**Checked by:** the architecture test (ADR 0007), the security tests (ADR 0009)
and the service tests that run without a database.
**Revisit when:** breakdown regularly exceeds its deadline, jobs must survive a
restart, or separate teams own parts of the system.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Microservices | Atomic breakdown would need distributed transactions; too heavy for one small team |
| Event-driven with a queue and worker | No work is longer than the deadline today; harder to test and debug |
