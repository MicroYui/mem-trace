class MemTraceError(Exception):
    """Base exception for the MemTrace SDK."""


class NotFoundError(MemTraceError):
    """Raised when a requested MemTrace resource does not exist."""


class BadRequestError(MemTraceError):
    """Raised when MemTrace rejects an invalid request."""


class ForbiddenError(MemTraceError):
    """Raised when MemTrace rejects a request for authz/authn reasons."""
