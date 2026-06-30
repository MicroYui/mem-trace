//! Scale-only profiler aggregation for MemTrace (ROADMAP §6 / architecture §3.2).
//!
//! Reads profiler events as JSON Lines on stdin — one object per line with at
//! least `"phase"` (string) and `"latency_ms"` (number) — and prints a per-phase
//! aggregate (count, total ms, average ms). It is intentionally dependency-light
//! (no serde): a hand-rolled field reader keeps the binary small and fast. This
//! is **not** part of the default deployment; it exists for the scale scenario
//! where profiling analysis over very large traces becomes a bottleneck.
//!
//! The Python runtime remains the source of truth for profiler records; this
//! tool only summarizes an exported stream and never writes back.

use std::collections::BTreeMap;
use std::io::{self, BufRead};

#[derive(Default, Clone)]
struct PhaseStats {
    count: u64,
    total_ms: f64,
}

/// Extract the string value of `"<key>":"<value>"` from a JSON line, if present.
fn extract_string(line: &str, key: &str) -> Option<String> {
    let needle = format!("\"{}\":\"", key);
    let start = line.find(&needle)? + needle.len();
    let rest = &line[start..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

/// Extract the numeric value of `"<key>":<number>` from a JSON line, if present.
fn extract_number(line: &str, key: &str) -> Option<f64> {
    let needle = format!("\"{}\":", key);
    let start = line.find(&needle)? + needle.len();
    let rest = &line[start..];
    let end = rest
        .find(|c: char| !(c.is_ascii_digit() || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E'))
        .unwrap_or(rest.len());
    rest[..end].parse::<f64>().ok()
}

fn aggregate<R: BufRead>(reader: R) -> BTreeMap<String, PhaseStats> {
    let mut stats: BTreeMap<String, PhaseStats> = BTreeMap::new();
    for line in reader.lines().flatten() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let phase = match extract_string(line, "phase") {
            Some(p) => p,
            None => continue,
        };
        let latency = extract_number(line, "latency_ms").unwrap_or(0.0);
        let entry = stats.entry(phase).or_default();
        entry.count += 1;
        entry.total_ms += latency;
    }
    stats
}

fn main() {
    let stdin = io::stdin();
    let stats = aggregate(stdin.lock());
    println!("phase\tcount\ttotal_ms\tavg_ms");
    for (phase, s) in &stats {
        let avg = if s.count > 0 { s.total_ms / s.count as f64 } else { 0.0 };
        println!("{}\t{}\t{:.3}\t{:.3}", phase, s.count, s.total_ms, avg);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aggregates_phases() {
        let input = "{\"phase\":\"retrieval\",\"latency_ms\":10}\n\
                     {\"phase\":\"retrieval\",\"latency_ms\":20}\n\
                     {\"phase\":\"gate\",\"latency_ms\":5}\n";
        let stats = aggregate(input.as_bytes());
        assert_eq!(stats["retrieval"].count, 2);
        assert_eq!(stats["retrieval"].total_ms, 30.0);
        assert_eq!(stats["gate"].count, 1);
    }

    #[test]
    fn extracts_fields() {
        let line = "{\"phase\":\"context_packing\",\"latency_ms\":1.5}";
        assert_eq!(extract_string(line, "phase").as_deref(), Some("context_packing"));
        assert_eq!(extract_number(line, "latency_ms"), Some(1.5));
    }
}
