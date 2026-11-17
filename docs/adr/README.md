# Decisions

Architecture decision records for the weeks 1-3 backend. Each one records the
context, the choice and what it costs, so a later change can be argued on the
merits rather than by guessing why something is the way it is.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-in-memory-store.md) | In-memory store for weeks 1-3 | Accepted (temporary; see 0006) |
| [0002](0002-actor-header-identity.md) | `X-Actor-Id` as temporary identity | Superseded by 0009 |
| [0003](0003-state-machine-in-service.md) | The state machine lives in the service layer | Accepted |
| [0004](0004-mock-providers-and-evals.md) | Deterministic mock providers plus an eval gate | Accepted |
| [0005](0005-error-envelope.md) | One error envelope for every failure | Accepted |
| [0006](0006-sql-server-store.md) | SQL Server behind the existing store interface | Superseded by 0008 |
| [0007](0007-layered-architecture-with-repository.md) | Layered architecture with a Repository layer | Accepted |
| [0008](0008-postgresql-and-alembic.md) | PostgreSQL with Alembic migrations replaces SQL Server | Accepted |
| [0009](0009-token-authentication-and-roles.md) | Token authentication and roles replace the X-Actor-Id header | Accepted |
| [0010](0010-top-qualities-and-architecture-style.md) | Top three qualities and a layered monolith | Accepted |

Format: a decision is a short document with **Status**, **Context**,
**Decision**, **Consequences** and **Alternatives considered**. A decision that
is replaced keeps its file and gains a **Superseded by** line; history is not
rewritten.
