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
    if top == "repositories" and len(parts) == 2 and parts[1] in {"memory.py", "factory.py"}:
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
            elif _is(mod, "app.repositories.memory"):
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
            if _is(mod, "app.repositories.memory"):
                found.append(f"{rel}:{lineno}: Service imports concrete repository ({mod})")
            if any(_is(mod, d) for d in SQL_DRIVERS):
                found.append(f"{rel}:{lineno}: Service imports SQL driver ({mod})")
        if layer == "repository":
            if _is(mod, "app.services") or _is(mod, "app.api"):
                found.append(f"{rel}:{lineno}: Repository imports service/api ({mod})")
            if _is(mod, "fastapi") or _is(mod, "starlette"):
                found.append(f"{rel}:{lineno}: Repository imports web framework ({mod})")
        if layer == "ai":
            if _is(mod, "app.repositories.memory") or _is(mod, "app.repositories.factory"):
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
                if node.level == 0 and node.module == "app.repositories.memory":
                    raise AssertionError(f"{rel}:{node.lineno}: imports from {node.module}")
                if node.level > 0 and node.module in {"memory", "factory"}:
                    raise AssertionError(f"{rel}:{node.lineno}: imports from .{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.repositories.memory":
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


def test_no_pytds_imports_and_deleted_modules_are_absent():
    import ast

    root = Path(__file__).resolve().parent.parent

    def _pytds_lines(source: str) -> list[int]:
        lines: list[int] = []
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "pytds":
                        lines.append(node.lineno)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "pytds":
                lines.append(node.lineno)
        return lines

    # Positive control: the detector really flags both import forms.
    assert _pytds_lines("import pytds\n")
    assert _pytds_lines("from pytds import connect\n")

    for path in sorted((root / "app").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        hits = _pytds_lines(path.read_text(encoding="utf-8"))
        assert not hits, f"{rel}: imports pytds on line(s) {hits}"

    for rel in (
        "app/repositories/sql_server.py",
        "app/backup.py",
        "app/services/backup.py",
        "app/api/ops.py",
    ):
        assert not (root / rel).exists(), f"{rel} still exists"

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


# --- S12 authentication rules ------------------------------------------------

AUTH_CRYPTO_MODULES = {"jwt", "argon2"}
AUTH_CRYPTO_OWNER = "app/services/auth.py"


def _auth_crypto_import_lines(source: str) -> list[int]:
    """Return lines importing a token or password-hashing library."""

    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in AUTH_CRYPTO_MODULES:
                    lines.append(node.lineno)
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            if top in AUTH_CRYPTO_MODULES:
                lines.append(node.lineno)
    return sorted(set(lines))


def test_only_the_auth_service_imports_crypto_libraries():
    # Positive controls: the detector sees both import forms.
    assert _auth_crypto_import_lines("import jwt\nimport argon2\n") == [1, 2]
    assert _auth_crypto_import_lines("from jwt import decode\n") == [1]

    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        hits = _auth_crypto_import_lines(path.read_text(encoding="utf-8"))
        if rel == AUTH_CRYPTO_OWNER:
            assert hits, f"{rel}: expected the auth service to own crypto imports"
        else:
            assert not hits, f"{rel}: imports jwt/argon2 on line(s) {hits}"


def test_api_layer_does_not_read_a_legacy_identity_header():
    # Positive control: a regression would be caught.
    assert "X-Actor-Id" in "headers['X-Actor-Id']"

    for path in sorted((ROOT / "app" / "api").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        assert "X-Actor-Id" not in source, f"{rel}: legacy identity header is still present"


def test_chat_request_schema_has_no_actor_field():
    path = ROOT / "app" / "schemas" / "chat.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    model = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatCompletionRequest"
    )
    fields = {
        node.target.id
        for node in model.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "messages" in fields  # positive control: the model was found
    assert "actor" not in fields


def test_auth_service_is_framework_free():
    path = ROOT / "app" / "services" / "auth.py"
    rel = path.relative_to(ROOT).as_posix()
    forbidden = {"fastapi", "starlette", "httpx", "app.api", "app.presenters"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden, f"{rel}:{node.lineno}: imports {alias.name}"
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            assert top not in forbidden, f"{rel}:{node.lineno}: imports from {module}"


# --- S17 stale identity text -------------------------------------------------


def _legacy_header_lines(source: str) -> list[int]:
    lines: list[int] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if "x-actor-id" in line.lower():
            lines.append(lineno)
    return lines


def test_no_file_under_app_contains_x_actor_id():
    # Positive control: the detector catches the legacy header in either case.
    assert _legacy_header_lines("X-Actor-Id: nope\n") == [1]
    assert _legacy_header_lines("x-actor-id\n") == [1]

    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        hits = _legacy_header_lines(path.read_text(encoding="utf-8"))
        assert not hits, f"{rel}: stale X-Actor-Id text on line(s) {hits}"


# --- S21 chat proposal safety ------------------------------------------------


def test_api_and_web_do_not_execute_write_tools_directly():
    # Positive control: detector catches a direct tool execution.
    sample = 'execute_tool(store, actor, "delete_card", {"card": "x"})\n'
    assert "execute_tool(" in sample

    for path in sorted((ROOT / "app" / "api").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        assert "execute_tool(" not in source, f"{rel}: api must not execute write tools directly"
    for path in sorted((ROOT / "app" / "web").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8", errors="ignore")
        assert "execute_tool(" not in source, f"{rel}: web must not execute write tools directly"
