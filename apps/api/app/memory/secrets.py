"""Secret detection and redaction for P0.

Deterministic regex-based detection. When content is flagged as secret:
- events store redacted content (raw original is not persisted in P0),
- no retrievable memory is created by the writer,
- the gate hard-rejects any sensitivity=secret memory that does slip in.
"""
from __future__ import annotations

import re

# Patterns chosen to be deterministic and demo-friendly, not exhaustive.
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),  # OpenAI-style key
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub PAT
    re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}\b"),  # Google API key
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),  # Slack token
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),  # JWT
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
    ),  # PEM private key block
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:password|passwd)\s+is\s+\S+"),  # "my password is hunter2"
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]

_REDACTION = "[REDACTED]"
_SECRET_KEY_TERMS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "credentials",
    "access_key",
    "private_key",
)


def is_secret_like_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower().replace("-", "_")
    return any(term in normalized for term in _SECRET_KEY_TERMS)


def contains_secret(text: str | None) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _SECRET_PATTERNS)


def redact(text: str | None) -> str:
    if not text:
        return text or ""
    out = text
    for p in _SECRET_PATTERNS:
        out = p.sub(_REDACTION, out)
    return out


__all__ = ["contains_secret", "redact", "is_secret_like_key"]
