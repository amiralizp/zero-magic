"""Backup scheduling rules that do not need a database."""

from __future__ import annotations

import tests.helpers as helpers


def test_backup_reports_that_nothing_is_configured(client):
    response = client.post("/api/v1/backup", headers=helpers.headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "backup_unavailable"


def test_backup_is_human_only(client):
    response = client.post("/api/v1/backup", headers=helpers.headers(helpers.AGENT))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"
