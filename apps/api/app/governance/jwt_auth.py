"""JWT / OIDC bearer authentication (ROADMAP §3.4, default-off).

A second authentication method alongside API keys. HS256 is verified natively
with the standard library (no third-party dependency), so the default + tests
need nothing extra; RS256/ES256 delegate to the optional ``PyJWT`` ``jwt`` extra
and degrade with a clear error when it is absent. Claims map to the existing
``Principal`` (``sub`` -> principal_id, ``roles``, ``workspace_ids``/``workspaces``).

Default-off via ``MEMTRACE_JWT_AUTH_ENABLED``. When enabled, this is consulted
only for bearer tokens that look like a JWT (three dot-separated segments); other
tokens fall through to API-key auth, so the two methods coexist.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.runtime.models import Principal


class JwtError(Exception):
    """Raised when a token is absent, malformed, or fails verification."""


def looks_like_jwt(token: str | None) -> bool:
    return bool(token) and token.count(".") == 2


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _principal_from_claims(claims: dict) -> Principal:
    sub = claims.get("sub")
    if not sub:
        raise JwtError("jwt missing sub claim")
    roles = claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    workspaces = claims.get("workspace_ids")
    if workspaces is None:
        workspaces = claims.get("workspaces", [])
    if isinstance(workspaces, str):
        workspaces = [workspaces]
    return Principal(
        principal_id=str(sub),
        kind="jwt",
        workspace_ids=[str(w) for w in (workspaces or [])],
        roles=[str(r) for r in (roles or [])],
    )


def _validate_claims(claims: dict, settings) -> None:
    now = time.time()
    exp = claims.get("exp")
    if exp is not None and now > float(exp):
        raise JwtError("jwt expired")
    nbf = claims.get("nbf")
    if nbf is not None and now < float(nbf):
        raise JwtError("jwt not yet valid")
    if settings.jwt_issuer and claims.get("iss") != settings.jwt_issuer:
        raise JwtError("jwt issuer mismatch")
    if settings.jwt_audience:
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if settings.jwt_audience not in audiences:
            raise JwtError("jwt audience mismatch")


def verify_jwt(token: str | None, settings) -> Principal:
    """Verify a JWT and return a Principal, or raise ``JwtError``."""
    if not token or token.count(".") != 2:
        raise JwtError("not a JWT")
    header_b64, payload_b64, sig_b64 = token.split(".")
    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception as exc:  # noqa: BLE001
        raise JwtError("malformed jwt header") from exc
    alg = header.get("alg")
    expected_alg = (settings.jwt_algorithm or "HS256").upper()
    if alg != expected_alg:
        raise JwtError(f"jwt alg mismatch: expected {expected_alg}")

    if alg == "HS256":
        if not settings.jwt_secret:
            raise JwtError("HS256 jwt requires jwt_secret")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
            raise JwtError("jwt signature mismatch")
        try:
            claims = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:  # noqa: BLE001
            raise JwtError("malformed jwt payload") from exc
        _validate_claims(claims, settings)
        return _principal_from_claims(claims)

    if alg in ("RS256", "ES256"):
        try:  # asymmetric verification needs the optional 'jwt' extra
            import jwt as pyjwt  # type: ignore
        except ModuleNotFoundError as exc:
            raise JwtError(f"{alg} jwt requires the 'jwt' extra (pip install '.[jwt]')") from exc
        if not settings.jwt_public_key:
            raise JwtError(f"{alg} jwt requires jwt_public_key")
        try:
            claims = pyjwt.decode(
                token,
                settings.jwt_public_key,
                algorithms=[alg],
                audience=settings.jwt_audience or None,
                issuer=settings.jwt_issuer or None,
                options={"verify_aud": bool(settings.jwt_audience), "verify_iss": bool(settings.jwt_issuer)},
            )
        except Exception as exc:  # noqa: BLE001 - PyJWT raises many subtypes
            raise JwtError(f"jwt verification failed: {exc}") from exc
        return _principal_from_claims(claims)

    raise JwtError(f"unsupported jwt alg: {alg}")


def encode_hs256(claims: dict, secret: str) -> str:
    """Encode an HS256 JWT (test/helper utility; not used on the hot path)."""

    def _seg(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header_b64 = _seg({"alg": "HS256", "typ": "JWT"})
    payload_b64 = _seg(claims)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    return f"{header_b64}.{payload_b64}.{sig_b64}"


__all__ = ["JwtError", "looks_like_jwt", "verify_jwt", "encode_hs256"]
