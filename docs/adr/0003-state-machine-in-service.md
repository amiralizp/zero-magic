# ADR 0003: The state machine lives in the service layer

**Status:** Accepted
**Date:** 2026-10-23
**Deciders:** backend

## Context

The central risk in an agentic funnel is a card moving forward without the right
human decision. Two implementations are tempting:

1. Put transitions in the HTTP handler, next to the route, because that is where
   the request arrives.
2. Encode them as a database constraint or an enum check on the record.

Both fail here. The router version mixes authorisation, persistence and HTTP,
and cannot be called by anything except HTTP. The database version cannot
express "only a human may take this edge" or "the builder cannot validate",
because those depend on the actor and on history, not only on the row's current
value.

## Decision

`app/services/cards.py` owns the rules as two explicit tables:

```python
ALLOWED_TRANSITIONS: dict[Stage, frozenset[Stage]] = {...}
HUMAN_ONLY_TRANSITIONS: frozenset[tuple[Stage, Stage]] = {...}
```

`transition_card()` applies them in this order:

1. load the card (404 if missing),
2. reject a move to the current stage (409),
3. reject an edge outside the matrix (409),
4. reject an agent on a human-only edge (403 `agent_not_allowed`),
5. reject an agent working another actor's card (403 `not_assignee`),
6. reject the builder validating its own card (403 `self_validation_blocked`),
7. persist the change and write an audit entry.

The router only parses the body, resolves the actor and calls the service. The
matrix and the role set are published by `GET /api/v1/meta` and asserted by unit
tests, so documentation cannot drift from code.

## Consequences

**Good**

- One file answers "what moves are legal and who may make them".
- The whole matrix is testable without HTTP; the parametrised tests cover every
  source/target pair.
- The guardrail order is a deliberate, tested decision. An agent gets
  `agent_not_allowed`, not `self_validation_blocked`, because role is checked
  first.
- Adding an edge is a one-line change plus tests, not a route edit.
- The order is auditable: every transition records actor, from, to, note and
  resulting assignee.

**Bad**

- The service needs the store and the actor; it is not a pure function.
- Two tables can drift if someone edits one without the other. A unit test
  (`test_human_only_edges_are_legal_edges`) mitigates this.
- The matrix is hard-coded, not configurable per workspace. That is intentional
  for now; a configurable funnel would need a versioned workflow definition.
- Some rules also exist in the schema (`Stage` enum, one assignee). The schema
  owns shape, the service owns permission; the split is documented but easy to
  blur.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Transition table in the router | Untestable without HTTP, mixes concerns, duplicated across routes |
| Database check constraint | Cannot see the actor or the builder; would allow an agent to validate |
| Third-party workflow engine | Too much machinery for six stages; hides the rules from review |
| `transitions` library | A dependency for eight edges; explicit tables are easier to audit |
| Allow all moves, log warnings | Directly contradicts the product promise |

## Follow-up

When workspaces arrive, the matrix may become a per-workspace policy object. The
service call signature should stay the same: `transition_card(store, actor,
card_id, payload)`. If the matrix grows beyond a page, split it into a data file
with a schema and keep the same tests.
