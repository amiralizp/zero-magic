# Card 02: Comments on cards

**Status:** Done (week 2)
**Depends on:** Card 01 (cards API)
**Built:** test-first from this file, on branch `feat/comments`

## Goal

Let a human and an agent discuss a card where the work happens. A comment is
append-only in this iteration: it never edits the card or changes its stage.

## Acceptance criteria

- [x] `POST /api/v1/cards/{id}/comments` accepts `{"body": "..."}` and returns
      201 with `id`, `card_id`, `author`, `body` and `created_at`.
- [x] The body is trimmed; an empty or whitespace-only body returns 422
      `invalid_payload`; a body over 2000 characters returns 422.
- [x] An unknown key in the payload returns 422.
- [x] Both humans and agents may comment; a missing/unknown actor returns 401.
- [x] Commenting on a missing card returns 404 `card_not_found`.
- [x] `GET /api/v1/cards/{id}/comments` returns `{items, total}`, oldest first.
- [x] Comments work in every stage, including `done`.
- [x] Adding a comment does not change the card's `version` or `updated_at`.
- [x] Deleting a card deletes its comments; listing them afterwards is 404.
- [x] Unicode (including Persian) round-trips unchanged.

## Out of scope

Editing or deleting individual comments, threading, mentions, notifications,
markdown rendering, attachments.

## Tests

| Criterion | Test |
| --- | --- |
| Typed response and trimming | `test_comments.py::test_add_comment_returns_the_typed_comment` |
| Agents may comment | `test_comments.py::test_agents_may_comment` |
| Every stage | `test_comments.py::test_comments_work_in_every_stage` |
| Ordering | `test_comments.py::test_comments_are_listed_oldest_first` |
| Empty and oversized bodies | `test_comments.py::test_empty_comment_is_422`, `test_oversized_comment_is_422` |
| Missing actor and card | `test_comments.py::test_comment_requires_an_actor`, `test_comment_on_missing_card_is_404` |
| Card is not mutated | `test_comments.py::test_commenting_does_not_mutate_the_card` |
| Unicode | `test_comments.py::test_unicode_comment_round_trips` |

## Notes

The read endpoint is public in the same sense as the rest of the API: identity is
only required for writes. When authentication lands, reads become workspace
scoped.

Author is stored as an actor id and presented as the full actor, so a renamed
display name does not rewrite history.
