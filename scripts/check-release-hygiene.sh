#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

failures=0

report_failure() {
  local message="$1"
  printf 'error: %s\n' "$message" >&2
  failures=1
}

tracked_matches() {
  local pattern="$1"
  git ls-files | grep -E "$pattern" || true
}

forbidden_artifacts='(^|/)node_modules/|(^|/)dist/|(^|/)build/|\.tsbuildinfo$|(^|/)package-lock\.json$|(^|/)pnpm-lock\.yaml$|(^|/)yarn\.lock$|\.tgz$|^reports/|(^|/)docker-data/|(^|/)postgres-data/|(^|/)redis-data/|(^|/)\.env($|\.)'
artifact_matches="$(tracked_matches "$forbidden_artifacts")"
if [[ -n "$artifact_matches" ]]; then
  report_failure "forbidden generated/local-service artifacts are tracked:"
  printf '%s\n' "$artifact_matches" >&2
fi

scan_paths=(README.md docs examples)
existing_scan_paths=()
for path in "${scan_paths[@]}"; do
  if [[ -e "$path" ]]; then
    existing_scan_paths+=("$path")
  fi
done

secret_pattern="(sk-[A-Za-z0-9_-]{12,}|Bearer[[:space:]]+[A-Za-z0-9._~+/-]{12,}|api[_-]?key[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9._~+/-]{12,}|password[[:space:]]*[:=][[:space:]]*['\"]?[^[:space:]'\"]{6,})"
secret_matches="$(
  git grep -n -I -E -i "$secret_pattern" -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' \
    | grep -Ev 'process\.env|your-|example-|placeholder|\$\{[A-Z0-9_]+\}' \
    || true
)"
if [[ -n "$secret_matches" ]]; then
  report_failure "possible real secret markers found in public docs/examples:"
  printf '%s\n' "$secret_matches" >&2
fi

raw_payload_pattern="raw_payload_ref[[:space:]]*[:=][[:space:]]*(['\"][^'\"]+['\"]|[^[:space:]#]+)"
raw_payload_matches="$(git grep -n -I -E "$raw_payload_pattern" -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' || true)"
if [[ -n "$raw_payload_matches" ]]; then
  report_failure "unredacted raw_payload_ref values found:"
  printf '%s\n' "$raw_payload_matches" >&2
fi

destructive_matches="$(git grep -n -I -E 'rm[[:space:]]+-rf[[:space:]]+/(prod|production|var|etc|usr|home|root)(/|[[:space:]]|$)' -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' || true)"
if [[ -n "$destructive_matches" ]]; then
  report_failure "raw destructive production command examples found:"
  printf '%s\n' "$destructive_matches" >&2
fi

if [[ "$failures" -ne 0 ]]; then
  exit 1
fi

echo "release hygiene checks passed"
