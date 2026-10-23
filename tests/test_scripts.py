"""Standalone demo scripts must run when invoked by path, not just as modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_demo_scripts_start_when_run_as_files():
    # Bug 001: a script run by path had no package context and crashed before
    # argparse could print help. The bootstrap in each script is the fix.
    root = Path(__file__).resolve().parent.parent
    for script in ("scripts/embedding_ranking.py", "scripts/compare_models.py"):
        completed = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, (script, completed.stderr[-400:])
        assert "usage:" in completed.stdout.casefold()
