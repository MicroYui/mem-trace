# rust-profile-analyzer (scale-only)

A dependency-light profiler-aggregation tool for MemTrace — **not part of the
default deployment**. Trigger condition (ROADMAP §6 / architecture §3.2):
profiling analysis over very large exported traces becomes a bottleneck.

## What it does

Reads profiler events as JSON Lines on stdin (one object per line with `"phase"`
and `"latency_ms"`) and prints a per-phase aggregate: count, total ms, average
ms. The Python runtime owns the authoritative profiler records; this tool only
summarizes an exported stream and never writes back.

```bash
cd components/rust-profile-analyzer
cargo build --release
cargo test
# Example:
echo '{"phase":"retrieval","latency_ms":12}' | ./target/release/rust-profile-analyzer
```

Requires the Rust toolchain (not bundled; default CI does not build this
component).

## Boundary

Read-only summarization over `/v1`-exported profiler data; no duplication of
Python runtime semantics.
