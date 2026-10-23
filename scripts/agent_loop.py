"""A small tool-use agent loop, kept under 150 lines on purpose.

The policy is scripted so the demo is offline and repeatable. The rest is a real
agent runner: tool allowlist, sandbox root, step cap, observations, JSONL trace.
"""

from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Any, Callable

MAX_STEPS = 8
MAX_WRITE = 10_000
LOG = Path(__file__).with_name("agent-run.jsonl")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "broken_calc"


class ToolError(RuntimeError):
    pass


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ToolError(f"path escapes the sandbox: {relative!r}")
    return candidate


def read_file(root: Path, path: str) -> str:
    target = _inside(root, path)
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    return target.read_text(encoding="utf-8")[:MAX_WRITE]


def write_file(root: Path, path: str, content: str) -> str:
    if not path.endswith(".py"):
        raise ToolError("the agent may only write Python files")
    if len(content) > MAX_WRITE:
        raise ToolError("file is too large")
    target = _inside(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


def run_tests(root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    return {
        "returncode": completed.returncode,
        "output": (completed.stdout + completed.stderr)[-2000:],
    }


def execute_tool(root: Path, action: dict[str, Any]) -> Any:
    name = action.get("tool")
    try:
        if name == "read_file":
            return read_file(root, action["path"])
        if name == "write_file":
            return write_file(root, action["path"], action["content"])
        if name == "run_tests":
            return run_tests(root)
    except (KeyError, TypeError) as exc:
        raise ToolError(f"bad arguments for {name!r}") from exc
    raise ToolError(f"unknown tool: {name!r}")


FIX = re.compile(r"(def subtract\([^)]*\)[^\n]*:\n    return )a \+ b")


def scripted_policy(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    step = len(history)
    if step == 0:
        return {"tool": "read_file", "path": "calculator.py"}
    if step == 1:
        return {"tool": "read_file", "path": "test_calculator.py"}
    if step == 2:
        source = history[0]["observation"]
        fixed = FIX.sub(r"\1a - b", source)
        if fixed == source:
            return None
        return {"tool": "write_file", "path": "calculator.py", "content": fixed}
    if step == 3:
        return {"tool": "run_tests"}
    return None


def run_agent(
    root: Path,
    *,
    max_steps: int = MAX_STEPS,
    log_path: Path | None = None,
    policy: Callable[[list[dict[str, Any]]], dict[str, Any] | None] = scripted_policy,
) -> dict[str, Any]:
    root = root.resolve()
    history: list[dict[str, Any]] = []
    with (log_path or LOG).open("w", encoding="utf-8") as log:
        for _ in range(max_steps):
            action = policy(history)
            if action is None:
                break
            try:
                observation, ok = execute_tool(root, action), True
            except (ToolError, subprocess.SubprocessError, OSError) as exc:
                observation, ok = f"error: {exc}", False
            entry = {
                "step": len(history) + 1,
                "tool": action.get("tool"),
                "args": action,
                "ok": ok,
                "observation": observation,
            }
            history.append(entry)
            log.write(json.dumps(entry, default=str) + "\n")

    last = history[-1] if history else {}
    tests = last.get("observation") if last.get("tool") == "run_tests" else None
    passed = isinstance(tests, dict) and tests.get("returncode") == 0
    reason = "done" if passed else ("max_steps" if len(history) >= max_steps else "policy_stopped")
    return {"ok": passed, "steps": len(history), "reason": reason, "history": history}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=EXAMPLE)
    parser.add_argument("--log", type=Path, default=LOG)
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="zero-magic-agent-"))
    shutil.copytree(args.source, workdir, dirs_exist_ok=True)
    result = run_agent(workdir, log_path=args.log)
    for entry in result["history"]:
        print(f"{entry['step']}. {entry['tool']} ok={entry['ok']}")
    print(f"result: {result['reason']} after {result['steps']} steps")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
