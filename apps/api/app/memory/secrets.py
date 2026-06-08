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
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]

_REDACTION = "[REDACTED]"


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


__all__ = ["contains_secret", "redact"]
