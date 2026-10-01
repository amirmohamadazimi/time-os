"""Domain errors raised by services and mapped to HTTP responses by the API layer."""

from typing import Any


class DomainError(Exception):
    code = "domain_error"
    status_code = 400

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409


class ValidationFailed(DomainError):
    code = "validation_error"
    status_code = 422
