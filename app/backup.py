"""On-demand full backup of the SQL Server database.

Nothing runs on a timer: every backup writes a new file, so it only happens when
a human asks for it (the console's Backup button, ``POST /api/v1/backup``, or
``backup-db-now.bat``). That keeps the disk under the operator's control.

BACKUP runs with CHECKSUM, so SQL Server reads and checks every page and fails
the command on a damaged one. RESTORE VERIFYONLY is not used here: it needs
CREATE DATABASE permission in master, which the application login deliberately
does not have. ``scripts/backup-db.ps1`` runs as the Windows user and performs
the stronger verify.

SQL execution and log writing only. Precondition and retention live in
``app/services/backup.py`` (ADR 0007).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytds

from .config import Settings

logger = logging.getLogger("zero_magic.backup")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def backup_dir(settings: Settings) -> Path:
    path = Path(settings.backup_dir)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _connect(settings: Settings) -> pytds.Connection:
    return pytds.connect(
        dsn=settings.db_server,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        autocommit=True,
        login_timeout=10,
        timeout=600,
    )


def _log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  {line}\n")
    logger.info(line)


def execute_backup(settings: Settings) -> Path:
    """SQL execution and log writing only. No precondition or pruning."""

    destination = backup_dir(settings)
    destination.mkdir(parents=True, exist_ok=True)
    log = destination / "backup.log"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = destination / f"{settings.db_name}_{stamp}.bak"
    _log(log, f"backup start: {target}")

    connection = _connect(settings)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"BACKUP DATABASE [{settings.db_name}] TO DISK = N'{target}' "
            f"WITH INIT, COMPRESSION, CHECKSUM, NAME = N'{settings.db_name} full backup'"
        )
    except Exception:
        _log(log, "FAILED: the backup command failed; removing the partial file")
        target.unlink(missing_ok=True)
        raise
    finally:
        cursor.close()
        connection.close()

    size = round(target.stat().st_size / (1024 * 1024), 2)
    _log(log, f"backup ok: {target} ({size} MB)")

    return target