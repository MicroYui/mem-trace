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
