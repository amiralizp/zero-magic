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


def test_domain_errors_is_framework_free():
    import subprocess
    import sys

    code = (
        "import sys; import app.domain_errors; "
        "assert 'fastapi' not in sys.modules, 'fastapi loaded'; "
        "assert 'starlette' not in sys.modules, 'starlette loaded'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_app_error_is_same_class():
    from app.domain_errors import AppError as DomainAppError
    from app.errors import AppError as ErrorsAppError

    assert ErrorsAppError is DomainAppError


def test_services_and_ai_do_not_import_app_errors():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for folder in ("services", "ai"):
        for path in (root / "app" / folder).rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module in {"app.errors", "app.errors"}:
                        raise AssertionError(f"{rel}:{node.lineno}: imports from app.errors")
                    if node.level > 0 and node.module == "errors":
                        raise AssertionError(f"{rel}:{node.lineno}: imports from .errors")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "app.errors":
                            raise AssertionError(f"{rel}:{node.lineno}: imports app.errors")


def test_records_is_framework_and_sql_free():
    import subprocess
    import sys

    code = (
        "import sys; import app.records; "
        "assert 'fastapi' not in sys.modules, 'fastapi loaded'; "
        "assert 'starlette' not in sys.modules, 'starlette loaded'; "
        "assert all(m not in sys.modules for m in ('pytds','pyodbc','sqlalchemy','psycopg','psycopg2','pymssql')), 'sql driver loaded'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_store_records_are_same_class():
    from app.records import CardRecord as RCard, CommentRecord as RComment, PRDRecord as RPrd
    from app.store import CardRecord as SCard, CommentRecord as SComment, PRDRecord as SPrd

    assert SCard is RCard
    assert SComment is RComment
    assert SPrd is RPrd


def test_services_do_not_import_store_modules():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in (root / "app" / "services").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module in {"app.store", "app.store_sql"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from {node.module}")
                if node.level > 0 and node.module in {"store", "store_sql"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from .{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"app.store", "app.store_sql"}:
                        raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")


def test_read_routers_do_not_call_store_methods():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("app/api/cards.py", "app/api/prds.py"):
        path = root / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "store":
                    raise AssertionError(
                        f"{rel}:{node.lineno}: router calls store.{node.func.attr}(...)"
                    )


def test_meta_does_not_touch_app_state_or_store_methods():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/api/meta.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # No access to app.state or request.app.state
            if node.attr == "state":
                raise AssertionError(f"{rel}:{node.lineno}: uses app.state")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "store":
                raise AssertionError(
                    f"{rel}:{node.lineno}: meta router calls store.{node.func.attr}(...)"
                )


def test_chat_service_is_framework_free():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/services/chat.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"fastapi", "starlette", "httpx", "app.api", "app.presenters"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden or alias.name.split(".")[0] in {"fastapi", "starlette", "httpx"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
                if alias.name.startswith("app.api") or alias.name.startswith("app.presenters"):
                    raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in forbidden or mod.startswith("fastapi") or mod.startswith("starlette") or mod.startswith("httpx"):
                raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")
            if mod.startswith("app.api") or mod.startswith("app.presenters"):
                raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")


def test_chat_router_does_not_call_store_methods():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/api/chat.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "store":
                raise AssertionError(
                    f"{rel}:{node.lineno}: chat router calls store.{node.func.attr}(...)"
                )


def test_backup_service_is_framework_and_sql_free():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/services/backup.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_modules = {"fastapi", "starlette", "pytds", "httpx"}
    forbidden_imports = {"app.api", "app.presenters"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in forbidden_modules:
                    raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
                if alias.name in forbidden_imports or alias.name.startswith("app.api") or alias.name.startswith("app.presenters"):
                    raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0]
            if top in forbidden_modules:
                raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")
            if mod in forbidden_imports or mod.startswith("app.api") or mod.startswith("app.presenters"):
                raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")


def test_ops_router_does_not_import_backup_or_pytds():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/api/ops.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.backup" or alias.name.startswith("app.backup"):
                    raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
                if alias.name == "pytds":
                    raise AssertionError(f"{rel}:{node.lineno}: imports pytds")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "app.backup" or mod.startswith("app.backup"):
                raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")
            if mod == "pytds":
                raise AssertionError(f"{rel}:{node.lineno}: imports from pytds")
