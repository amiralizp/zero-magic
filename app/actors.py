"""Seed identities.

The caller's identity comes from a verified bearer token; this directory defines
the seeded humans and agents and their roles. The service layer decides what
each role may do, and unknown identities are rejected.
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
