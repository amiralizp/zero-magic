# ADR 0005: One error envelope for every failure

**Status:** Accepted
**Date:** 2026-10-23
**Deciders:** backend

## Context

FastAPI produces three different error shapes by default:

- our own business errors (if we invent one per feature),
- Pydantic request validation errors (`{"detail": [...]}` with nested `loc`/`msg`),
- Starlette HTTP errors (`{"detail": "Not Found"}`),
- unhandled exceptions (HTML in debug mode, plain 500 otherwise).

A browser client would need to parse all four, and a typo in a URL would look
different from a business rule violation. The funnel's contract matters most when
something goes wrong: the client must distinguish "retry", "fix the payload" and
"you are not allowed" without reading prose.

## Decision

Every failure returns:

```json
{"error": {"code": "stable_code", "message": "human text", "details": "optional"}}
```

- `AppError(status_code, code, message, details=None, headers=None)` is raised by
  services and dependencies for expected failures.
- `install_error_handlers` registers handlers for `AppError`, Pydantic's
  `RequestValidationError`, Starlette's `HTTPException` and bare `Exception`.
- Validation errors become `422 invalid_payload` with a list of
  `{location, message, type}` objects, never Pydantic's raw structure.
- Unexpected exceptions are logged with the stack trace and return a generic
  `500 internal_error`; no exception text, prompt or stack trace reaches the
  client.
- `details` is optional and omitted when `None`, so the shape is stable without
  empty placeholders.
- Tests assert the code, not the message. Messages may be improved without
  breaking clients.

Status codes follow HTTP semantics: 401 identity, 403 permission, 404 missing,
409 conflict/illegal state, 422 payload, 429 budget, 502 upstream failure, 504
upstream timeout.

## Consequences

**Good**

- One parser on the client; one place to add request-id correlation later.
- Business codes are stable and greppable (`illegal_transition`,
  `self_validation_blocked`, `provider_error`).
- 500s do not leak internals; debugging uses the request id and server log.
- The same envelope covers missing routes and wrong methods, not just our routes.
- Contract tests can assert `set(payload) == {"error"}` for every failure class.

**Bad**

- We give up FastAPI's default validation shape; tooling that expects
  `{"detail": ...}` (some auto-generated clients) needs the custom schema.
- Every new error needs a code decision, which is deliberate friction.
- `details` is typed `Any`, so its shape is only enforced by the tests that
  happen to assert it.
- The handler for bare `Exception` can mask programming errors in production
  unless logs are monitored.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep FastAPI defaults | Three shapes, and a client cannot branch on a stable code |
| `{"detail": {"code": ...}}` | Closer to the framework, but mixes framework and domain errors; `error` is clearer |
| RFC 9457 Problem Details | A good standard, but heavier than needed here and would not cover our business codes without an extension |
| Per-router error models | Duplication and drift; the handlers are a single seam |

## Follow-up

If the frontend or an SDK needs machine-readable codes, publish the enum in
`/api/v1/meta` and add an OpenAPI example per status. If the API becomes public,
add problem-type URLs to `details` while keeping `code` unchanged.
