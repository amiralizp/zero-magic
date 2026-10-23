# Card 03: One assignee per card

**Status:** Done (week 2)
**Depends on:** Card 01 (cards API)
**Built:** test-first from this file, on branch `feat/assignment`

## Goal

Make ownership unambiguous. Every card has zero or one assignee; assignment is a
human decision; an agent can see what is assigned to it and may only build that.

## Acceptance criteria

- [x] `PUT /api/v1/cards/{id}/assignee` with `{"assignee_id": "<known id>"}`
      returns 200 and the card's `assignee`.
- [x] `{"assignee_id": null}` clears the assignee and also returns 200.
- [x] The `assignee_id` key is required; omitting it returns 422.
- [x] An unknown actor id returns 422 `unknown_assignee`.
- [x] Only a human may assign; an agent gets 403 `human_only`.
- [x] A missing card returns 404 `card_not_found`.
- [x] Assigning a card in `done` returns 409 `card_closed`.
- [x] Assignment is allowed in every stage before `done`.
- [x] `POST /api/v1/cards` accepts an optional `assignee_id` and validates it.
- [x] `GET /api/v1/cards?assignee=<id>` filters by assignee and composes with
      the stage filter.
- [x] An agent may only transition a card assigned to it; an unassigned card is
      claimed by the agent that starts building it.

## Out of scope

Multiple assignees, watchers, teams, workload balancing, assignment history
beyond the audit log.

## Tests

| Criterion | Test |
| --- | --- |
| Set and clear | `test_assignment.py::test_assign_and_clear` |
| Human assignee | `test_assignment.py::test_assign_to_a_human` |
| Unknown id and required key | `test_assignment.py::test_unknown_assignee_is_422`, `test_assignee_key_is_required` |
| Agent forbidden | `test_assignment.py::test_agents_cannot_assign` |
| Missing and closed cards | `test_assignment.py::test_assigning_a_missing_card_is_404`, `test_done_cards_cannot_be_reassigned` |
| Create with assignee | `test_assignment.py::test_create_with_assignee` |
| Filter composition | `test_assignment.py::test_assignment_filter_composes_with_stage` |
| Agent can only build its card | `test_assignment.py::test_agent_can_only_work_on_its_own_card` |

## Notes

The guardrail compares the assignee to the acting agent only for agent actors.
Humans can move a card that is assigned to someone else, because a human may be
reviewing or unblocking it; the audit log records who did it.
