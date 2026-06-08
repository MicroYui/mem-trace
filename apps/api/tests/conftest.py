"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def runtime(repo: InMemoryRepository) -> MemoryRuntime:
    return MemoryRuntime(repo, default_workspace_id="ws_test")
