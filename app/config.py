"""Application settings.

Everything is read once, from environment variables, when the app is created.
Tests build their own Settings so limits can be tightened without patching
module globals.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RATE_LIMIT = 5
DEFAULT_RATE_WINDOW = 60.0
DEFAULT_MAX_PRD_CHARS = 20_000
DEFAULT_MAX_CARDS = 10
DEFAULT_RETRIES = 2
DEFAULT_PROMPT = "v2"
DEFAULT_PRIMARY_MODEL = "mock-strong"
DEFAULT_FALLBACK_MODEL = "mock-fast"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_CHAT_BASE = "https://api.deepseek.com"
DEFAULT_CHAT_MODEL = "deepseek-flash"
DEFAULT_CHAT_PROVIDER = "DeepSeek"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load a local ``.env`` file into ``os.environ`` without overriding it.

    The project keeps secrets out of code and out of the repository, and a
    developer should not have to export every variable before ``uvicorn``. Real
    environment variables always win, so deployments and tests are unaffected.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return

    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        name, _, value = entry.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    app_name: str = "Gantry API"
    api_version: str = "0.3.0"
    environment: str = "local"

    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN

    breakdown_timeout_seconds: float = DEFAULT_TIMEOUT
    breakdown_rate_limit: int = DEFAULT_RATE_LIMIT
    breakdown_rate_window_seconds: float = DEFAULT_RATE_WINDOW
    max_prd_chars: int = DEFAULT_MAX_PRD_CHARS
    max_cards_per_breakdown: int = DEFAULT_MAX_CARDS
    model_retries: int = DEFAULT_RETRIES
    default_prompt_version: str = DEFAULT_PROMPT
    chat_api_key: str = field(default="", repr=False)
    chat_base_url: str = DEFAULT_CHAT_BASE
    chat_models_url: str = ""
    chat_model: str = DEFAULT_CHAT_MODEL
    chat_provider: str = DEFAULT_CHAT_PROVIDER
    chat_session: str = ""

    # SQL Server. Empty db_user means the in-memory store.
    db_server: str = "localhost"
    db_name: str = "Gantry"
    db_user: str = ""
    db_password: str = field(default="", repr=False)

    # Backups are manual on purpose: a timer would fill the disk unattended.
    backup_keep_days: int = 14
    backup_dir: str = "backups"

    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL

    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        key = os.getenv("OPENROUTER_API_KEY") or None
        return cls(
            environment=os.getenv("APP_ENV", "local"),
            frontend_origin=os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN),
            breakdown_timeout_seconds=_float("BREAKDOWN_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
            breakdown_rate_limit=_int("BREAKDOWN_RATE_LIMIT", DEFAULT_RATE_LIMIT),
            breakdown_rate_window_seconds=_float(
                "BREAKDOWN_RATE_WINDOW_SECONDS", DEFAULT_RATE_WINDOW
            ),
            max_prd_chars=_int("MAX_PRD_CHARS", DEFAULT_MAX_PRD_CHARS),
            max_cards_per_breakdown=_int("MAX_CARDS_PER_BREAKDOWN", DEFAULT_MAX_CARDS),
            model_retries=_int("MODEL_RETRIES", DEFAULT_RETRIES),
            default_prompt_version=os.getenv("DEFAULT_PROMPT_VERSION", DEFAULT_PROMPT),
            chat_api_key=os.getenv("CHAT_API_KEY", ""),
            chat_base_url=os.getenv("CHAT_BASE_URL", DEFAULT_CHAT_BASE),
            chat_models_url=os.getenv("CHAT_MODELS_URL", ""),
            chat_model=os.getenv("CHAT_MODEL", DEFAULT_CHAT_MODEL),
            chat_provider=os.getenv("CHAT_PROVIDER", DEFAULT_CHAT_PROVIDER),
            chat_session=os.getenv("CHAT_SESSION", ""),
            db_server=os.getenv("DB_SERVER", "localhost"),
            db_name=os.getenv("DB_NAME", "Gantry"),
            db_user=os.getenv("DB_USER", ""),
            db_password=os.getenv("DB_PASSWORD", ""),
            backup_keep_days=_int("BACKUP_KEEP_DAYS", 14),
            backup_dir=os.getenv("BACKUP_DIR", "backups"),
            primary_model=os.getenv("MODEL_PRIMARY", DEFAULT_PRIMARY_MODEL),
            fallback_model=os.getenv("MODEL_FALLBACK", DEFAULT_FALLBACK_MODEL),
            openrouter_api_key=key,
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE),
        )
