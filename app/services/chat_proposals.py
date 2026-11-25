"""Stateless signed chat write proposals.

Write tools never execute immediately in chat. The server returns a signed
proposal; /api/v1/chat/confirm verifies it and executes the same service
function. The proposal token is not a login JWT: it uses a dedicated HMAC key
derived from the JWT secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

PROPOSAL_TTL_SECONDS = 300


def _now() -> int:
    return int(time.time())


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _derived_key(jwt_secret: str) -> bytes:
    return hashlib.sha256(b"chat_confirm|" + jwt_secret.encode("utf-8")).digest()


def arguments_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(arguments).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProposalClaims:
    proposal_id: str
    actor_id: str
    tool: str
    args_hash: str
    exp: int


@dataclass(frozen=True)
class PendingProposal:
    proposal_id: str
    actor_id: str
    tool: str
    arguments: dict[str, Any]
    exp: int


class UsedProposalStore:
    """In-memory pending/used proposal ids, bounded by expiry."""

    def __init__(self) -> None:
        self._used: dict[str, int] = {}
        self._pending: dict[str, PendingProposal] = {}
        self._lock = threading.Lock()

    def _prune(self, now: int) -> None:
        expired_used = [pid for pid, exp in self._used.items() if exp <= now]
        for pid in expired_used:
            self._used.pop(pid, None)
        expired_pending = [pid for pid, p in self._pending.items() if p.exp <= now]
        for pid in expired_pending:
            self._pending.pop(pid, None)

    def put(self, proposal: PendingProposal) -> None:
        now = _now()
        with self._lock:
            self._prune(now)
            self._pending[proposal.proposal_id] = proposal

    def get(self, proposal_id: str) -> PendingProposal | None:
        now = _now()
        with self._lock:
            self._prune(now)
            return self._pending.get(proposal_id)

    def mark_used(self, proposal_id: str, exp: int) -> bool:
        now = _now()
        with self._lock:
            self._prune(now)
            if proposal_id in self._used:
                return False
            self._used[proposal_id] = exp
            self._pending.pop(proposal_id, None)
            return True

    def is_used(self, proposal_id: str) -> bool:
        now = _now()
        with self._lock:
            self._prune(now)
            return proposal_id in self._used


def issue_proposal(
    *, jwt_secret: str, actor_id: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    proposal_id = secrets.token_urlsafe(18)
    exp = _now() + PROPOSAL_TTL_SECONDS
    claims = {
        "pid": proposal_id,
        "sub": actor_id,
        "tool": tool,
        "ah": arguments_hash(arguments),
        "exp": exp,
    }
    body = _b64url_encode(_canonical_json(claims).encode("utf-8"))
    sig = hmac.new(_derived_key(jwt_secret), body.encode("ascii"), hashlib.sha256).digest()
    token = f"{body}.{_b64url_encode(sig)}"
    return {"proposal_id": proposal_id, "exp": exp, "token": token}


def verify_proposal(token: str, *, jwt_secret: str) -> ProposalClaims:
    try:
        body, sig_part = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid proposal token") from exc
    expected = hmac.new(_derived_key(jwt_secret), body.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _b64url_decode(sig_part)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid proposal token") from exc
    if not hmac.compare_digest(expected, actual):
        raise ValueError("invalid proposal signature")
    try:
        claims = json.loads(_b64url_decode(body))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid proposal token") from exc
    if not isinstance(claims, dict):
        raise ValueError("invalid proposal claims")
    exp = int(claims.get("exp", 0))
    if exp <= _now():
        raise ValueError("proposal expired")
    proposal_id = str(claims.get("pid", ""))
    actor_id = str(claims.get("sub", ""))
    tool = str(claims.get("tool", ""))
    ah = str(claims.get("ah", ""))
    if not proposal_id or not actor_id or not tool or not ah:
        raise ValueError("invalid proposal claims")
    return ProposalClaims(
        proposal_id=proposal_id, actor_id=actor_id, tool=tool, args_hash=ah, exp=exp
    )

def confirm_and_execute(
    *,
    token: str,
    arguments: dict[str, Any] | None,
    actor: Any,
    store: Any,
    settings: Any,
    proposals: UsedProposalStore,
) -> dict[str, Any]:
    from .chat_agent import WRITE_TOOLS, execute_tool

    claims = verify_proposal(token, jwt_secret=settings.jwt_secret)
    if claims.actor_id != actor.id:
        raise PermissionError("forbidden")
    if claims.tool not in WRITE_TOOLS:
        raise ValueError("unknown tool")
    pending = proposals.get(claims.proposal_id)
    resolved_args = arguments if arguments is not None else (pending.arguments if pending else None)
    if resolved_args is None:
        raise ValueError("missing arguments")
    if arguments_hash(resolved_args) != claims.args_hash:
        raise ValueError("arguments mismatch")
    if not proposals.mark_used(claims.proposal_id, claims.exp):
        raise RuntimeError("proposal used")
    return execute_tool(store, actor, claims.tool, resolved_args, settings=settings)
