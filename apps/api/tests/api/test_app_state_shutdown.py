"""AppState shutdown must close the provider registry (network client cleanup)."""
from __future__ import annotations

import pytest

from app.api.deps import AppState


class _FakeRegistry:
    def __init__(self, *, raises: bool = False) -> None:
        self.aclose_calls = 0
        self._raises = raises

    async def aclose(self) -> None:
        self.aclose_calls += 1
        if self._raises:
            raise RuntimeError("provider close failed")


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


async def test_app_state_shutdown_closes_provider_registry():
    state = AppState()
    registry = _FakeRegistry()
    state.provider_registry = registry  # type: ignore[assignment]
    state.engine = None

    await state.shutdown()

    assert registry.aclose_calls == 1


async def test_app_state_shutdown_without_registry_is_safe():
    state = AppState()
    state.provider_registry = None
    state.engine = None

    await state.shutdown()  # must not raise when nothing was started


async def test_app_state_shutdown_disposes_engine_even_if_registry_aclose_raises():
    state = AppState()
    state.provider_registry = _FakeRegistry(raises=True)  # type: ignore[assignment]
    engine = _FakeEngine()
    state.engine = engine  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="provider close failed"):
        await state.shutdown()

    assert engine.dispose_calls == 1  # engine disposed despite provider close failure
