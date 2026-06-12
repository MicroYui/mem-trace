from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from memtrace_sdk.client import MemTrace
from memtrace_sdk.errors import BadRequestError, MemTraceError, NotFoundError
from memtrace_sdk.types import (
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryContext,
    ObservabilityReportRequest,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)


OPERATIONAL_COMMANDS = {
    "start-run",
    "start-step",
    "write-event",
    "retrieve",
    "timeline",
    "state-tree",
    "inspect-access",
    "report",
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("memtrace: interrupted", file=sys.stderr)
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memtrace",
        description="Trace, retrieve, inspect, and report through a MemTrace runtime.",
    )
    parser.add_argument("--http", help="Base URL of a persistent MemTrace HTTP server")
    parser.add_argument("--workspace-id", help="Workspace id for commands that accept one")
    parser.add_argument("--api-key", help="Bearer token sent to the HTTP server")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    subcommands = parser.add_subparsers(dest="command")

    demo = subcommands.add_parser("demo", help="Run a deterministic one-shot SDK demo")
    demo.add_argument("--in-process", action="store_true", help="Run demo against an in-memory runtime")

    start_run = subcommands.add_parser("start-run", help="Start a run on a persistent server")
    start_run.add_argument("--session-id", required=True)
    start_run.add_argument("--task")

    start_step = subcommands.add_parser("start-step", help="Start a step")
    start_step.add_argument("--run-id", required=True)
    start_step.add_argument("--intent")
    start_step.add_argument("--parent-step-id")
    start_step.add_argument("--recovery-from-step-id")
    start_step.add_argument("--goal")

    write_event = subcommands.add_parser("write-event", help="Write an event with event_source=cli")
    write_event.add_argument("--run-id", required=True)
    write_event.add_argument("--step-id", required=True)
    write_event.add_argument("--role", choices=[role.value for role in EventRole], default=EventRole.user.value)
    write_event.add_argument(
        "--event-type",
        choices=[event_type.value for event_type in EventType],
        default=EventType.message.value,
    )
    write_event.add_argument("--content")
    write_event.add_argument("--tool-name")
    write_event.add_argument("--status")

    retrieve = subcommands.add_parser("retrieve", help="Retrieve packed context")
    retrieve.add_argument("--run-id", required=True)
    retrieve.add_argument("--step-id")
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--task-intent")
    retrieve.add_argument(
        "--strategy",
        choices=[strategy.value for strategy in RetrievalStrategy],
        default=RetrievalStrategy.variant_2.value,
    )
    retrieve.add_argument("--top-k", type=int, default=10)
    retrieve.add_argument("--token-budget", type=int)

    timeline = subcommands.add_parser("timeline", help="List events in a run")
    timeline.add_argument("--run-id", required=True)

    state_tree = subcommands.add_parser("state-tree", help="List state nodes in a run")
    state_tree.add_argument("--run-id", required=True)

    inspect_access = subcommands.add_parser("inspect-access", help="Inspect a retrieval access")
    inspect_access.add_argument("--access-id", required=True)

    report = subcommands.add_parser("report", help="Write observability JSON/Markdown/HTML reports")
    report.add_argument("--run-id")
    report.add_argument("--output-dir", default="reports")
    report.add_argument("--no-replay", action="store_true")

    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command in OPERATIONAL_COMMANDS and not args.http:
        print(
            f"memtrace: '{args.command}' requires --http so it can talk to a persistent "
            "MemTrace server; in-process mode would lose state between CLI invocations.",
            file=sys.stderr,
        )
        return 2

    client: MemTrace | None = None
    try:
        if args.command == "demo":
            if args.in_process and args.http:
                print("memtrace: demo accepts either --in-process or --http, not both", file=sys.stderr)
                return 2
            if not args.in_process and not args.http:
                print("memtrace: demo requires --in-process or --http", file=sys.stderr)
                return 2
            client = (
                MemTrace.in_memory(default_workspace_id=args.workspace_id or "ws_cli_demo")
                if args.in_process
                else _http_client(args.http, api_key=args.api_key)
            )
            result = await _run_demo(client, workspace_id=args.workspace_id or "ws_cli_demo")
            _print(result, json_output=args.json)
            return 0

        client = _http_client(args.http, api_key=args.api_key)
        result = await _run_operational_command(client, args)
        _print(result, json_output=args.json)
        return 0
    except NotFoundError as exc:
        print(f"memtrace: not found: {exc}", file=sys.stderr)
        return 1
    except BadRequestError as exc:
        print(f"memtrace: bad request: {exc}", file=sys.stderr)
        return 2
    except MemTraceError as exc:
        print(f"memtrace: error: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            await client.aclose()


def _http_client(base_url: str, *, api_key: str | None = None) -> MemTrace:
    return MemTrace.http(base_url, api_key=api_key)


async def _run_operational_command(client: MemTrace, args: argparse.Namespace) -> Any:
    if args.command == "start-run":
        return await client.start_run(
            StartRunRequest(session_id=args.session_id, task=args.task, workspace_id=args.workspace_id)
        )
    if args.command == "start-step":
        return await client.start_step(
            StartStepRequest(
                run_id=args.run_id,
                intent=args.intent,
                parent_step_id=args.parent_step_id,
                recovery_from_step_id=args.recovery_from_step_id,
                goal=args.goal,
            )
        )
    if args.command == "write-event":
        return await client.write_event(
            WriteEventRequest(
                run_id=args.run_id,
                step_id=args.step_id,
                role=EventRole(args.role),
                event_type=EventType(args.event_type),
                content=args.content,
                tool_name=args.tool_name,
                status=args.status,
                event_source="cli",
            )
        )
    if args.command == "retrieve":
        return await client.retrieve_context(
            RetrievalRequest(
                run_id=args.run_id,
                step_id=args.step_id,
                query=args.query,
                task_intent=args.task_intent,
                workspace_id=args.workspace_id,
                strategy=RetrievalStrategy(args.strategy),
                token_budget=args.token_budget,
                top_k=args.top_k,
            )
        )
    if args.command == "timeline":
        return await client.get_timeline(args.run_id)
    if args.command == "state-tree":
        return await client.get_state_tree(args.run_id)
    if args.command == "inspect-access":
        return await client.inspect_access(args.access_id)
    if args.command == "report":
        return await client.write_observability_report(
            ObservabilityReportRequest(
                workspace_id=args.workspace_id,
                run_id=args.run_id,
                output_dir=args.output_dir,
                include_replay=not args.no_replay,
            )
        )
    raise MemTraceError(f"unsupported command: {args.command}")


async def _run_demo(client: MemTrace, *, workspace_id: str) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    for strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.variant_2):
        run, recovery = await _seed_demo_run(
            client,
            session_id=f"cli-demo-{strategy.value}",
            workspace_id=workspace_id,
        )
        context = await client.retrieve_context(
            RetrievalRequest(
                run_id=run.run_id,
                step_id=recovery.step_id,
                query="How do I run the test suite? I tried npm test.",
                strategy=strategy,
                workspace_id=workspace_id,
            )
        )
        results[strategy.value] = {
            "action": _decide_action(context),
            "failed_branch_contamination": int(_contaminated(context)),
            "context_blocks": [block.model_dump(mode="json") for block in context.context_blocks],
            "warnings": context.warnings,
        }

    summary = {
        "baseline_action": results[RetrievalStrategy.baseline_1.value]["action"],
        "variant_2_action": results[RetrievalStrategy.variant_2.value]["action"],
        "baseline_contamination": results[RetrievalStrategy.baseline_1.value]["failed_branch_contamination"],
        "variant_2_contamination": results[RetrievalStrategy.variant_2.value]["failed_branch_contamination"],
        "contamination_eliminated": (
            results[RetrievalStrategy.baseline_1.value]["failed_branch_contamination"] == 1
            and results[RetrievalStrategy.variant_2.value]["failed_branch_contamination"] == 0
        ),
        "strategies": results,
    }
    return summary


