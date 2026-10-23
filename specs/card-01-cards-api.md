# Card 01: Cards API with typed contracts and a strict stage machine

**Status:** Done (week 1-2)
**Depends on:** none
**Source:** internship plan, days 1-5

## Goal

Give the funnel a single source of truth for work: a card with a written spec, a
typed public shape, and a state machine that rejects illegal moves instead of
guessing. The browser must be able to branch on HTTP status and an error code.

## Acceptance criteria

- [x] `POST /api/v1/cards` creates a card in `spec` as a human and returns 201.
- [x] The public card has `id`, `title`, `goal`, `acceptance_criteria`,
      `out_of_scope`, `stage`, `assignee`, `created_by`, `depends_on`, `prd_id`,
      timestamps, `version` and a computed `source` of `manual` or `prd`.
- [x] Internal fields (`built_by`, history) never appear in a response.
- [x] A payload with a missing field, a blank value, duplicate criteria, more
      than five criteria or an unknown key returns 422 with
      `error.code == "invalid_payload"` and field details.
- [x] A missing or unknown `X-Actor-Id` returns 401; an agent creating, editing
      or deleting a card gets 403 `human_only`.
- [x] Only these edges exist: `spec -> ready`, `ready -> spec`,
      `ready -> building`, `building -> checks`, `checks -> validation`,
      `checks -> building`, `validation -> done`, `validation -> building`.
- [x] Any other move, including a move to the current stage, returns 409
      `illegal_transition` with the current and requested stage.
- [x] Agents may take only `ready -> building` and `building -> checks`; every
      other edge is 403 `agent_not_allowed`.
- [x] An agent may work only a card assigned to it, otherwise 403
      `not_assignee`; claiming an unassigned card assigns it to the agent.
- [x] The actor that built a card cannot move it to `done` (403
      `self_validation_blocked`).
- [x] The spec can be edited only in `spec` (409 `spec_locked` afterwards).
- [x] `GET /api/v1/cards` filters by stage and assignee, searches title/goal/
      criteria, and paginates with `limit`, `offset` and `total`.
- [x] Every failure uses `{"error": {"code", "message", "details"?}}`.
- [x] CORS allows only `FRONTEND_ORIGIN`, not `*`.
- [x] Every response carries or echoes `X-Request-Id`.

## Out of scope

Comments, assignment UI, PRD breakdown, persistence, login, frontend.

## Tests

| Criterion | Test |
| --- | --- |
| Create shape and hidden fields | `test_cards_crud.py::test_create_card_returns_typed_public_shape` |
| Actor identity | `test_cards_crud.py::test_create_requires_a_known_actor` |
| Validation and 422 envelope | `test_cards_crud.py::test_invalid_create_payload_returns_422_with_one_error_shape` |
| Transition matrix | `test_stage_machine.py::test_edges_outside_the_matrix_return_409` |
| Human-only edges | `test_stage_machine.py::test_agents_cannot_take_human_only_edges` |
| Agent assignee rule | `test_assignment.py::test_agent_can_only_work_on_its_own_card` |
| Self-validation | `test_stage_machine.py::test_builder_cannot_validate_its_own_card` |
| Error envelope, CORS, request id | `test_http_contracts.py` |
| Matrix completeness | `test_units.py::test_transition_matrix_only_names_known_stages` |

## Notes

The matrix lives in `app/services/cards.py`, not in the router, so the HTTP layer
cannot drift from the rules. The self-validation check compares the actor with
the recorded builder, not with the assignee.

## Follow-ups

- Week 5: replace the in-memory store with PostgreSQL and migrations.
- Week 6: replace `X-Actor-Id` with real authentication and per-workspace roles.
- Week 7: move rate limits to Redis for multi-worker deployments.
