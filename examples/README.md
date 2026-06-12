# MemTrace SDK examples

These examples are deterministic and use the public `memtrace_sdk` surface. They
are intended as copy-pasteable integration sketches for agent loops outside the
bundled MemTrace demo.

## Custom loop: `examples/simple_agent`

Runs a tiny hand-written agent loop through `MemTrace.in_memory(...)` and
recreates the Bun-vs-Node failed-branch isolation scenario:

```bash
uv run --package memtrace-sdk python examples/simple_agent/main.py
```

Expected output includes:

```text
baseline_1 action: npm test (contamination=1)
variant_2 action: bun test (contamination=0)
contamination eliminated: true
```

The local `decide_action(...)` helper intentionally ignores
`avoided_attempts` / `source="negative_evidence"` blocks when choosing the next
command. This demonstrates that safe failure lessons can be shown as negative
evidence without causing the agent to retry the failed `npm test` path.

## LangGraph adapter: `examples/langgraph_adapter`

Runs one LangGraph node wrapped by `MemTraceLangGraphAdapter` hooks:

```bash
uv run --package memtrace-sdk --extra langgraph python examples/langgraph_adapter/main.py
```

If LangGraph is not installed, the example exits successfully with an actionable
skip message:

```text
LangGraph is not installed; skipping this example. Install it with: pip install memtrace-sdk[langgraph]
```

When LangGraph is available, the node lifecycle is traced with
`event_source="langgraph_adapter"` and the step finishes as `completed`.
