"""JWT/OIDC bearer auth tests (ROADMAP §3.4, default-off).

Covers native HS256 verify/encode round-trip, expiry/issuer/audience checks,
the Principal mapping, malformed-token rejection, and the require_api_key
integration (JWT honored when enabled, ignored when off).
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from app.api import deps
from app.config import Settings, get_settings
from app.governance.jwt_auth import JwtError, encode_hs256, looks_like_jwt, verify_jwt


def _settings(**kw) -> Settings:
    base = dict(jwt_auth_enabled=True, jwt_algorithm="HS256", jwt_secret="topsecret")
    base.update(kw)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_looks_like_jwt():
    assert looks_like_jwt("a.b.c")
    assert not looks_like_jwt("not-a-jwt")
    assert not looks_like_jwt(None)


def test_hs256_round_trip_maps_principal():
    token = encode_hs256(
        {"sub": "user-1", "roles": ["reader"], "workspace_ids": ["ws_a"]}, "topsecret"
    )
    principal = verify_jwt(token, _settings())
    assert principal.kind == "jwt"
    assert principal.principal_id == "user-1"
    assert principal.roles == ["reader"]
    assert principal.workspace_ids == ["ws_a"]


def test_hs256_rejects_tampered_signature():
    token = encode_hs256({"sub": "u"}, "topsecret")
    with pytest.raises(JwtError, match="signature"):
        verify_jwt(token, _settings(jwt_secret="different"))


def test_rejects_expired_token():
    token = encode_hs256({"sub": "u", "exp": int(time.time()) - 10}, "topsecret")
    with pytest.raises(JwtError, match="expired"):
        verify_jwt(token, _settings())


def test_enforces_issuer_and_audience():
    token = encode_hs256({"sub": "u", "iss": "wrong", "aud": "api"}, "topsecret")
    with pytest.raises(JwtError, match="issuer"):
        verify_jwt(token, _settings(jwt_issuer="right"))
    token2 = encode_hs256({"sub": "u", "iss": "right", "aud": "other"}, "topsecret")
    with pytest.raises(JwtError, match="audience"):
        verify_jwt(token2, _settings(jwt_issuer="right", jwt_audience="api"))


def test_missing_sub_rejected():
    token = encode_hs256({"roles": ["reader"]}, "topsecret")
    with pytest.raises(JwtError, match="sub"):
        verify_jwt(token, _settings())


def test_non_jwt_token_raises():
    with pytest.raises(JwtError, match="not a JWT"):
        verify_jwt("opaque-api-key", _settings())


# ----------------------- require_api_key integration ----------------- #


@pytest.mark.asyncio
async def test_require_api_key_accepts_valid_jwt(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_SECRET", "topsecret")
    get_settings.cache_clear()
    token = encode_hs256({"sub": "user-9", "roles": ["writer"], "workspace_ids": ["ws"]}, "topsecret")
    principal = await deps.require_api_key(authorization=f"Bearer {token}", x_api_key=None)
    assert principal.kind == "jwt"
    assert principal.principal_id == "user-9"


@pytest.mark.asyncio
async def test_require_api_key_rejects_bad_jwt(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_SECRET", "topsecret")
    get_settings.cache_clear()
    bad = encode_hs256({"sub": "u"}, "wrong-secret")
    with pytest.raises(HTTPException) as exc:
        await deps.require_api_key(authorization=f"Bearer {bad}", x_api_key=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_jwt_off_by_default_ignores_jwt_shape(monkeypatch):
    # auth on but jwt off + legacy api key: a non-JWT token still works as before.
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.delenv("MEMTRACE_JWT_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("MEMTRACE_API_KEY", "legacy-key")
    get_settings.cache_clear()
    # The legacy token gate is the no-repository path; ensure app_state has no
    # repository leaked in from another test in the full-suite run.
    monkeypatch.setattr(deps.app_state, "repository", None, raising=False)
    principal = await deps.require_api_key(authorization="Bearer legacy-key", x_api_key=None)
    assert principal.kind == "legacy_api_key"


# ------------- enabled-state HS256 E2E through the dependency ---------- #

_SHARED_SECRET = "e2e-shared-secret"


def _enable_jwt(monkeypatch) -> None:
    """Turn on auth + HS256 JWT with a known shared secret via env."""
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("MEMTRACE_JWT_SECRET", _SHARED_SECRET)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_require_api_key_hs256_resolves_workspace_claim(monkeypatch):
    # Enabled-state HS256 minted in-test with the shared secret, driven through
    # the real request dependency via an Authorization: Bearer header. The
    # resolved principal must carry the sub/roles/workspace claims verbatim.
    _enable_jwt(monkeypatch)
    token = encode_hs256(
        {"sub": "user-42", "roles": ["reader", "writer"], "workspace_ids": ["ws_a", "ws_b"]},
        _SHARED_SECRET,
    )
    principal = await deps.require_api_key(authorization=f"Bearer {token}", x_api_key=None)
    assert principal.kind == "jwt"
    assert principal.principal_id == "user-42"
    assert principal.roles == ["reader", "writer"]
    assert principal.workspace_ids == ["ws_a", "ws_b"]


@pytest.mark.asyncio
async def test_require_api_key_tampered_signature_returns_403(monkeypatch):
    # A token whose signature segment has been mutated is an invalid credential.
    # MemTrace's established auth contract (ADR-016/H3, locked by
    # tests/api/test_auth.py: missing->401, wrong->403) returns 403 for a
    # *supplied but invalid* credential — the same status the static API-key
    # path uses for a wrong key (deps.py). Only a *missing* credential is 401.
    _enable_jwt(monkeypatch)
    token = encode_hs256({"sub": "user-42"}, _SHARED_SECRET)
    head, payload, sig = token.split(".")
    mangled_sig = ("Z" if not sig.startswith("Z") else "Y") + sig[1:]
    tampered = f"{head}.{payload}.{mangled_sig}"
    with pytest.raises(HTTPException) as exc:
        await deps.require_api_key(authorization=f"Bearer {tampered}", x_api_key=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_api_key_expired_jwt_returns_403(monkeypatch):
    # An expired but well-signed token is a supplied-but-invalid credential, so
    # it maps to 403 consistently with the tampered-signature and wrong-API-key
    # cases (missing credential would be 401).
    _enable_jwt(monkeypatch)
    token = encode_hs256(
        {"sub": "user-42", "exp": int(time.time()) - 30}, _SHARED_SECRET
    )
    with pytest.raises(HTTPException) as exc:
        await deps.require_api_key(authorization=f"Bearer {token}", x_api_key=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_api_key_missing_credential_returns_401(monkeypatch):
    # The one 401 case: no credential supplied at all (the other half of the
    # missing->401 / invalid->403 contract), asserted under the JWT-enabled path.
    _enable_jwt(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await deps.require_api_key(authorization=None, x_api_key=None)
    assert exc.value.status_code == 401
