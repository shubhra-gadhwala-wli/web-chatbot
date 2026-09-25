"""Typed repository errors from data-api/repository-contract.md."""
from __future__ import annotations


class RepositoryError(Exception):
    pass


class NotFound(RepositoryError):
    """API 404. Missing and foreign are indistinguishable by construction."""

    def __init__(self, resource: str, opaque_id: str | None = None):
        super().__init__("not_found")
        self.resource = resource
        self.opaque_id = opaque_id


class StateConflict(RepositoryError):
    def __init__(self, resource: str, current_state: str):
        super().__init__("state_conflict")
        self.resource = resource
        self.current_state = current_state


class IdempotencyConflict(RepositoryError):
    def __init__(self, key: str):
        super().__init__("idempotency_conflict")
        self.key = key


class ValidationError(RepositoryError):
    def __init__(self, code: str, field: str | None = None):
        super().__init__(code)
        self.code = code
        self.field = field
