"""Operational endpoints: run a backup on demand."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..backup import run_backup
from ..config import Settings
from ..errors import AppError
from ..schemas.actors import Actor
from ..schemas.common import ErrorEnvelope
from .deps import get_settings, require_human

router = APIRouter(prefix="/api/v1", tags=["ops"])

_ERRORS = {
    403: {"model": ErrorEnvelope, "description": "Human only."},
    503: {"model": ErrorEnvelope, "description": "No SQL database configured."},
}


@router.post("/backup", responses=_ERRORS, summary="Write and verify a database backup")
async def backup(
    actor: Annotated[Actor, Depends(require_human)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if not settings.db_user:
        raise AppError(
            503,
            "backup_unavailable",
            "No SQL Server login is configured, so there is no database to back up.",
        )
    try:
        path = await asyncio.to_thread(run_backup, settings)
    except Exception as exc:  # noqa: BLE001 - the file system or SQL Server failed
        raise AppError(500, "backup_failed", f"Backup failed: {exc}") from exc
    return {"file": str(path), "bytes": path.stat().st_size, "by": actor.id}
