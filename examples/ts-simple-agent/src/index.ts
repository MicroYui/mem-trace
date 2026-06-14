import { MemTraceClient } from "@memtrace/sdk";

async function main(): Promise<void> {
  const baseUrl = process.env.MEMTRACE_BASE_URL ?? "http://127.0.0.1:8000";
  const options: ConstructorParameters<typeof MemTraceClient>[0] = { baseUrl };
  if (process.env.MEMTRACE_API_KEY !== undefined) {
    options.apiKey = process.env.MEMTRACE_API_KEY;
  }

  const client = new MemTraceClient(options);
  const run = await client.startRun({
    workspace_id: process.env.MEMTRACE_WORKSPACE_ID ?? "default",
    session_id: "ts-simple-agent",
    task: "Demonstrate TypeScript SDK usage",
  });
  const step = await client.startStep({ run_id: run.run_id, intent: "record preference" });
  const write = await client.writeEvent({
    run_id: run.run_id,
    step_id: step.step_id,
    role: "user",
    event_type: "message",
    content: "This project should use Bun for TypeScript tooling.",
    event_source: "ts-sdk-example",
  });
  const context = await client.retrieveContext({
    run_id: run.run_id,
    step_id: step.step_id,
    query: "Which TypeScript package manager should this project use?",
  });

  console.log(JSON.stringify({
    run_id: run.run_id,
    step_id: step.step_id,
    event_id: write.event.event_id,
    access_id: context.access_id,
    context_block_count: context.context_blocks.length,
  }, null, 2));
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
