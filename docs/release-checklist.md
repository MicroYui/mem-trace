# MemTrace Release Checklist

This checklist is for maintainers preparing a source, GitHub tag, PyPI, or npm release. It is intentionally manual: R1 prepares release metadata and verification commands, but it does **not** publish packages automatically.

## 1. Scope and publish decision

Before tagging or publishing, decide which release type this is:

- **Source-only / GitHub tag release:** publish the repository state and generated release notes, but do not upload packages.
- **PyPI release:** publish `memtrace` and/or `memtrace-sdk` only after the Python build checks below pass.
- **npm release:** publish `@memtrace/sdk` and/or `@memtrace/mcp-server` only after an explicit maintainer decision to remove `private: true` and after adding a separate package-publication plan.
- **Dry run:** run all checks and builds without creating a tag or uploading artifacts.

R1 keeps both JavaScript packages private by default. Do not change `packages/ts-sdk/package.json` or `packages/mcp-server/package.json` from `private: true`, and do not add `dist/`, bundler, declaration emit, or automatic publish workflows unless that is explicitly approved as a separate task.

## 2. Required local verification

Run these from the repository root:

```bash
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
uv run --extra dev pytest -q
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test
bash scripts/check-release-hygiene.sh
uv run python -m app.benchmark.runner --output-dir reports
bash scripts/reproduce.sh
```

Expected high-level results:

- Python compileall exits 0.
- Full pytest exits 0.
- TypeScript typecheck exits 0.
- Bun tests exit 0.
- Release hygiene prints `release hygiene checks passed`.
- Benchmark and reproduce keep the current global deterministic acceptance at `13/13` unless the benchmark suite intentionally changes in the same release.

## 3. Package metadata and dry-run checks

Python package build checks:

```bash
uv build --out-dir /tmp/memtrace-build-root --package memtrace
uv build --out-dir /tmp/memtrace-build-sdk --package memtrace-sdk
```

JavaScript package-shape checks:

```bash
npm exec --yes --package bun -- bun test packages/ts-sdk/test/package-shape.test.ts packages/mcp-server/test/package-shape.test.ts
```

Review the package metadata before publishing:

- Root `pyproject.toml` describes the current MemTrace runtime, not only the original P0 demo.
- `packages/python-sdk/pyproject.toml` uses build-safe metadata and preserves the `memtrace` console script.
- `packages/ts-sdk/package.json` and `packages/mcp-server/package.json` include explicit `exports` and `files` and remain `private: true` unless npm publishing is approved.
- No package points at generated reports, local service state, or test-only artifacts as public package contents.

## 4. Artifact and secret hygiene

Run the tracked-file and public-doc guard before tagging:

```bash
bash scripts/check-release-hygiene.sh
```

Do not commit:

- `node_modules/`
- `*.tsbuildinfo`
- npm/pnpm/yarn lockfiles
- package tarballs such as `*.tgz`
- generated `reports/` outputs
- local database/service data
- tracked `.env` files
- real API keys, bearer tokens, `sk-` tokens, passwords, raw destructive production commands, or unredacted `raw_payload_ref` values in public docs/examples

Synthetic redaction fixtures belong in tests or internal design documents, not in public onboarding docs.

## 5. Tagging and release notes

For a source or package release:

1. Confirm `git status --short` contains only intentional tracked changes.
2. Confirm the release commit includes the updated roadmap and `.ai` project memory.
3. Draft release notes from the public-facing changes: README, user docs, package metadata, CI, release hygiene, and deterministic reproducibility status.
4. Create the tag only after required verification passes.

## 6. Rollback notes

- If a GitHub tag is wrong and has not been published broadly, delete the local tag with `git tag -d <tag>` and the remote tag with `git push origin :refs/tags/<tag>`.
- If package metadata or build checks fail before publication, fix metadata, rerun the dry-run/build checks, and create a new release candidate commit.
- If a package is already published, prefer publishing a corrected patch version rather than rewriting public release history.
- If CI fails after tagging, do not publish package artifacts until CI is green or the failure is explicitly classified as unrelated infrastructure noise.
