# ADR 0009: Token authentication and roles replace the X-Actor-Id header

**Status:** Accepted (implementation in S12-S14)
**Date:** 2026-11-17
**Deciders:** backend
**Supersedes:** [0002](0002-actor-header-identity.md)

## Context

ADR 0002 accepted the X-Actor-Id header as a temporary identity and documented
it as insecure: anyone can claim any seeded actor, including a human, so an
agent could approve its own work by sending a different header. The service
layer already has the role rules (human-only edges, self-validation block), but
they trust an identity that cannot be trusted.

## Decision

- Users log in with a username and password. Passwords are stored only as a
  salted hash (argon2 or bcrypt).
- Login returns a signed token with an expiry. The signing key comes from the
  environment.
- Each user has a role, human or agent, stored in the database (migration 2 of
  ADR 0008). The HTTP layer turns the token into the caller (who are you).
- The service layer decides what the caller may do and checks it on every call,
  so the HTTP API, the chat agent and scripts cannot skip a rule.
- The X-Actor-Id header no longer determines identity. Missing or invalid token
  gives 401; a valid token without permission gives 403.
- Initial users are created from environment values, never from secrets in code.

## Consequences

**Good**

- An agent cannot pretend to be a human.
- Authentication (who) and authorization (what) are separate and testable.

**Bad**

- The console and the chat page need a login and must send the token.
- Agents need their own credentials; token expiry needs a refresh story later.
- Existing tests that send X-Actor-Id must be updated.

**Checked by:** security tests for 401 (no or bad token) and 403 (agent moving
a card to Done, agent calling the backup endpoint), run on every endpoint.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep the header | Defeats the human-only rules, the core of the product |
| Server-side sessions with cookies | Heavier for an API used by scripts and agents |
| API keys per agent only | Humans still need login; one mechanism for both is simpler |
| External identity provider (OAuth) | More moving parts than this project needs now |
