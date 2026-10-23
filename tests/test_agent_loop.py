"""The agent runner: sandbox escapes, step caps, and a real fix end to end."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import agent_loop
from scripts.agent_loop import (
    EXAMPLE,
    MAX_WRITE,
    ToolError,
    execute_tool,
    read_file,
    run_agent,
    write_file,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    shutil.copytree(EXAMPLE, root)
    return root


def test_loop_is_under_150_lines():
    source = Path(agent_loop.__file__).read_text(encoding="utf-8")
    assert len(source.splitlines()) < 150


def test_agent_finds_and_fixes_the_bug(sandbox: Path, tmp_path: Path):
    log = tmp_path / "run.jsonl"
    result = run_agent(sandbox, log_path=log)

    assert result["ok"] is True, result
    assert result["reason"] == "done"
    assert result["steps"] == 4
    assert [entry["tool"] for entry in result["history"]] == [
        "read_file",
        "read_file",
        "write_file",
        "run_tests",
    ]

    fixed = (sandbox / "calculator.py").read_text(encoding="utf-8")
    assert "def subtract(a: float, b: float) -> float:\n    return a - b" in fixed
    assert "def add(a: float, b: float) -> float:\n    return a + b" in fixed

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=sandbox,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout

    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4
    assert lines[-1]["observation"]["returncode"] == 0


def test_step_cap_is_a_clean_failure(sandbox: Path, tmp_path: Path):
    result = run_agent(sandbox, max_steps=2, log_path=tmp_path / "cap.jsonl")
    assert result["ok"] is False
    assert result["steps"] == 2
    assert result["reason"] == "max_steps"


def test_paths_cannot_escape_the_sandbox(sandbox: Path):
    for path in ("../outside.py", "..\\outside.py", str(sandbox.parent / "outside.py")):
        with pytest.raises(ToolError):
            read_file(sandbox, path)
        with pytest.raises(ToolError):
            write_file(sandbox, path, "print('no')")


def test_writes_are_bounded_and_python_only(sandbox: Path):
    with pytest.raises(ToolError):
        write_file(sandbox, "notes.txt", "hello")
    with pytest.raises(ToolError):
        write_file(sandbox, "big.py", "x" * (MAX_WRITE + 1))


def test_unknown_tool_and_bad_arguments_are_reported(sandbox: Path):
    with pytest.raises(ToolError):
        execute_tool(sandbox, {"tool": "delete_everything"})
    with pytest.raises(ToolError):
        execute_tool(sandbox, {"tool": "read_file"})
    with pytest.raises(ToolError):
        execute_tool(sandbox, {"tool": "write_file", "path": "calculator.py"})


def test_missing_file_is_a_tool_error(sandbox: Path):
    with pytest.raises(ToolError):
        read_file(sandbox, "missing.py")


def test_example_sandbox_stays_broken():
    source = (EXAMPLE / "calculator.py").read_text(encoding="utf-8")
    assert "def subtract(a: float, b: float) -> float:\n    return a + b" in source
