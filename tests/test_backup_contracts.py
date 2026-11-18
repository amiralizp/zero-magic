"""Behavior-lock tests for backup (S8.6).

Pin the availability check, authorization and retention policy so the
S8.6 layer move cannot change behavior.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import tests.helpers as helpers
from app.services.backup import prune_old_backups


def test_backup_unavailable_without_sql_user(client):
    response = client.post("/api/v1/backup", headers=helpers.headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "backup_unavailable"


def test_backup_human_only(client):
    response = client.post("/api/v1/backup", headers=helpers.headers(helpers.AGENT))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"


def test_backup_requires_actor(client):
    response = client.post("/api/v1/backup")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_actor"


def test_retention_prunes_old_files(tmp_path: Path):
    db_name = "Gantry"
    old_file = tmp_path / f"{db_name}_20200101_000000.bak"
    old_file.write_text("old")
    old_time = time.time() - 30 * 86400
    os.utime(old_file, (old_time, old_time))

    new_file = tmp_path / f"{db_name}_20261118_000000.bak"
    new_file.write_text("new")

    # unrelated file should not be touched
    other = tmp_path / "other_20200101_000000.bak"
    other.write_text("other")
    os.utime(other, (old_time, old_time))

    pruned = prune_old_backups(tmp_path, db_name, 14)
    assert old_file.name in pruned
    assert not old_file.exists()
    assert new_file.exists()
    assert other.exists()