"""Backup policy: precondition and retention, framework-free.

The SQL execution and log writing stay in ``app/backup.py`` (repository-side
code). This module owns the availability check and the retention/pruning
policy, so the router depends only on the service layer (ADR 0007).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..backup import backup_dir, execute_backup, _log
from ..config import Settings
from ..domain_errors import AppError


def require_backup_available(settings: Settings) -> None:
    if not settings.db_user:
        raise AppError(
            503,
            "backup_unavailable",
            "No SQL Server login is configured, so there is no database to back up.",
        )


def prune_old_backups(directory: Path, db_name: str, keep_days: int) -> list[str]:
    """Delete ``.bak`` files older than ``keep_days``. Return pruned names."""
    pruned: list[str] = []
    cutoff = datetime.now() - timedelta(days=keep_days)
    for old in directory.glob(f"{db_name}_*.bak"):
        if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
            old.unlink(missing_ok=True)
            pruned.append(old.name)
    return pruned


def run_backup(settings: Settings) -> Path:
    require_backup_available(settings)
    destination = backup_dir(settings)
    path = execute_backup(settings)
    log = destination / "backup.log"
    pruned = prune_old_backups(destination, settings.db_name, settings.backup_keep_days)
    for name in pruned:
        _log(log, f"pruned: {name}")
    return path
