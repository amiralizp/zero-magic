# ADR 0009: Token authentication and roles replace the X-Actor-Id header

**Status:** Accepted; S12 authentication and S13 authorization implemented (S14 security tests remain)
**Date:** 2026-11-17
**Reviewed:** 2026-11-20
**Deciders:** backend
**Supersedes:** [0002](0002-actor-header-identity.md)

## Context

ADR 0002 accepted the X-Actor-Id header as a temporary identity and documented
it as insecure: anyone can claim any seeded actor, including a human, so an
agent could approve its own work by sending a different header. The service
layer already has the role rules (human-only edges, self-validation block), but
they trust an identity that cannot be trusted.

## Decision

- Users log in at `POST /api/v1/auth/login` with a username and password.
  Passwords are stored only as Argon2id hashes (`argon2-cffi`); the plaintext is
  never stored, logged or returned.
- Login returns a short-lived HS256 JWT. The signing key comes from `JWT_SECRET`
  (at least 32 characters) and the lifetime from `TOKEN_TTL_SECONDS` (default
  3600). Decoding hard-codes HS256, checks issuer `gantry`, expiry and the
  required `sub`, `username` and `role` claims.
- Each user has a `UserRecord` with a role (`human` or `agent`) and an actor id
  that maps to the seeded actors. The HTTP layer turns the token into that
  actor; the service layer still decides what the actor may do on every call,
  so the HTTP API, the chat agent and scripts cannot skip a rule. The token's
  `role` claim is cross-checked against the stored actor on every request; a
  mismatch is 401 `invalid_token` with `WWW-Authenticate: Bearer`.
- `X-Actor-Id` no longer determines identity and is ignored everywhere in
  `app/api/`. The chat request schema no longer accepts an `actor` field.
  Missing, malformed, expired or unknown identity gives 401
  (`missing_token`, `invalid_token`); wrong credentials give 401
  `invalid_credentials`; a valid token without permission gives 403.
  Bearer failures include `WWW-Authenticate: Bearer`.
- Authorization keeps the service-layer rules. Agents may comment and build,
  never create cards or move a card to `Done`; the service rejects any agent
  transition whose target is `Done`, even if a future edge is not marked
  human-only. There is no backup/admin endpoint (removed in S11b) to call.
- The initial users are `ada` (human) and `builder` (agent). Their passwords are
  read from `GANTRY_HUMAN_PASSWORD` and `GANTRY_AGENT_PASSWORD` by the user-run
  `scripts/setup_auth.py`; there are no credentials in code. The script is
  idempotent and prints usernames only.
- The console and the standalone chat page share one browser token under
  `zm.token` and send it as `Authorization: Bearer ...`.

## Consequences

**Good**

- An agent cannot pretend to be a human by changing a header or a chat field.
- Authentication (who) and authorization (what) are separate and testable.
- One token works for the console, chat and scripted API clients.
- The access token is kept only in memory in the browser (no localStorage); a page reload requires a new login.
- Login attempts are limited per client address and per username-and-address pair, so one client cannot lock another user out; the role is always read from the repository and a token with a different role is rejected.

**Bad**

- Both web pages need a login form; a stored token must be cleared on log out.
- Tokens cannot yet be refreshed or revoked; only the six seeded users are bootstrapped.
- Existing header-based tests and examples had to be rewritten.

**Checked by:** `tests/test_auth.py`, `tests/test_authorization.py`,
`tests/test_auth_core.py` and `tests/test_architecture.py` (only the auth
service imports `jwt`/`argon2`, no legacy identity header in `app/api/`, no
`actor` field in the chat schema), plus the full HTTP suite for 401/403
contracts and the OpenAPI assertion that no backup route exists.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep the header | Defeats the human-only rules, the core of the product |
| Server-side sessions with cookies | Heavier for an API used by scripts and agents |
| API keys per agent only | Humans still need login; one mechanism for both is simpler |
| External identity provider (OAuth) | More moving parts than this project needs now |
