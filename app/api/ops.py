"""Operational endpoints: run a backup on demand."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..config import Settings
from ..errors import AppError
from ..schemas.actors import Actor
from ..schemas.common import ErrorEnvelope
from ..services import backup as backup_service
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
    try:
        path = await asyncio.to_thread(backup_service.run_backup, settings)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - the file system or SQL Server failed
        raise AppError(500, "backup_failed", f"Backup failed: {exc}") from exc
    return {"file": str(path), "bytes": path.stat().st_size, "by": actor.id}
