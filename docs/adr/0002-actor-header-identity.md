# ADR 0002: `X-Actor-Id` as temporary identity

**Status:** Superseded
**Superseded by:** [0009](0009-token-authentication-and-roles.md)
**Date:** 2026-10-23
**Deciders:** backend, security review

## Context

The funnel's core rules depend on *who* is acting: humans approve specs and
validate work, agents build and submit it. Those rules cannot be tested without
an identity. Real authentication (signup, login, sessions, password hashing,
workspace membership) is scheduled for week 6 and would dominate weeks 1-3.

The dangerous shortcut is to hard-code a single "current user" or to accept a
role header like `X-Role: human`. Both make authorisation untestable and would
survive into production by accident.

## Decision

Require an `X-Actor-Id` header on writes. The value must match a seeded actor:

| Id | Role |
| --- | --- |
| `human:ada` | human |
| `human:grace` | human |
| `human:linus` | human |
| `agent:builder` | agent |
| `agent:reviewer` | agent |
| `agent:planner` | agent |

- Missing header -> `401 missing_actor`.
- Unknown id -> `401 unknown_actor`.
- The role comes from the stored actor, never from the request. There is no
  `X-Role` header and no way for a caller to promote itself.
- Read endpoints do not require identity in this iteration.
- The README, architecture doc and this ADR all state that the header is
  temporary and that the service must not be exposed publicly as-is.

`require_actor` and `require_human` in `app/api/deps.py` are the only places that
read the header. Services receive a resolved `Actor` object.

## Consequences

**Good**

- Every rule is testable by changing one header.
- Role checks live in one dependency plus the service, not scattered in routers.
- Swapping the identity source later means changing `optional_actor`, not the
  rules.
- The 401/403 split is explicit and covered by contract tests.

**Bad**

- Anyone who can reach the API can impersonate any seeded actor. There is no
  secret, signature or expiry.
- There is no tenant boundary: all actors see all cards.
- `401` with `WWW-Authenticate: Actor` is a placeholder scheme, not a standard.
- Logs record the claimed id, which is not proof of anything.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Full auth now | Correct, but weeks 1-3 are explicitly scoped to the funnel and the model harness |
| API key per actor | Better than a bare header, but still not the week 6 design and adds key management |
| `X-Role` header | Worse: it separates identity from role and invites privilege escalation |
| No identity, single implicit user | Makes the human/agent guardrails untestable, which is the point of the project |

## Follow-up

Week 6 replaces the dependency with a session/token resolver that returns the
same `Actor` shape. At the same time, read endpoints become workspace-scoped and
every query filters by membership. ADR 0002 is then superseded; the service
rules do not change.
