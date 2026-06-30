"""Encrypted raw-payload store (ROADMAP §3.4 / ADR-017, default-off).

ADR-017 keeps raw secret payloads out of storage by default. When an operator
explicitly enables raw-payload retention they must provide an encrypted store;
this module implements it. Encryption uses ``cryptography``'s Fernet (AES-128-CBC
+ HMAC), lazy-imported from the optional ``crypto`` extra — without the dependency
or a key the store reports ``available = False`` and the existing guard keeps
retention disabled.

The store maps an opaque ``raw_payload_ref`` to ciphertext. This reference
implementation keeps ciphertext in-process (a real deployment would back it with
an object store), but the *encryption* is real, so plaintext secrets never sit in
memory unencrypted beyond the encrypt/decrypt call.
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@runtime_checkable
class RawPayloadStore(Protocol):
    name: str

    @property
    def available(self) -> bool:
        ...

    def put(self, ref: str, plaintext: str) -> None:
        ...

    def get(self, ref: str) -> str | None:
        ...


class FernetRawPayloadStore:
    """Fernet-encrypted payload store (lazy ``cryptography`` import, degrade-safe)."""

    name = "fernet"

    def __init__(self, *, key: str) -> None:
        self._fernet = None
        self._cipher: dict[str, bytes] = {}
        if not key:
            self._available = False
            return
        try:  # cryptography is an optional extra
            from cryptography.fernet import Fernet  # type: ignore
        except ModuleNotFoundError:
            logger.warning(
                "raw payload retention requires the 'crypto' extra "
                "(pip install '.[crypto]'); encrypted store disabled."
            )
            self._available = False
            return
        try:
            self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
            self._available = True
        except Exception:  # noqa: BLE001 - bad key must not break startup
            logger.warning("Invalid raw payload encryption key; encrypted store disabled.")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def put(self, ref: str, plaintext: str) -> None:
        if not self._available or self._fernet is None:
            raise RuntimeError("encrypted raw payload store is not available")
        self._cipher[ref] = self._fernet.encrypt(plaintext.encode("utf-8"))

    def get(self, ref: str) -> str | None:
        if not self._available or self._fernet is None:
            return None
        token = self._cipher.get(ref)
        if token is None:
            return None
        return self._fernet.decrypt(token).decode("utf-8")


def build_raw_payload_store(settings) -> RawPayloadStore | None:
    """Construct the encrypted store when retention is enabled and configured.

    Returns ``None`` (the default) unless ``raw_payload_retention_enabled`` is on,
    ``governance_enabled`` is on, and the store URL uses the ``encrypted://``
    scheme — mirroring the redaction-policy guard.
    """
    if not getattr(settings, "raw_payload_retention_enabled", False):
        return None
    if not getattr(settings, "governance_enabled", False):
        return None
    url = getattr(settings, "raw_payload_store_url", "") or ""
    if not url.startswith("encrypted://"):
        return None
    # encrypted://<backend>; the key comes from settings, never the URL.
    urlparse(url)  # validate shape; reference impl ignores the host segment
    return FernetRawPayloadStore(key=getattr(settings, "raw_payload_encryption_key", ""))


__all__ = ["RawPayloadStore", "FernetRawPayloadStore", "build_raw_payload_store"]
