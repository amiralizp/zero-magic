"""Architecture fitness: enforce import boundaries between layers (S7).

Uses the ``ast`` module to read imports only, without executing code.
Marked xfail until the S8 refactor removes the existing violations.

What this test does NOT catch: indirect imports (services -> app/errors.py ->
fastapi), routers that call repository methods through an injected dependency,
and business rules placed in routers. These are covered by docs/critique.md
and review, not by this test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

SQL_DRIVERS = {"pytds", "pyodbc", "sqlalchemy", "psycopg", "psycopg2", "pymssql"}


def _layer(rel: str) -> str | None:
    if not rel.startswith("app/"):
        return None
    parts = rel[len("app/"):].split("/")
    top = parts[0]
    if top == "api":
        return "http"
    if top == "services":
        return "service"
    if top == "ai":
        return "ai"
    if top in {"store.py", "store_sql.py", "db.py", "backup.py"} and len(parts) == 1:
        return "repository"
    if top in {"main.py", "presenters.py"}:
        return "http"
    return None


def _resolve_import(node: ast.AST, rel: str) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name if node.names else None
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return node.module
        parts = rel.split("/")
        pkg = parts[:-1]
        for _ in range(node.level - 1):
            if pkg:
                pkg.pop()
        if node.module:
            pkg = pkg + node.module.split(".")
        if not pkg:
            return None
        return ".".join(pkg)
    return None


def _imports_with_lines(path: Path, rel: str) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = _resolve_import(node, rel)
            if mod:
                result.append((node.lineno, mod))
    return result


def _is(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        layer = _layer(rel)
        if layer is None:
            continue
        for lineno, mod in _imports_with_lines(path, rel):
            if layer == "http":
                if (
                    _is(mod, "app.store")
                    or _is(mod, "app.store_sql")
                    or _is(mod, "app.db")  # main.py is the wiring point; S8 must decide whether it gets an allowlist.
                    or _is(mod, "app.backup")
                ):
                    found.append(f"{rel}:{lineno}: HTTP imports repository/store ({mod})")
                if any(_is(mod, d) for d in SQL_DRIVERS):
                    found.append(f"{rel}:{lineno}: HTTP imports SQL driver ({mod})")
            if layer == "service":
                if _is(mod, "fastapi") or _is(mod, "starlette"):
                    found.append(f"{rel}:{lineno}: Service imports web framework ({mod})")
                if _is(mod, "app.api") or _is(mod, "app.presenters"):
                    found.append(f"{rel}:{lineno}: Service imports HTTP/presenters ({mod})")
                if _is(mod, "app.store_sql"):
                    found.append(f"{rel}:{lineno}: Service imports concrete DB ({mod})")
                if any(_is(mod, d) for d in SQL_DRIVERS):
                    found.append(f"{rel}:{lineno}: Service imports SQL driver ({mod})")
            if layer == "repository":
                if _is(mod, "app.services") or _is(mod, "app.api"):
                    found.append(f"{rel}:{lineno}: Repository imports service/api ({mod})")
                if _is(mod, "fastapi") or _is(mod, "starlette"):
                    found.append(f"{rel}:{lineno}: Repository imports web framework ({mod})")
            if layer == "ai":
                if (
                    _is(mod, "app.store")
                    or _is(mod, "app.store_sql")
                    or _is(mod, "app.db")
                    or _is(mod, "app.backup")
                ):
                    found.append(f"{rel}:{lineno}: AI imports repository/store ({mod})")
                if _is(mod, "app.services"):
                    found.append(f"{rel}:{lineno}: AI imports services ({mod})")
            if mod == "httpx" and layer != "ai":
                found.append(f"{rel}:{lineno}: non-AI layer imports httpx ({mod})")
    return found


@pytest.mark.xfail(reason="S8 removes the violations; then remove this marker", strict=True)
def test_architecture_imports():
    violations = _violations()
    assert not violations, "Architecture violations:\n" + "\n".join(violations)