async def _seed_demo_run(client: MemTrace, *, session_id: str, workspace_id: str):
    run = await client.start_run(
        StartRunRequest(
            session_id=session_id,
            task="Fix failing tests from the CLI",
            workspace_id=workspace_id,
        )
    )

    planning = await client.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=planning.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun，不用 Node.js",
            event_source="cli",
        )
    )
    await client.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=planning.step_id, status=StepStatus.completed)
    )

    failed = await client.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_call,
            tool_name="bash",
            content="npm test",
            event_source="cli",
        )
    )
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            tool_name="bash",
            status="failed",
            content="Tried running tests with npm test, but it failed because npm was unavailable.",
            event_source="cli",
        )
    )
    await client.finish_step(
        FinishStepRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            status=StepStatus.failed,
            error_message="npm unavailable",
        )
    )
    await client.rollback_branch(
        RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm unavailable")
    )

    recovery = await client.start_step(
        StartStepRequest(
            run_id=run.run_id,
            intent="debugging",
            recovery_from_step_id=failed.step_id,
            goal="Recovery: choose correct test runner",
        )
    )
    return run, recovery


def _decide_action(context: MemoryContext) -> str:
    if _contaminated(context):
        return "npm test"
    positive_text = " ".join(block.content.lower() for block in _positive_blocks(context))
    if "bun" in positive_text:
        return "bun test"
    return "unknown"


def _contaminated(context: MemoryContext) -> bool:
    return any("npm" in block.content.lower() and "failed" in block.content.lower() for block in _positive_blocks(context))


def _positive_blocks(context: MemoryContext):
    return [
        block
        for block in context.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]


def _print(result: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(_to_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))
        return

    if isinstance(result, dict) and "contamination_eliminated" in result:
        print(
            "baseline_1 action: "
            f"{result['baseline_action']} "
            f"(contamination={result['baseline_contamination']})"
        )
        print(
            "variant_2 action: "
            f"{result['variant_2_action']} "
            f"(contamination={result['variant_2_contamination']})"
        )
        print(f"contamination eliminated: {str(result['contamination_eliminated']).lower()}")
        return

    print(json.dumps(_to_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
