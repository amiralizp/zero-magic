"""Seed identities.

There is no login yet (that is week 6). For weeks 1-3 the caller identifies
itself with ``X-Actor-Id``; this directory decides whether that id is a human
or an agent, and therefore what it may do. Unknown ids are rejected, so the
guardrails cannot be bypassed by inventing ``agent:root``.
"""

from __future__ import annotations

from .schemas.actors import Actor, ActorRole

HUMAN_ADA = "human:ada"
HUMAN_GRACE = "human:grace"
HUMAN_LINUS = "human:linus"
AGENT_BUILDER = "agent:builder"
AGENT_REVIEWER = "agent:reviewer"
AGENT_PLANNER = "agent:planner"

SEED_ACTORS: tuple[Actor, ...] = (
    Actor(id=HUMAN_ADA, display_name="Ada (human)", role=ActorRole.HUMAN),
    Actor(id=HUMAN_GRACE, display_name="Grace (human)", role=ActorRole.HUMAN),
    Actor(id=HUMAN_LINUS, display_name="Linus (human)", role=ActorRole.HUMAN),
    Actor(id=AGENT_BUILDER, display_name="Builder (agent)", role=ActorRole.AGENT),
    Actor(id=AGENT_REVIEWER, display_name="Reviewer (agent)", role=ActorRole.AGENT),
    Actor(id=AGENT_PLANNER, display_name="Planner (agent)", role=ActorRole.AGENT),
)
