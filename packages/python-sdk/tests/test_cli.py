from __future__ import annotations

import asyncio
import json

import httpx

from app.api.deps import get_runtime
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository
from memtrace_sdk import MemTrace
from memtrace_sdk import cli
from memtrace_sdk.types import (
    EventRole,
    EventType,
    FinishStepRequest,
    RetrievalRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)


def _override_runtime(runtime: MemoryRuntime) -> None:
    app.dependency_overrides[get_runtime] = lambda: runtime


async def _asgi_client_for(runtime: MemoryRuntime) -> tuple[MemTrace, httpx.AsyncClient]:
    _override_runtime(runtime)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return MemTrace.http("http://test", client=http_client), http_client


async def _seed_retrievable_context(runtime: MemoryRuntime) -> tuple[str, str]:
    client, http_client = await _asgi_client_for(runtime)
    try:
        run = await client.start_run(StartRunRequest(session_id="cli-s1", task="remember runtime"))
        step = await client.start_step(StartStepRequest(run_id=run.run_id, intent="record constraint"))
        await client.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content="这个项目使用 Bun",
            )
        )
        await client.finish_step(
            FinishStepRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                status=StepStatus.completed,
            )
        )
        recovery = await client.start_step(
            StartStepRequest(run_id=run.run_id, intent="recover test command")
        )
        # Prove the seeded runtime can retrieve before the CLI reads through the same HTTP surface.
        context = await client.retrieve_context(
            RetrievalRequest(run_id=run.run_id, step_id=recovery.step_id, query="Bun runtime")
        )
        assert context.context_blocks
        return run.run_id, recovery.step_id
    finally:
        await http_client.aclose()
        app.dependency_overrides.clear()


def test_cli_demo_in_process(capsys) -> None:
    exit_code = cli.main(["demo", "--in-process"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "baseline_1 action: npm test" in output
    assert "variant_2 action: bun test" in output
    assert "contamination eliminated: true" in output.lower()


def test_cli_demo_http_runs_against_persistent_server(monkeypatch, capsys) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_cli")
    clients: list[httpx.AsyncClient] = []

    def http_factory(base_url: str, *, api_key: str | None = None) -> MemTrace:
        assert base_url == "http://test"
        assert api_key is None
        _override_runtime(runtime)
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        clients.append(http_client)
        return MemTrace.http("http://test", client=http_client)

    monkeypatch.setattr(cli, "_http_client", http_factory, raising=False)

    try:
        exit_code = cli.main(["--http", "http://test", "demo"])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert "baseline_1 action: npm test" in output
        assert "variant_2 action: bun test" in output
        assert "contamination eliminated: true" in output.lower()
    finally:
        for client in clients:
            asyncio.run(client.aclose())
        app.dependency_overrides.clear()


def test_cli_operational_command_requires_http(capsys) -> None:
    exit_code = cli.main(["start-run", "--session-id", "cli-s1", "--task", "remember runtime"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "requires --http" in captured.err
    assert "persistent MemTrace server" in captured.err


def test_cli_retrieve_outputs_json_over_http(monkeypatch, capsys) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_cli")
    run_id, step_id = asyncio.run(_seed_retrievable_context(runtime))
    clients: list[httpx.AsyncClient] = []

    def http_factory(base_url: str, *, api_key: str | None = None) -> MemTrace:
        assert base_url == "http://test"
        assert api_key is None
        _override_runtime(runtime)
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        clients.append(http_client)
        return MemTrace.http("http://test", client=http_client)

    monkeypatch.setattr(cli, "_http_client", http_factory, raising=False)

    try:
        exit_code = cli.main(
            [
                "--http",
                "http://test",
                "--json",
                "retrieve",
                "--run-id",
                run_id,
                "--step-id",
                step_id,
                "--query",
                "Bun runtime",
            ]
        )
        output = capsys.readouterr().out
        payload = json.loads(output)

        assert exit_code == 0
        assert payload["query"] == "Bun runtime"
        assert payload["context_blocks"]
        assert any(block["type"] == "project_memory" for block in payload["context_blocks"])
    finally:
        for client in clients:
            asyncio.run(client.aclose())
        app.dependency_overrides.clear()


def test_cli_write_event_stamps_cli_event_source(monkeypatch, capsys) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_cli")
    run_id, step_id = asyncio.run(_seed_retrievable_context(runtime))
    clients: list[httpx.AsyncClient] = []

    def http_factory(base_url: str, *, api_key: str | None = None) -> MemTrace:
        assert base_url == "http://test"
        assert api_key is None
        _override_runtime(runtime)
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        clients.append(http_client)
        return MemTrace.http("http://test", client=http_client)

    monkeypatch.setattr(cli, "_http_client", http_factory, raising=False)

    try:
        exit_code = cli.main(
            [
                "--http",
                "http://test",
                "--json",
                "write-event",
                "--run-id",
                run_id,
                "--step-id",
                step_id,
                "--role",
                "assistant",
                "--content",
                "Use bun test.",
            ]
        )
        output = capsys.readouterr().out
        payload = json.loads(output)

        assert exit_code == 0
        assert payload["event"]["event_source"] == "cli"
        assert payload["event"]["content"] == "Use bun test."
    finally:
        for client in clients:
            asyncio.run(client.aclose())
        app.dependency_overrides.clear()


def test_cli_http_404_nonzero_exit(monkeypatch, capsys) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_cli")
    clients: list[httpx.AsyncClient] = []

    def http_factory(base_url: str, *, api_key: str | None = None) -> MemTrace:
        assert base_url == "http://test"
        assert api_key is None
        _override_runtime(runtime)
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        clients.append(http_client)
        return MemTrace.http("http://test", client=http_client)

    monkeypatch.setattr(cli, "_http_client", http_factory, raising=False)

    try:
        exit_code = cli.main(
            [
                "--http",
                "http://test",
                "inspect-access",
                "--access-id",
                "acc_missing",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "not found" in captured.err.lower()
        assert "access not found" in captured.err.lower()
    finally:
        for client in clients:
            asyncio.run(client.aclose())
        app.dependency_overrides.clear()
