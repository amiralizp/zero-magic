"""Neutral error types for the repository layer.

Framework-free (ADR 0007): these exceptions carry no HTTP status and no web
framework import. Services translate them to ``AppError`` where needed.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for repository-level failures."""


class RepositoryIntegrityError(RepositoryError):
    """A referenced id does not exist (foreign-key violation)."""


class RepositoryNotFoundError(RepositoryError):
    """The requested record does not exist."""