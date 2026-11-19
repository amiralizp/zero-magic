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

# --- Allowlist (S8.8b) -------------------------------------------------------
WIRING_POINTS = {"app/main.py", "app/api/deps.py"}
KNOWN_DEBT = {
    "app/presenters.py": "S8.11 presenters read actors through the repository",
}


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
    if top == "repositories" and len(parts) == 2 and parts[1] in {"memory.py", "sql_server.py", "factory.py"}:
        return "repository"
    if top == "backup.py" and len(parts) == 1:
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


def _imports_with_lines(path: Path, rel: str) -> list[tuple[int, str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append((node.lineno, alias.name, [alias.asname or alias.name.split(".")[-1]]))
        elif isinstance(node, ast.ImportFrom):
            mod = _resolve_import(node, rel)
            if mod:
                names = [alias.name for alias in node.names]
                result.append((node.lineno, mod, names))
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
        source = path.read_text(encoding="utf-8")
        found.extend(_violations_for_source(source, rel))
    return found


def _violations_for_source(source: str, rel: str) -> list[str]:
    """Check a single source string (used by self-tests)."""
    found: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"{rel}:0: SyntaxError"]

    entries: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                entries.append((node.lineno, alias.name, [alias.asname or alias.name.split(".")[-1]]))
        elif isinstance(node, ast.ImportFrom):
            parts = rel.split("/")
            pkg = parts[:-1]
            level = node.level
            if level == 0:
                mod = node.module
            else:
                for _ in range(level - 1):
                    if pkg:
                        pkg.pop()
                if node.module:
                    pkg = pkg + node.module.split(".")
                mod = ".".join(pkg) if pkg else None
            if mod:
                names = [alias.name for alias in node.names]
                entries.append((node.lineno, mod, names))

    layer = _layer(rel)
    if layer is None:
        return found

    for lineno, mod, names in entries:
        if layer == "http":
            if _is(mod, "app.repositories.factory"):
                if rel in WIRING_POINTS:
                    allowed = {"Repository", "build_repository"}
                elif rel in KNOWN_DEBT:
                    allowed = {"Repository"}
                else:
                    allowed = {"Repository"}
                if allowed is not None:
                    bad = [n for n in names if n not in allowed]
                    if bad:
                        found.append(
                            f"{rel}:{lineno}: HTTP imports forbidden name(s) "
                            f"{bad} from app.repositories.factory"
                        )
            elif (
                _is(mod, "app.repositories.memory")
                or _is(mod, "app.repositories.sql_server")
                or _is(mod, "app.backup")
            ):
                found.append(f"{rel}:{lineno}: HTTP imports repository/store ({mod})")
            if any(_is(mod, d) for d in SQL_DRIVERS):
                found.append(f"{rel}:{lineno}: HTTP imports SQL driver ({mod})")
            if mod == "httpx":
                found.append(f"{rel}:{lineno}: non-AI layer imports httpx ({mod})")
        if layer == "service":
            if _is(mod, "fastapi") or _is(mod, "starlette"):
                found.append(f"{rel}:{lineno}: Service imports web framework ({mod})")
            if _is(mod, "app.api") or _is(mod, "app.presenters"):
                found.append(f"{rel}:{lineno}: Service imports HTTP/presenters ({mod})")
            if _is(mod, "app.repositories.sql_server") or _is(mod, "app.repositories.memory"):
                found.append(f"{rel}:{lineno}: Service imports concrete repository ({mod})")
            if any(_is(mod, d) for d in SQL_DRIVERS):
                found.append(f"{rel}:{lineno}: Service imports SQL driver ({mod})")
        if layer == "repository":
            if _is(mod, "app.services") or _is(mod, "app.api"):
                found.append(f"{rel}:{lineno}: Repository imports service/api ({mod})")
            if _is(mod, "fastapi") or _is(mod, "starlette"):
                found.append(f"{rel}:{lineno}: Repository imports web framework ({mod})")
        if layer == "ai":
            if (
                _is(mod, "app.repositories.memory")
                or _is(mod, "app.repositories.sql_server")
                or _is(mod, "app.repositories.factory")
                or _is(mod, "app.backup")
            ):
                found.append(f"{rel}:{lineno}: AI imports repository/store ({mod})")
            if _is(mod, "app.services"):
                found.append(f"{rel}:{lineno}: AI imports services ({mod})")
    return found


def _check(source: str, rel: str) -> list[str]:
    return _violations_for_source(source, rel)


# --- Self-tests of the checker (S8.8b) -------------------------------------

def test_checker_flags_router_importing_build_repository():
    src = "from app.repositories.factory import build_repository\n"
    vs = _check(src, "app/api/foo.py")
    assert any("forbidden name" in v and "build_repository" in v for v in vs)


def test_checker_flags_service_importing_memory():
    src = "from app.repositories.memory import InMemoryRepository\n"
    vs = _check(src, "app/services/foo.py")
    assert any("concrete repository" in v for v in vs)


def test_checker_flags_non_ai_httpx():
    src = "import httpx\n"
    vs = _check(src, "app/api/foo.py")
    assert any("httpx" in v for v in vs)


def test_checker_allows_wiring_point():
    src = "from app.repositories.factory import Repository, build_repository\n"
    vs = _check(src, "app/main.py")
    assert vs == []


def test_checker_allows_api_repository_type():
    src = "from app.repositories.factory import Repository\n"
    vs = _check(src, "app/api/foo.py")
    assert vs == []


def test_checker_allows_known_debt():
    src = "from app.repositories.factory import Repository\n"
    vs = _check(src, "app/presenters.py")
    assert vs == []


def test_checker_flags_known_debt_extra_name():
    src = "from app.repositories.factory import Repository, build_repository\n"
    vs = _check(src, "app/presenters.py")
    assert any("forbidden name" in v and "build_repository" in v for v in vs)


def test_checker_flags_known_debt_other_module():
    src = "from app.repositories.memory import InMemoryRepository\n"
    vs = _check(src, "app/presenters.py")
    assert len(vs) > 0


def test_architecture_imports():
    violations = _violations()
    assert not violations, "Architecture violations:\n" + "\n".join(violations)
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
                    if folder == "services" and node.level > 0 and node.module == "errors":
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
    from app.repositories.memory import CardRecord as SCard, CommentRecord as SComment, PRDRecord as SPrd

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
                if node.level == 0 and node.module in {"app.repositories.memory", "app.repositories.sql_server"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from {node.module}")
                if node.level > 0 and node.module in {"memory", "sql_server", "factory"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from .{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"app.repositories.memory", "app.repositories.sql_server"}:
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


def test_chat_router_has_no_hint_functions():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    rel = "app/api/chat.py"
    path = root / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and node.name.endswith("_hint"):
                raise AssertionError(
                    f"{rel}:{node.lineno}: router defines hint function {node.name}"
                )


def test_services_do_not_import_presenters():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in (root / "app" / "services").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.presenters" or alias.name.startswith("app.presenters"):
                        raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
                    if alias.name == ".presenters" or alias.name == "presenters":
                        raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "app.presenters" or mod.startswith("app.presenters"):
                    raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")
                # relative imports: from ..presenters import ...
                if node.level > 0 and mod == "presenters":
                    raise AssertionError(f"{rel}:{node.lineno}: imports from .presenters")


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

def test_services_and_api_do_not_import_sqlalchemy_or_psycopg():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for folder in ("services", "api"):
        for path in (root / "app" / folder).rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top in {"sqlalchemy", "psycopg"}:
                            raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    top = mod.split(".")[0]
                    if top in {"sqlalchemy", "psycopg"}:
                        raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")


def test_only_postgres_repository_imports_sqlalchemy_or_psycopg():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    allowed_file = "app/repositories/postgres.py"
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel == allowed_file:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in {"sqlalchemy", "psycopg"}:
                        raise AssertionError(f"{rel}:{node.lineno}: imports {alias.name}")
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                top = mod.split(".")[0]
                if top in {"sqlalchemy", "psycopg"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from {mod}")


def test_postgres_repository_only_imported_by_factory():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel == "app/repositories/factory.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.repositories.postgres":
                        raise AssertionError(f"{rel}:{node.lineno}: imports app.repositories.postgres")
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "app.repositories.postgres":
                    raise AssertionError(f"{rel}:{node.lineno}: imports from app.repositories.postgres")

def test_services_and_api_may_import_repository_errors():
    # Neutral repository errors are explicitly allowed in services and api.
    src = "from app.repositories.errors import RepositoryIntegrityError\n"
    vs = _check(src, "app/services/foo.py")
    assert vs == [], f"repository errors import was flagged: {vs}"

    vs2 = _check(src, "app/api/foo.py")
    assert vs2 == [], f"repository errors import was flagged: {vs2}"
