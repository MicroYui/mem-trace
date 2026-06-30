# MemTrace 后续工作路线图 (ROADMAP)

> 本文件是「未来要做的事情」的权威清单。新会话启动后，连同 `.ai/PROJECT_STATE.md` 一起阅读即可知道当前进度与后续待办。
>
> - **进度基线**：P0 + P1 完成；**P2 完成 (6/6)**，含真实 OpenAI 兼容 LLM extraction provider（已对火山方舟 deepseek 实测）+ 真实 LLM 验证 bench（`app/benchmark/llm_bench.py`）。
> - **来源**：`docs/design/architecture.md`（完整架构，自带 Phase 标注）、`docs/design/draft.md`（原始愿景，范围远大于 MVP）、`.ai/MVP_SCOPE.md`（Out of Scope）、`.ai/OPEN_QUESTIONS.md`、`.ai/DECISIONS.md`、`.ai/PROJECT_STATE.md`。
> - **维护约定**：完成一项后在此勾掉并同步更新 `.ai/PROJECT_STATE.md` 与 `.ai/IMPLEMENTATION_PLAN.md`。区分两类来源——「愿景级」(draft) vs 「已决策推迟」(ADR/MVP_SCOPE)。

---

## 0. 即时待决策 (OPEN QUESTIONS) — 已全部拍板 (2026-06-10)

来自 `.ai/OPEN_QUESTIONS.md` §Remaining，**已按推荐方案决策完毕**（见 `.ai/DECISIONS.md` ADR-015/016/017）。此处记录结论，落地实现各归对应章节：

- [x] **真实 embedding 模型替换**：**决策 = 保留确定性 hashed default 作为 benchmark 基线，真实 embedding 作为可选 config-gated `EmbeddingProvider`**（ADR-015）。实现落到 §10 Provider Registry。出处：OPEN_Q #1 / PROJECT_STATE 风险#1 / ADR-014。
- [x] **Auth model**：**决策 = 托管 demo 前先做轻量 Hosted-Demo Safety Mode（API-key stub + workspace-scoped demo token + 不持久化原文 secret + demo reset + rate limit + 只读公开报告）；完整多租户治理仍在计划内但后置到 Phase 4**（ADR-016）。完整治理落到 §3.4。出处：OPEN_Q #3 / MVP_SCOPE Out-of-Scope #5。
- [x] **Raw secret payload**：**决策 = 默认不存原文；若做 `raw_payload_ref` 必须加密且默认关闭，归入 Phase 4 §3.4 的 redaction 状态机**（ADR-017）。出处：OPEN_Q #4 / architecture §6.2。

---

## 1. 技术债 / 已知风险

来自 `.ai/PROJECT_STATE.md` Open Risks 与 `.ai/PITFALLS.md`：

- [ ] **进程内 candidate buffer 不跨 worker 共享**：当前单进程，多 worker 部署会失效。architecture 明确把 Redis-backed buffer 推迟到 post-P2。出处：PROJECT_STATE / ADR 注。
- [ ] **生命周期过滤是单点**：superseded/archived 过滤只在 retrieval candidate 阶段（`_RETRIEVABLE_STATUSES`）。**任何新检索路径必须重新应用此过滤**，否则会泄漏退役记忆。出处：PITFALLS。
- [ ] **LLM key 不稳定性**：模型对同一概念可能分配不同 key，破坏 key-based 冲突解析。已用受控 key 词表系统提示缓解，但仍是真实 LLM 路径脆弱点。**根治方向见 §11 Controlled Memory Key Ontology（schema registry，比「语义去重」更早更实用）**。出处：PROJECT_STATE / llm_extractor `_SYSTEM_PROMPT`。
- [ ] **PG15 数据卷与 pg16 镜像不兼容**：切换需 `docker-compose down -v`（破坏性）。运维注意。
- [ ] **profiler 亚毫秒阶段读为 0ms**：四舍五入所致，属预期非 bug（真实负载下非 0）。
- [x] **检索超预算是丢弃式截断、无压缩补偿**：C1 已完成默认开启的 packer 超预算补偿：普通块被丢弃时会生成 `compacted_constraints` + `compaction_notice`，并保留结构化 key=value 事实；C2 已完成 durable `ContextCompactionLog`、observability summary 指标、replay payload 与 `compaction_drift`。出处：`packer.py:pack_context` / §9 Context Compaction。

### 1.1 全量代码审查发现（2026-06-13）

一次覆盖 runtime / retrieval / memory / observability / storage / SDK 六大模块的逐行审查。下列**已修复**项已在本轮安全/一致性提交内含测试与回归；§13 historical slice verification 为 `uv run --extra dev pytest -q` -> **397 passed, 1 skipped**，当时 benchmark/reproducibility 为 `acceptance.passed=true (12/12 checks true)`；I7/R1 后当前全局 benchmark/reproducibility acceptance 为 **13/13**：

- [x] **secrets 脱敏覆盖面过窄**：新增 JWT / PEM 私钥块 / Slack `xox*` / Google `AIza*` / 自然语「password is X」模式。因为整个抽取分支由 `contains_secret` 把关，漏检即等于密钥落库且进入可检索记忆。出处：`memory/secrets.py`。
- [x] **writer 否定短语产生矛盾记忆**：`"should not use X"` / `"不想用 X"` 会同时命中 positive 与 negative 规则，产出自相矛盾的 `project.runtime=X` + `project.runtime.excluded=X`。已加后置去矛盾过滤（被排除的 runtime 不得作为正向约束）。出处：`memory/writer.py`。
- [x] **resolver 单值 key 集合落后于 LLM 受控 key 契约**：`_SINGLE_VALUED_KEYS` 仅含 `project.runtime`，而 LLM 系统提示已约定 language/database/test_framework/formatting/package_manager 等单值概念。已扩展该集合，使后到的冲突值即使没有 `supersede=true` 也能被正确 supersede。出处：`memory/resolver.py`。
- [x] **observability 报告 degrade 计入「已接受」**：`reports.py:_accepted_memories` 把 `degrade` 当成 accepted，与 `metrics.py`/`replay.py` 的权威 `{accept,warn}` 定义冲突，导致 per-access 行指标与 summary 聚合自相矛盾。已对齐为 `{accept,warn}`。出处：`observability/reports.py`。

下列为**审查确认项的当前状态**：H1-H18 范围内的问题已在 §13 关闭；仍未勾选的条目是需要更大设计决策、属于非 §13 主线、或可 opportunistic cleanup 的后续待办。

- [x] **[High] 正向打包路径无脱敏纵深防御**：H1 已完成 packer 级纵深脱敏：正向 context 的 active state/path、prelude、project constraints、memory-derived blocks、compacted retained facts 在入 prompt 前统一走 `redact()`；H2 复审又把 `secret` / `contains_secret` / destructive / tool-sensitive 提升为 `baseline_1` / `long_context` 也不可绕过的 gate safety floor。出处：`retrieval/packer.py` / `retrieval/gate.py` / `tests/retrieval/test_retrieval_flow.py` / `tests/retrieval/test_gate.py`。
- [x] **[High] `variant_1` 为「失败分支降权」过度关闭整条 hard/risk policy**：H2 已完成 gate 收敛：`variant_1` 仅放行 failed/rolled_back 分支用于降权对比，保留 hard/risk policy；quarantined、secret、destructive、tool-sensitive 增加非绕过安全底线，任何策略都不得进入正向 context。出处：`retrieval/gate.py` / `tests/retrieval/test_gate.py`。
- [x] **[High] in-process 与 HTTP 后端 isomorphism 仍有缺口**：H4 已完成；`StateTreeError` 映射为 HTTP 400 / SDK `BadRequestError`，`replay_access` / `replay_run` missing-run 检查下沉到 `MemoryRuntime` 并在 routes/SDK 后端统一翻译为 404 / `NotFoundError`，同时 `get_step` 走 runtime facade 而不是私有 repo 访问。出处：`packages/python-sdk/.../backends.py` / `api/routes.py` / `runtime/memory_runtime.py`。
- [x] **[High] 并发下 `next_sequence_no` 可能重复**：H5 已完成；runtime 热路径改用 `Repository.append_event(...)`，SQL 在同一事务里持有 `pg_advisory_xact_lock(hashtext('memtrace_event_seq'), hashtext(:run_id))`、计算 max+1 并插入，`IntegrityError` 有界重试；唯一约束名对齐初始迁移 `uq_event_run_seq`，`0006` 仅保留 hardening 边界不重复建约束。出处：`storage/sql_repository.py` / `storage/orm.py` / `migrations/versions/0006_security_consistency_hardening.py`。
- [x] **[High] 检索超时路径 split-brain**：H6 已完成；prelude / non-prelude timeout 都持久化同一 minimal access 形态，timeout 只包裹 `trace(...)` 构造，成功 trace 的日志持久化与 `access_count` mutation 在 timeout 窗口外执行，并覆盖 slow persistence 不被误判 timeout。出处：`retrieval/controller.py` / `tests/retrieval/test_retrieval_flow.py`。
- [x] **[Medium] token 估算复用剔停用词的 `tokenize`**：H11 已完成；prompt budget 改用独立 regex/CJK-aware estimator，截断路径会复核预算闭合，policy snapshot 记录 `TOKEN_ESTIMATOR_VERSION`。出处：`retrieval/packer.py` / `retrieval/policy.py` / `tests/retrieval/test_packer_negative.py`。
- [x] **[Medium] 服务端无鉴权但 SDK/CLI 发送 Bearer**：H3 已完成默认关闭轻量 token gate：`MEMTRACE_AUTH_ENABLED=false` 保持本地/benchmark 零鉴权；启用后 `/v1` 要求 Bearer 或 `X-API-Key` 匹配 `MEMTRACE_API_KEY`，缺失 401、错误 403，`/health` 仍开放。SDK/CLI token path 已有测试。出处：`api/deps.py` / `api/routes.py` / `tests/api/test_auth.py` / SDK tests。
- [x] **[Medium] benchmark 公平性恢复仅覆盖 `access_count`**：H14 已完成；benchmark 现在对受测 workspace 做 whole-memory snapshot/restore，并在策略执行后检查新增/缺失/迁移 memory，避免未来 reflection/scheduler 字段 mutation 污染后续策略。出处：`benchmark/runner.py` / `tests/benchmark/test_runner.py`。
- [x] **[Medium] LLM provider 每次调用新建 `AsyncClient`**：~~无连接复用，高频抽取下端口/性能压力~~。**已完成 (2026-06-30)**：`OpenAIEmbeddingProvider` / `LLMExtractionProvider` / `LLMSummarizerProvider` 改为惰性缓存自有 `httpx.AsyncClient`（`_client_for_request()`）并经 `aclose()` 关闭（仅关自建、不关注入的 client，由 `_owns_client` 区分）；`ProviderRegistry.aclose()` best-effort 关闭各 slot（尝试全部 provider，再抛首个错误），`AppState.shutdown()` 与 `WorkerRuntimeHandle.aclose()` 用 `try/finally` 在关 registry 后必定 `engine.dispose()`，`llm_bench.py` 用 try/finally aclose。确定性 provider 无 client、保持无网络。出处：`memory/llm_extractor.py` / `providers/embedding.py` / `memory/summarizer_provider.py` / `providers/registry.py` / `api/deps.py` / `async_tasks/runtime_factory.py`。
- [x] **[Medium] ORM 与迁移在 `context_compaction_logs` 索引上漂移**：H8 已完成；ORM 显式声明复合索引 `ix_context_compaction_logs_workspace_created(workspace_id, created_at)` 并移除 workspace 单列 index，`create_all` metadata 与 `0005_context_compaction` migration 对齐。出处：`storage/orm.py` / `migrations/versions/0005_context_compaction.py` / `tests/storage/test_migrations.py`。
- [x] **[Medium] gate log 排序非确定性**：H7 已完成；InMemory/SQL `list_gate_logs` 均按 `(created_at, gate_id)` 排序，hot-path 与 replay accepted context 重建使用 `(-final_score, memory_id)` tie-break，避免虚假 order-changed diff。出处：`runtime/repository.py` / `storage/sql_repository.py` / `observability/replay.py` / `retrieval/controller.py`。
- [x] **[Medium] summarizer LLM 路径 provenance 校验可能恒失败**：H12 已完成并复审加固；retained-fact allow-set 由结构化 `must_retain_facts` provenance 播种，同时 top-level source id 列表必须与请求精确一致，防止 provider 改写全局来源集合。出处：`memory/summarizer_provider.py` / `tests/memory/test_summarizer_provider.py`。
- [x] **[Medium] 多处状态机/隔离边界小缺陷**：H13 已完成；`state_tree.apply_finish` 映射 `StepStatus.rolled_back`，`finish_step` / `rollback_branch` 对缺失 state node 或 `state_node_id=None` 的腐坏 step 在任何状态写入/flush 副作用前抛 `StateTreeError`，避免 ghost node、step-only rollback 和 corrupt rollback 触发 buffered flush。出处：`runtime/state_tree.py` / `runtime/memory_runtime.py` / `tests/runtime/test_memory_runtime_trace.py` / `tests/runtime/test_candidate_buffer_flush.py`。
- [ ] **[Medium] 负向证据（avoided_attempts）非受保护块**：预算紧张时「请勿重复某危险操作」的安全提示可能被丢弃。建议将 `sanitized_risk_notice` 模式负向证据纳入受保护集合或提高保留优先级。出处：`retrieval/packer.py:145-146`。**Deferred by decision (2026-06-30)**：触及 context-packing 语义且需重跑 benchmark；其安全 metadata 已由 I7 retained 在 compaction log（replay/observability 可见），故作为单独可选增强后置，不在 2026-06-30 收尾切片内。
- [ ] **[Low] 其余（2026-06-30 closeout 复核）**：**已修复 / 已确认修复**——`tool_sensitive_present` 子串误判改为 token 边界匹配（`writer.py` `_TOOL_SENSITIVE_PATTERNS=[(?<![a-z])secrets?(?![a-z])]`，保留 `client_secret`/`api_secret`/`secret_key` 等复合凭据标识符并丢弃 `secretary` 类前缀误判；destructive/production 仍由既有 flag 覆盖）；`last_accessed_at` 已由 P4-B `bump_memory_access` 写入并被 `retention._recency` 消费（recency 不再是死字段）；报告路径 TOCTOU 已由 `reports._safe_output_dir` 逐段 symlink + resolved-root 校验覆盖；`stale_injected` 全程用 `datetime.now(timezone.utc)`，无 naive/aware 混比；summarizer episodic 内容基于已脱敏 event 构建并经上游 governance 脱敏。**仍待办（价值低）**——`access_count`/`raw_event_ids` 的 read-modify-write 竞态（SQL 服务端 `+1` 已原子，仅 in-memory dev/test repo 非原子；`raw_event_ids` 为反规范化缓存，真相源是 `agent_events` join）、CLI 与 evaluator 判定逻辑重复（SDK 不得 import `apps/api`，去重需跨刻意的包边界耦合）。详见审查记录。

> **修复优先级建议**：正向脱敏 + variant_1 gate（安全闭环）≈ isomorphism/StateTreeError ＞ sequence_no 并发 + 超时 split-brain（数据一致性）＞ token 预算精度 ＞ 鉴权 ＞ 其余。安全相关的两条（正向脱敏、variant_1）与一致性两条建议优先排期。

### 1.2 全栈核验 + 7 项审计修复（2026-06-30 session 2）

一次覆盖后端 / 前端 / SDK-集成 / 真实大模型路径的完整核验：后端全量 **775 passed, 2 skipped**、benchmark/reproduce **13/13**、前端 `typecheck` + 根 `bun test`(58) + `web:test`(27) + vite 生产构建全绿；真实大模型经本地 OpenAI 兼容反代 `http://localhost:4141`（chat-completions-only，`gpt-5-mini`）验证 LLM 抽取（`llm_bench` 8/8）+ 配置门控 LLM 摘要（provenance 保真）+ embedding 优雅降级（反代无 `/embeddings` → 确定性 256 维回退）。一个 20-agent 代码审计确认 **147** 项文档能力已落地 / 接入 / 正确，并发现 7 项真实但轻量缺陷（**全部在 opt-in / 默认关 / 便捷脚本路径**，均已修复并带回归测试）：

- [x] **[Medium] RuleSummarizerProvider 对自身合法输出误报**：retained fact 值含空格（如 `project.test_command=uv run pytest -q`）时 `_validate_result` 的 summary-prose 守卫把截断的 `=uv` 当作 invented fact 抛错，静默禁用滚动历史压缩。已改为接受每个 allowed 值的首空格 token 作为等价 prose 形式。出处：`memory/summarizer_provider.py`。
- [x] **[Medium] admin 异步维护 enqueue 产生孤儿 run**：route 预落 `pending` run A，worker 另建 run B，返回的 run id 永不回填完成状态。已把 `scheduler_run_id` 透传进 `TaskEnvelope`，`run_workspace_maintenance(..., scheduler_run_id=)` 采纳同 workspace 预建 run；仅当该 id 已不存在时才以其重建；绝不采纳 / 复用跨 workspace 的 id。出处：`api/admin_routes.py` / `memory/maintenance.py` / `async_tasks/tasks.py`。
- [x] **[Medium] enqueue 失败把裸 str 赋给 dict summary**：已改为 `{"error": "enqueue failed"}`，SQL 回读不再 ValidationError。出处：`api/admin_routes.py`。
- [x] **[Low] 死代码 `RetrievalController._retrieve_impl`**：无任何调用方，已删除。出处：`retrieval/controller.py`。
- [x] **[Low] replay context-block diff 顺序跨进程不确定**：set 差集改为 `sorted(...)` 迭代，diff 顺序确定。出处：`observability/replay.py`。
- [x] **[Low] `/v1/events` 未映射 `StateTreeError`→400**：已对齐其余所有写路由。出处：`api/routes.py`。
- [x] **[Low] `bun run web:test` 因 cwd 相对路径失败**：showcase 测试改用 `import.meta.dir` 解析仓库路径（CI 的 `bun test` 从仓库根跑本就通过）。出处：`apps/web/test/memory-atlas-ops-showcase.test.tsx`。
- [x] **过时 llm_bench failed_branch 断言**：失败 npm 尝试以 `AVOIDED` 负向证据块出现是 I1–I7 的正确行为而非污染；判定改为只检查正向上下文块。`llm_bench` 现 8/8。出处：`benchmark/llm_bench.py`。

---

## 2. Phase 3 — 可观测性与可视化（★ 最高性价比，优先做）

对齐 architecture §6.9 / §14 Phase 3、draft §9。当前仅有表格 API（`GET /v1/dashboard/tables`，ADR-013）。**先做不依赖前端的 P3-A，再做可视化 P3-B（先 HTML/表，后 React 大前端）。**

### 3-A：后端可观测性（无需大前端，优先级最高）
- **实施计划**：见 `docs/design/P3A_IMPLEMENTATION_PLAN.md`。执行约定：每完成计划 §11 的一个 Issue，都必须同步更新 `.ai/PROJECT_STATE.md`，并 tick 或注释本节对应 checkbox/sub-checkbox。
- [x] **Retrieval Replay**：`replay_retrieval(access_id)` / `replay_run(run_id)` 复现检索→重排→gate→packing。**这是把系统从「跑过一次 demo」升级为「每次检索决策可复现/可解释/可调试」的关键，优先级最高。** 出处：architecture §6.1/§6.9。Phase 3-A Issue 2 已完成其前置基础：`RetrievalController.trace(...)` side-effect-free pipeline + hot-path trace 持久化重构；Phase 3-A Issue 3 已完成 replay service + deterministic diff semantics + runtime facade；Phase 3-A Issue 4 已完成 Replay HTTP API（`GET /v1/replay/access/{access_id}` / `GET /v1/replay/runs/{run_id}`）与最小 observability summary endpoint。
- [x] **eval 表落地**：`eval_cases / eval_runs / eval_results` 已完成 Phase 3-A Issue 1：新增 eval records、Repository/InMemory/SQL 持久化、dashboard table 字段、Alembic `0004_phase3a_observability.py`，并补 `MemoryAccessLog.top_k` 以支持后续 replay 精确重放。出处：architecture §7.1。
- [x] **Quality & Safety 指标统一进 profiler**：failed_branch_contamination / stale_injection / tool_safety / workspace_leakage（部分 benchmark 已覆盖，需统一到 profiler）。Phase 3-A Issue 5 已完成为只读 computed observability metrics：access-level helper + summary by_strategy，不默认写入 `quality` / `safety` `ProfileEvent`。
- [x] **完整 phase-aware Profiler**：扩到 architecture §6.9 的 10 阶段归因（Ingestion/Construction/Retrieval/Rerank/Gate/Context Packing/Generation/Maintenance/Quality/Safety）。Phase 3-A Issue 5 已扩展 `ProfilePhase` enum 并保留既有值稳定；不为尚无真实操作的阶段伪造 profile rows。
- [x] **最小 Dashboard（静态 HTML 报告优先，不急于上 React）**。Phase 3-A Issue 6 已完成 dashboard table API 扩展：`GET /v1/dashboard/tables` 保留既有 rows，并返回 eval rows + workspace-scoped `observability_summary`；Phase 3-A Issue 7 已完成静态 JSON/Markdown/HTML observability reports（`POST /v1/observability/reports` + `reports/observability_report.{json,md,html}`，含 summary、strategy breakdown、quality/safety、slowest accesses、replay drift、access details，且 output_dir 限制在 `reports/` 下）。

### 3-B：前端可视化（在 3-A 稳定后）
- **当前选定计划（2026-06-17）**：见 `docs/design/PHASE3B_DASHBOARD_PLAN.md`。目标是在 `apps/web` 建一个 showpiece-grade React + TypeScript dashboard：真实产品首屏而非 landing page，复用 `@memtrace/sdk` / `/v1` read-only APIs，突出 Timeline、State Tree、Gate Analysis、Memory Flow、Benchmark Lab、Memory Atlas 与 fixture-backed showcase mode。任何 backend 变更都必须是 bounded read-only projection，并保留现有 authz/quota/redaction/workspace isolation；`/v1/dashboard/ui` 保持轻量静态查看器，不继续扩展成大型前端。
- [x] **Built-in read-only static Dashboard UI (`/v1/dashboard/ui`)**：2026-06-15 已作为轻量查看器落地，单文件 HTML/inline CSS/vanilla JS，无 build step / external JS / CDN，只消费既有 read-only API。它不是 Phase 3-B React/TS dashboard 的完成标记，也不应继续沿 Python HTML 字符串扩展成大型前端。
- [x] **React + TS 前端 Dashboard (`apps/web`)**：WEB-A/WEB-B 已完成并经审查加固，WEB-C visual system、WEB-D Overview/run gallery、WEB-E Run Explorer、WEB-F Access Replay / Memory Flow、WEB-G Benchmark Lab、WEB-H Memory Atlas / Ops Read-Only、WEB-I Showcase / screenshot workflow、WEB-J docs/testing closeout 均已完成。
  - [x] Scaffold `apps/web` as a Bun workspace React/Vite app over `@memtrace/sdk`.
  - [x] WEB-B data boundary: SDK-backed client/query hooks, typed view models/normalizers, fixture validation, `CapabilityState`, explicit request/error states, protocol-relative API-origin rejection, TS SDK ops-table DTO alignment, and tests.
  - [x] WEB-C visual system: tokens, app chrome, metric/status/empty primitives, icon buttons, theme toggle, drawer/score/timeline/token/strategy/error primitives, responsive overview styling, and component coverage.
  - [x] WEB-D Overview / run gallery with workspace connection, observability summary, recent runs/accesses, strategy comparison, explicit safety/compaction/negative-evidence signals, selected-run drawer, and owner-gated ops state.
  - [x] Run Trace Timeline (`/runs/:runId`, route-specific timeline/state-tree/steps/profile loading)
  - [x] **State Tree Viewer**（active path / failed branch / recovery 可视化；当前为 responsive state-tree graph，pan/zoom graph canvas 可后续 polish）
  - [x] Gate Analysis Panel (`/access/:accessId`, inspect/replay-backed gate decision matrix with final/component scores)
  - [x] **Memory Flow**（候选→gate→context；当前为 responsive flow graph，Sankey-style graph 可后续 polish）
  - [x] Cost Breakdown / Replay Panel（token pressure + replay drift summary）
  - [x] Benchmark Lab for six strategies / all returned benchmark cases (current fixture/live acceptance covers 13 known cases), contamination, token bloat, compaction, and negative-evidence retention.
  - [x] Memory Atlas for lifecycle/conflicts/versions and owner-gated read-only ops panels.
  - [x] Fixture-backed Showcase mode plus screenshot/playwright verification workflow.

---

## 3. Phase 4 — 异步基础设施 + 记忆生命周期（依赖链核心）

architecture §6.8 / §12 / §14 Phase 4、draft §8。**大量 Cold Path 能力共同依赖 Celery+Redis，应作为前置基建优先。**

### 3.1 异步基础设施
- [x] **Celery 异步任务队列** + **多队列拆分**（`memory_queue / maintenance_queue / eval_queue`）。✅ P4-A1/P4-A2 已完成并审查加固：settings 默认关闭/eager-safe，`make_celery_app(...)` 注册 memory/maintenance/eval queues，JSON-only serialization，eager task wrapper 通过 runtime-level `process_event_extraction(...)` 执行且不依赖 FastAPI `app_state`；task contracts 拒绝 raw secret-like payload/result/error。
- [x] **Redis**：broker + 热点缓存 + 幂等锁 + active session key。✅ P4-A2/P4-A5 已完成首批基础设施：`RedisIdempotencyStore` 提供 SET NX EX 幂等锁边界，默认 worker path 在 async+redis 启用时懒加载 Redis idempotency；`RedisCandidateBuffer` 维护编码后的 session↔workspace 索引；`docker-compose.dev.yml` 提供 opt-in Redis/worker dev stack，真实 Redis smoke 由 `MEMTRACE_TEST_REDIS_URL` 保护且默认跳过。
- [x] **Redis-backed candidate buffer + idle flush**（替换当前进程内 buffer）。✅ P4-A3 已完成 async `CandidateBufferProtocol`、确定性 in-process buffer async 化、Redis post-redaction `AgentEvent` JSON buffer、encoded key segments、Lua-backed atomic detach drain、session-only flush 兼容和默认 in-memory / opt-in Redis runtime selection；buffered flush/worker extraction 统一复用 persisted-event 安全检查。
- [x] **完整写入模式矩阵**：`async / sync_flush / lazy / no_extract`（§12.1）+ async enqueue fallback。✅ P4-A4 已完成 `ExtractionMode.async_ = "async"`、`sync_flush`、`lazy`、`no_extract`，`WriteEventResult.queued/task_id/warnings`，event-id-only `TaskEnvelope` payload，成功 enqueue 不内联抽取，enqueue 失败回退 post-redaction lazy buffer；默认 sync benchmark 行为不变。LLM extraction 失败 async retry 仍以后续生产 worker retry policy 承接。

### 3.2 Reflection / Forgetting 调度器（★ 高价值，P4-B 已落首批）
- **后续选定计划（2026-06-14；MADM-A/B/C/D/E 全部完成并复审加固 2026-06-15）**：`docs/design/MAINTENANCE_ADMIN_GOVERNANCE_PLAN.md` 已选为当前实施目标并已完成，聚焦 maintenance scheduler / admin governance depth。MADM-A 完成 admin/maintenance settings、owner-gated admin helper、durable `MaintenanceRunRecord` / `MaintenanceTaskAttemptRecord` / `AdminActionAuditRecord` / `QuotaLimitRecord`、in-memory/SQL repository methods、ORM tables 与 Alembic `0012_maintenance_admin_governance`。MADM-B 完成 expanded first-wave maintenance operations 与 `run_workspace_maintenance(...)` direct/Celery 统一编排、dry-run、per-operation failure isolation。MADM-C 完成 default-off owner-gated `/v1/admin/maintenance/runs`（direct/enqueue）、list/get/attempts、`/v1/admin/lifecycle-audits`，复审修复 enqueue 路径的重复-operation 校验与 run-level redaction 缺口。MADM-D 完成 owner-gated API key admin（一次性 raw `mtk_` key、digest-free public DTO、幂等 revoke）、quota override admin（principal->workspace->settings 覆盖查找、仅 `quota_enabled` 时读 DB）、manual lifecycle/conflict resolution admin，复审修复 `conflicted->superseded` 合法转移、choose_winner loser 预校验、已解决冲突 409、quota 跨 unit identity。MADM-E 完成 dashboard/report admin observability（`maintenance_runs/maintenance_task_attempts/admin_action_audits/quota_limits` workspace-scoped surfacing + report maintenance summary）、SDK/CLI docs-only 决策（无 SDK admin facade）、README/deployment/ROADMAP/`.ai` closeout。默认仍不启用 admin/governance/Redis/Celery；reproduce 保持 **13/13**。SDK admin facade 与 Phase 3-B 前端仍为远期候选。
- [x] **多维评分模型首版**：P4-B2 已实现 `compute_retention_signals(...)`，使用 `value_score / freshness_score / trust_score / risk_score / access_count / last_accessed_at / expires_at` 计算独立 `retention_score` / `reflection_priority`；过期/高风险记忆降权且不会被评分重新变为可检索。
- [x] **决策分数分离**：P4-B2/P4-B3 已新增 `memory_retention_signals` 表，scheduler 输出与 `MemoryItem` 内容/状态分离；retrieval 仍使用相关性/gate 分，`variant_3` 仅在 accepted 后用 `reflection_priority` 重排。
- [x] **真实 Reflection 信号源替代 reflection-lite 优先级**：P4-B3 已让 `variant_3` bulk-load `MemoryRetentionSignal.reflection_priority`，有持久化信号时使用 `reflection_signal_source="scheduler_v1"`，无信号时保留 deterministic fallback `reflection_signal_source="fallback_lite"`，默认 benchmark/reproduce 稳定不变。
- [x] **完整生命周期状态机首版**：P4-B1 已实现 `active→dormant→archived→deleted` + `pinned/conflicted/quarantined/superseded` 旁路转移；pin 记录 `previous_status`，unpin 恢复安全 previous status；scheduler 不会归档 pinned。
- [x] **10 个定时任务补全**：P4-B3 已完成 `score_memory / decay_memory / archive_memory / quarantine_memory / profile_refresh` 的直接 async 函数与 `maintenance.memory` Celery wrapper；MADM-A 已落 durable scheduler run/task attempt/admin audit/quota override foundations；MADM-B 已补齐 `conflict_scan / dedup_memory / reindex_memory / summary_refresh / procedural_refresh`，并统一 direct/Celery 编排、durable run/attempt 记录、dry-run skipped attempts 与 redacted failure summary，且通过完整复审加固 paginated conflict stale resolution、dedup sensitive-key handling、legacy run-memory replacement、run-level redaction、run immutability 和 Celery failed-run retry behavior。MADM-C/D/E 已完成 owner-gated admin maintenance/lifecycle/conflict/API-key/quota APIs、dashboard/report surfacing、docs-only SDK admin decision 与 closeout。
- [x] **审计日志**：P4-B1 已新增 `MemoryLifecycleAuditRecord` / `memory_lifecycle_audits`，scheduler 生命周期状态变更写 audit log。

### 3.3 冲突 / 版本管理（在 P2 基础版上补全）
- [x] **`memory_versions` 表 + Version Manager**：P4-C1 已完成（2026-06-14）。新增 `MemoryVersionRecord` / `memory_versions`、红线脱敏 snapshot helper、semantic-change 判定；`update_memory(...)` 与 lifecycle transition 会记录版本，access-count-only / `last_accessed_at` 更新不记录版本。
- [x] **`memory_conflicts` 表 + conflict_scan 读路径**：P4-C2 已完成（2026-06-14）。新增 `MemoryConflictRecord` / `memory_conflicts`、ontology-backed conflict scan、HTTP read APIs `GET /v1/memory-conflicts` 与 `GET /v1/memories/{memory_id}/versions`，dashboard table payload 暴露 versions/conflicts。
- [x] **7 条完整冲突规则**（时间覆盖、tool result 优先、provenance 解释链）。**已完成（2026-06-30）**：新增确定性纯模块 `apps/api/app/memory/conflict_policy.py`（`decide_conflict`），编码 architecture §6.7 七条规则的优先序——R4 用户显式纠正 (`lifecycle_metadata["user_correction"]`) ＞ R5 来源权威（tool result / asserted fact ＞ assistant 推断的 `working_state`/`episodic`）＞ R6 completed ＞ active ＞ rolled_back ＞ failed 分支 ＞ R2 显式有效时间 (`lifecycle_metadata["valid_from"]`，presence 后 recency) ＞ legacy `trust_score`/`updated_at` tie-break ＞ R3 真正平局＝uncertain（`conflicted`，无 winner）。R1（检测）/R7（跨 workspace）仍由 `detect_memory_conflicts`/dedup identity 在上游强制。该策略是旧 `max((trust,updated))` resolver 的**向后兼容超集**：R4/R5/R6/R2 不区分时退回原 legacy 行为，所有既有 resolver/conflict 测试与 benchmark `case_5` 不变。`conflicts._explanation` 现追加脱敏、确定性的 provenance 建议链（`Suggested resolution (<rule>): keep <winner>, supersede <losers>`，仅引用 id+rule，不含原值）。出处：architecture §6.7 / draft §1.8。

### 3.4 多租户治理（★ P4-D 已落首批）

> **状态（2026-06-14）**：P4-D governance 首批已完成并保持 default-off：本地/dev/benchmark 默认无 auth、无 quota、无治理依赖；启用 auth 后支持 legacy `MEMTRACE_API_KEY` 与 DB API key 的安全过渡，DB key 存储使用 prefix+digest；资源 ID 路由会先解析 workspace ownership 再授权；quota / redaction policy 均为 config-gated。完整 JWT、membership table、admin conflict review UI、per-tenant quota override 存储与 encrypted raw payload store 仍是后续治理/admin work。
> **后续选定计划（2026-06-14）**：`docs/design/MAINTENANCE_ADMIN_GOVERNANCE_PLAN.md` 将先做无前端的 owner-gated admin HTTP surface：maintenance run 启动/查看、lifecycle audit、manual memory status transition、conflict resolution、API key create/list/revoke、quota limit override。计划已按源码审查修订：不支持 anonymous admin；admin list API 使用 bounded `limit/offset`；quota workspace-wide override 使用 PostgreSQL partial unique indexes；API key public DTO 不返回 digest；quota override lookup 仅在 quota enabled 热路径生效。JWT/OIDC、membership table、React admin UI、encrypted raw payload store 仍不在本轮。

- [x] **API Key / workspace 权限系统首版**（`api_keys` 表）。P4-D1 已新增 prefix+digest API key 模型、`Principal` / `WorkspacePermission`、workspace-scoped role hierarchy、legacy-key fallback disable rule，以及 run/step/access/memory/eval resource-owner lookup helpers；resource-id routes enforce 404 for missing resources and 403 for unauthorized existing resources. JWT / membership table remains future work.
- [x] **多租户配额 (quota) / 限流首版**。P4-D2 已新增 fixed-window quota service with per-workspace/principal/unit counters (`write_event`, `retrieve_context`, `report_export`, `replay`, `async_task_enqueue`), configurable default limits, default-off behavior, and fail-closed 503 on quota-counter errors only when governance is enabled. Production Redis-backed distributed counter / DB override records remain future work.
- [x] **字段级脱敏 / redaction 状态机首版**。P4-D3 已新增 `none/redacted/digest_only/blocked` decision policy, default redaction behavior, operator-secret-gated HMAC digest behavior（未配置 digest secret 时不持久化裸 secret 指纹）, blocked-content no-store behavior, and raw payload retention guard requiring governance-enabled encrypted store configuration. Encrypted raw payload persistence itself remains disabled/future work per ADR-017.
- [x] **人工审核 memory conflict 管理后台**（admin）。owner-gated HTTP admin workflow 已完成：`POST /v1/admin/memory-conflicts/{id}/resolve` 支持 `mark_false_positive` / `choose_winner`（MADM-D 已落），并于 2026-06-30 新增 `apply_suggested`——按 §3.3 七规则策略自动选定 winner、supersede losers（审计 `applied_rule`），对 R3 uncertain 平局返回 HTTP 409 要求人工 `choose_winner`；冲突记录 `explanation` 现内联 suggested-resolution provenance 链供人工审核参考。React 管理后台 UI 仍后置（无 admin mutation UI by design）。

---

## 4. Phase 5 — 高级存储与检索（★ 整体后置，需触发条件）

architecture §3.3 / §7 / §8、draft §3/§5。**仅在以下条件满足时才启动（避免过早引入 ES+Neo4j 的部署/一致性/讲解复杂度，削弱主线）：**
> 1. pgvector / lexical / 当前检索在 benchmark 中已成为瓶颈；
> 2. 出现需要图谱 provenance 或 multi-hop retrieval 才能支撑的新 case；
> 3. Phase 3 可观测性与 Phase 4 lifecycle 已稳定。

- [ ] **Elasticsearch / OpenSearch 混合检索**（dense vector + BM25 + filter + valid_time + branch_status）。出处：architecture §8.2，「第一阶段推荐」但被 pgvector 替代。
- [ ] **Neo4j 溯源图谱**：完整图模型 + `SUPERSEDES/CONFLICTS_WITH` 关系。出处：architecture §7.5 / §8。
- [ ] **图邻居扩展检索**（Neo4j neighbor expansion，最大 2 hop）+ `graph_relatedness_score` 排序项。
- [ ] **多路候选融合 RRF/加权**（vector + BM25 + graph）+ 按 task_intent 切换 ranking_profiles。出处：architecture §6.5。**opt-in micro-slice 部分完成**：已实现 deterministic、无外部依赖的 Reciprocal Rank Fusion (RRF) 融合 lexical + vector 两路排名，默认仍为 `linear` 加权（benchmark/replay 行为不变），通过 `MEMTRACE_RETRIEVAL_FUSION=rrf` 切换；配置仅允许 `linear` / `rrf`，vector 显式关闭时 policy snapshot 退回记录默认 linear 语义。此 micro-slice 不代表 Phase 5 已启动；BM25/graph 路与 task_intent ranking_profiles 仍后置（依赖 ES/Neo4j 触发条件）。
- [ ] **多存储最终一致性**：`index_status / graph_status / last_indexed_at` + 后台 reindex/graph sync 重试。
- [ ] **Query Planner**（query rewrite + entity/keyword hints）+ Need-Retrieval Decision（简单任务跳过检索）。
- [ ] **多跳迭代检索 (Iterative Reconstruction)**：cue→tag/entity→content/evidence，每跳受 token budget 限制。出处：draft §5（MRAgent/AdaMEM 方向）。

---

## 5. 状态树高级能力（多数后置）

architecture §6.3、draft §3（MAGE 方向）、ADR-004 推迟。

- [x] **Completed subgoal 压缩成 summary node**。**已完成（2026-06-30，默认关闭的最小子集，与 §9 Context Compaction 协同）。** 新增 config `summary_node_compression_enabled`（默认 `False`）+ `active_path_summary_threshold`（默认 8）+ `active_path_summary_keep_recent`（默认 3）。`build_active_path_block(..., summarize_after, keep_recent)` 在启用且活动路径上 completed step 数超过阈值时，把最旧的 completed subgoal 折叠成单个确定性 summary 段（`[N earlier completed steps summarized]`），仅保留最近 N 个原样展示，使这个**受保护**块在长程任务下有界；默认 `summarize_after=0` 时逐个列出（行为不变）。Controller 仅在启用时传非零参数，replay 复用同一 controller 的参数避免假漂移。无 enum/schema/migration 改动，benchmark/reproduce 仍 13/13。`StateNodeType` 仍为 `root/step/recovery`；完整 node_type（含 `summary`/`subgoal`/`tool_call`）与 subgoal 自动推断仍后置。
- [ ] **Subgoal 自动推断**（当前仅显式 `root/step/recovery`）。**后置——会变成「智能状态树」研究课题。**
- [ ] **完整 node_type**：`root/subgoal/step/tool_call/recovery/summary`。**后置。**
- [ ] **MAGE 四类操作**：Grow / Compress / Maintain / Revise。**后置。**

---

## 6. SDK / 集成 / 可观测性导出

architecture §3/§9/§External、MVP_SCOPE Out-of-Scope #3、§15 明确「后做」。**推进顺序：Python SDK / LangGraph Adapter > CLI > TS SDK > MCP Server > IDE 插件。前两项可提前到 Phase 3.5（最能证明「可插拔 runtime，而非必须用自带 agent loop」的定位）。**

- [x] **【提前·Phase 3.5】独立 Python SDK 包**（`packages/python-sdk`）+ **LangGraph Adapter**（before/after node 钩子）+ `examples/` 下一个 custom-loop 与一个 langgraph 接入示例。证明「任意 agent loop → 接入 MemTrace → trace/retrieve/gate/profiler」。
  - [x] S1 prerequisite: core `event_source` passthrough is complete (`WriteEventRequest.event_source` → `AgentEvent.event_source`), enabling SDK/adapter/CLI entrypoint stamping without changing existing default behavior.
  - [x] S0 packaging/workspace skeleton: `packages/python-sdk` is a uv workspace member with importable `memtrace_sdk` placeholder public surface, console-script stub, and pytest discovery wired into the full suite.
  - [x] S2a shared SDK contract + in-process backend: `memtrace_sdk.types` re-exports core runtime DTOs/enums, `Backend` Protocol mirrors runtime hot path/read/observability methods, `InProcessBackend` wraps `MemoryRuntime` with HTTP-aligned `NotFoundError` / `BadRequestError` mapping while preserving empty-list reads, and `MemTrace.in_process` / `MemTrace.in_memory` provide the unified client with default `event_source="sdk"`.
  - [x] S2b HTTP backend + route/isomorphism: `GET /v1/runs/{run_id}/steps` returns `list[AgentStep]` and preserves missing-run `[]`; `HttpBackend` mirrors `/v1` with Pydantic JSON/list parsing, 404→`NotFoundError`, 400→`BadRequestError`, bearer-token header support, single-step `get_step`, and owned/injected `httpx.AsyncClient` lifecycle; `MemTrace.http(...)` plus ASGITransport tests prove HTTP/in-process backend shape equivalence.
  - [x] S3 LangGraph adapter: `MemTraceLangGraphAdapter` provides `before_node` / `after_node` / `on_error` hooks plus a thin `wrap_node(...)` helper without importing langgraph; adapter-written events stamp `event_source="langgraph_adapter"`, `after_node` returns both `WriteEventResult` and `FinishStepResult`, and failure tests assert rolled-back branches stay out of positive context while allowing I3 negative-evidence blocks only in `avoided_attempts` / `source="negative_evidence"`.
  - [x] S4 examples: `examples/simple_agent` is a deterministic custom loop over `MemTrace.in_memory(...)` that prints the baseline `npm test` contamination vs variant_2 `bun test` recovery contrast; `examples/langgraph_adapter` wires a minimal graph through `MemTraceLangGraphAdapter` and exits 0 with an actionable skip when `langgraph` is absent; `packages/python-sdk/tests/test_examples_smoke.py` covers both paths.
- [x] **CLI 入口**（Python SDK / HTTP / CLI 三入口之一）：`memtrace` argparse CLI 已接入 SDK facade；operational commands (`start-run`/`start-step`/`write-event`/`retrieve`/`timeline`/`state-tree`/`inspect-access`/`report`) 必须显式 `--http` 连接持久服务，避免跨进程 in-memory 状态丢失；`demo --in-process` / `demo --http` 为一次性场景；CLI 写事件显式 `event_source="cli"`；`packages/python-sdk/tests/test_cli.py` 覆盖 in-process demo、HTTP demo、HTTP requirement、JSON retrieve、404 exit、CLI event_source。
- [x] **TypeScript SDK** (`packages/ts-sdk`)。INT-A 已完成（2026-06-14）：Bun workspace + `@memtrace/sdk`、strict DTOs/client/errors、Phase 4 HTTP surface（400/422/401/403/404/429、async extraction、body-based session flush、path-authoritative complete-run、memory versions/conflicts）、mock contract smoke、optional real-service smoke、`examples/ts-simple-agent`；验证：TS typecheck passed、SDK tests **9 passed, 1 skipped**、Python SDK HTTP/isomorphism **13 passed**。
- [x] **MCP Server** (`packages/mcp-server`)。INT-B 已完成并经详细审查补强（2026-06-14）：Bun workspace + `@memtrace/mcp-server`、env-based `MEMTRACE_BASE_URL` / `MEMTRACE_API_KEY` config、stdio MCP server、first-wave tools (`start_run/start_step/write_event/retrieve_context/inspect_access`)、second-wave tools (`finish_step/replay_access/report`)、concise redacted outputs、8k replay/report cap、recursive JSON + key/value secret redaction hardening（覆盖 `authorization`、bare `token`、`client_secret`、`secret_key`、`id_token`、`*_token` / `*_secret` / `*_credential`）、unknown-tool error redaction/cap、HTTP(S)-only no-userinfo base URL validation、README MCP config snippet, and SDK-only/no-Python-import/package-boundary tests；验证：MCP tool tests **16 passed**、package-local MCP tests **18 passed**、root Bun tests **27 passed, 1 skipped**、TS typecheck passed、SDK tests **9 passed, 1 skipped**。
- [x] **MCP config templates / IDE thin layer**（Claude Code / Cursor）。INT-C 已完成（2026-06-14）：新增 `examples/mcp/claude-code.json` / `examples/mcp/cursor.json` 与 `@memtrace/mcp-server` 导出的 `MCP_CONFIG_TEMPLATES`，模板只使用 `${MEMTRACE_BASE_URL}` / `${MEMTRACE_API_KEY}` 环境变量占位且不含真实 secret；README 提供 copy-paste 片段并说明 MCP 仍通过 TS SDK 调 HTTP `/v1`。INT-C2 决策为暂不创建专用 IDE 包，等 MCP adoption 反馈后再评估；验证：Bun workspace tests **27 passed, 1 skipped**、TS typecheck passed。
- [x] **R1 Release Readiness / Public Adoption — complete**（2026-06-14）：`docs/design/RELEASE_READINESS_PLAN.md` 已完成。A0 command inventory 已确认 CLI/Python demo 稳定 marker、HTTP/TS/MCP 前置条件与 runtime requirement 分类；A1 README 已重写为公共 landing page；A2 新增 `docs/getting-started.md`、`docs/concepts.md`、`docs/mcp.md`、`docs/benchmark.md`、`docs/deployment.md`；A3 新增 canonical no-network release-readiness smoke `scripts/smoke-release-readiness.sh` 并文档化可选 HTTP/TS env-gated smoke；B1 为 `@memtrace/sdk` / `@memtrace/mcp-server` 增加 private source-entry package metadata、exports/files 与 package-shape tests；B2 更新 Python package metadata 并锁定 CLI readiness；B3 新增 `.github/workflows/ci.yml`，默认运行 Python compile/full pytest、Bun typecheck/tests、release hygiene，且不要求 Postgres/Redis/LLM/live HTTP；C1 新增 `docs/release-checklist.md` 并从 README 维护者导航链接；C2 已完成 Python/JS 验证、benchmark/reproduce closeout、tracked-file/public-doc release hygiene 与 ROADMAP/`.ai` sync。`bash scripts/reproduce.sh` 打印 `acceptance.passed=true (13/13 checks true)`。R1 仅包装现有能力，不改变 runtime retrieval/gate/context semantics。
- [x] **OpenTelemetry / OpenInference exporter**（接 LangSmith/Phoenix/Langfuse）。✅ **已完成核心 exporter slice（2026-06-14）**：详见 `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md`。范围限定为默认关闭的 OTLP/OpenInference 核心 exporter：MemTrace DTO → redacted telemetry spans/events、noop/in-memory/JSONL/optional OTLP exporters、best-effort runtime hooks、可选 read-only run export、docs/`.ai` closeout。**Segment 1 已完成并经详细审查补强（2026-06-14）：TEL-A1/TEL-A2/TEL-B1/TEL-B2 与 TEL-B3 minimal replay/benchmark projection 纯代码落地，新增 `apps/api/app/telemetry/{models,semconv,redaction,builder}.py`，覆盖稳定 `memtrace.*` 语义常量、OTel-safe primitive/list attribute DTO（`None` 省略/拒绝）、递归脱敏/预算、raw-content-like metadata 脱敏、run/step/event/retrieval/gate/profile/replay/benchmark 纯 builder、optional-run-id trace fallback。**Segment 2 已完成并经最终审查补强（2026-06-14）：TEL-C1/TEL-C2/TEL-D1 新增 `exporters.py` / `factory.py` / `service.py`、default-off telemetry settings、safe JSONL exporter、in-memory/noop exporters、optional lazy OTLP exporter、strict/header/sample-rate settings、factory validation/degradation、fail-open `TelemetryService` facade、以及 telemetry exporter/service tests。**Segment 3 已完成并经详细审查补强（2026-06-14）：TEL-D2 runtime hooks 注入 `MemoryRuntime`，在权威持久化后 best-effort 导出 terminal run/step snapshots + event/retrieval spans，hooks 即使注入 fail-closed service/exporter 也保持 fail-open，retrieval projection 读取失败也不影响 hot path，且避免同一 run/step lifecycle 重复稳定 span id；TEL-D3 新增 `POST /v1/telemetry/export/runs/{run_id}` read-only endpoint，沿用 report-reader authz 并消耗既有 `report_export` quota，仅返回 counts/generic warnings；TEL-E2 README/concepts/deployment 文档覆盖 default-off JSONL、optional OTLP、vendor non-goals 与 CLI export defer。**Segment 4 verification / closeout 已完成并在最终全计划审查后重跑（2026-06-14）：targeted telemetry/runtime/API **51 passed**，affected runtime/API/observability **194 passed**，compileall passed，full pytest **658 passed, 2 skipped**，benchmark/reproduce 保持 `acceptance.passed=true (13/13 checks true)`，release hygiene 与 `git diff --check` passed。热路径 hooks 不同步做网络 OTLP export；LangSmith/Phoenix/Langfuse 暂作为 OTLP/OpenInference 兼容目的地说明，不引入 vendor SDK；CLI telemetry-export 与 richer access/backfill surfaces 仍后置。
- [ ] **专用 IDE 插件**（VS Code 等）。MCP config templates 已完成；专用扩展继续后置，触发条件是 MCP 流程有真实 adoption 反馈且出现编辑器特定需求。
- [ ] **【远期·scale-only】Go Trace Collector / Gateway**、**Rust profile analyzer**。**触发条件：Python ingestion QPS 或 profiling 分析成为真实瓶颈时再做；当前阶段重点是机制与评测，不是 QPS。** 出处：architecture §3.2 / §15。

---

## 7. 评估 / Benchmark 扩展

- [x] **真实 LLM bench 扩展场景**（`app/benchmark/llm_bench.py`，现 8 场景）：✅ 已实现并实测——memory_override / scale_retrieval / llm_vs_rule / nl_extraction + 新增 failed_branch_isolation / workspace_isolation / stale_rejection / tool_safety。多端点可移植性对比经 `MEMTRACE_LLM_BENCH_ENDPOINTS`（JSON 列表）支持，单端点经标准 `MEMTRACE_LLM_*`。火山方舟 deepseek 实测 8/8 PASS。
- [x] **完整 6 策略对比**（★ 优先于 LoCoMo）：no memory / long-context / vector / state-aware / +gate / +reflection（+reflection 依赖 §3.2）。这是最有说服力、最好讲的 benchmark——逐层证明每个机制的收益（无记忆失败 → 全塞污染/高 token → 向量相似但失败分支污染 → 状态感知改善 → +gate 污染率显著下降 → +reflection 长期质量提升）。出处：architecture §6.10。已实现：strategies = no-memory (`baseline_0`) / long-context (`long_context`) / vector (`baseline_1`) / state-aware (`variant_1`) / +gate (`variant_2`) / +reflection (`variant_3`)；+reflection 为确定性 reflection-lite（`retention_score` 用 trust/freshness/access_count 重排 accepted），由 `case_12_reflection_retention` 证明在紧预算下保留高价值记忆而 +gate 丢弃。
- [x] **benchmark report 落库**（配合 §2 eval 表）。`run_benchmark(repo=...)` 现额外写入 `eval_runs` / `eval_cases` / `eval_results`（复用 Phase 3-A eval schema，无新迁移）。
- [ ] **小规模 LoCoMo / MemoryArena**（§15 标注「可做小规模，不优先刷榜」）。**降级：核心贡献是 Agent Runtime 级记忆治理，不是刷通用长记忆榜，排在 6 策略对比之后。**
- [ ] **集成/回归测试补全**：unit（gate/packer/state transition/extractor parser）、integration（API + postgres + migration + retrieval）、e2e（demo agent + benchmark）、regression（failed_branch / workspace_isolation / stale / tool_safety）。
- [ ] **Docker Compose 分层（避免开发环境过重）**：`compose.core`（api + postgres）/ `compose.dev`（+ redis + worker）/ `compose.full`（+ es + neo4j + frontend）。出处：draft §12.4 / §11。

---

## 8. 明确不做（Out of Scope，记录以避免重复讨论）

architecture §15 / draft §7 / MVP_SCOPE：

- 图片 OCR / 音频 / 多模态摄取、大而全文档知识库。
- 复杂社区发现 / 全量知识图谱前端。
- 训练式 MemGate 小模型（高风险候选可用 LLM-judge，但不训练模型）。
- LoCoMo/MemoryArena 全量刷榜。
- 多 Agent 协作平台。

---

## 9. Context Compaction（上下文压缩 / 历史折叠）★ 与系统定位强相关

> **实施计划（2026-06-11）**：本节已细化为 Issue-by-Issue 计划 `docs/design/CONTEXT_COMPACTION_PLAN.md`。**状态：C0 `PackResult` + callsite behavior-preserving refactor、C1 packer 超预算压缩补偿、C2 durable `ContextCompactionLog` + observability/replay wiring、C3 可配置 rule/LLM `SummarizerProvider`、C4 config-gated 运行中 rolling history summary、C5 压缩质量指标 + benchmark/report/replay/project-memory sync 均已完成并通过回归。**

mem-trace 定位为「long-horizon agent 的状态感知记忆运行时」，而长程 agent 的核心痛点正是 **context window 撑爆**。C0-C5 之前，系统对「上下文超限」只做**丢弃式截断**（见 §1 技术债）；现在已完成 trace-aware context compaction 闭环：预算超限时保留关键约束和审计 notice，运行中长历史可 config-gated 折叠为 `history_summary`，并通过 durable `ContextCompactionLog` 支撑 observability / replay / benchmark。它独立于 §3.2（生命周期衰减）与 §5（状态树压缩），三者协同但不重叠。

现状盘点：
- ✅ **run 结束摘要**（`summarizer.build_run_summary`，冷路径）：把已结束 run 的 trace 蒸馏成 episodic + procedural memory。压缩的是「已结束轨迹→长期记忆」，**不解决运行中长历史超窗**。
- ✅ **active path 进度块**（`packer.build_active_path_block`）：把 completed 节点 label 串成一句，是拼接展示**非压缩**。
- ✅ **运行时 context compaction（C4 rolling history summary）**：config-gated `compaction_enabled` 路径已能把超阈值 active-path 历史折叠为 protected `history_summary` block，并持久化 `ContextCompactionLog(kind=history_summary)`；replay 读取持久化快照，不 rerun summarizer。

已完成项 / 剩余协同项：
- [x] **packer 超预算压缩补偿（替代纯丢弃）**：`pack_context` 超 `token_budget` 时，对被丢弃的低优先级块做「合并摘要 / 块内裁剪」而非整块丢弃，至少保留一条「已省略 N 条记忆（含约束 X/Y）」的占位摘要，避免约束静默丢失。C1 已实现 `compacted_constraints` / `compaction_notice` / protected-block deterministic truncation；C2 已实现 durable `ContextCompactionLog`、observability summary compaction metrics、replay payload 与 `compaction_drift`。出处：§1 技术债 / `packer.py`。
- [x] **运行中长历史折叠**：当一个 run 的 active-path 事件历史超过阈值时，对安全过滤后的早期历史做 rolling summary，再以 protected `history_summary` block 注入上下文；持久化 `ContextCompactionLog(kind=history_summary)`，timeout/error 降级为 no-fold + warning，replay 读取持久化快照不 rerun summarizer。
- [x] **可配置 summarizer（规则 / LLM 双路）**：compaction 的摘要器需 config-gate（默认规则保 benchmark 可复现；启用 LLM 走 `LLMExtractionProvider` 同款注入 + 失败降级），与 extraction 管线对齐。C3 已实现 `SummarizerProvider` Protocol、deterministic `RuleSummarizerProvider`、OpenAI-compatible `LLMSummarizerProvider`、保守 retained-fact validation、DI wiring 与 runtime fallback。
- [x] **压缩质量指标**：benchmark 新增 `case_9_over_budget_compaction`，runner 输出 `compaction_trigger_rate` / `constraint_retention_hit_rate` / `unsafe_compaction_leakage_rate` / `avg_compression_ratio`，acceptance 检查 `variant_2_retains_constraints_under_compaction`；observability report 新增 Compaction section，replay 端到端覆盖 `compaction_drift`。出处：architecture §6.8 `compression_gain`。
- [ ] **协同项（交叉引用）**：state tree 的 completed subgoal → summary node（§5）、生命周期 decay/archive 把旧记忆降级压缩（§3.2）。这三处共同构成完整的「记忆/上下文压缩」体系，建议一并设计。

---

## 9.1 Failure-aware Negative Memory Injection（失败感知负向记忆注入）★ 首批已完成

> **实施计划（2026-06-11）**：Issue-by-Issue 计划 `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`。首批 I1-I6 已完成：I1 Gate 三路输出、I2 DTO/builder/packer、I3 controller 主路径接线、I4 inspect/replay/metrics 接线、I5 benchmark/evaluator 扩展、I6 文档/项目记忆同步。I7 compaction negative retained 也已完成：retained-negative DTO、dedicated compaction-log field、SQL JSONB migration/mapping、packer dropped-block metadata retention、replay/metrics/reports/trace-bundle surfacing、benchmark `case_13_compaction_retains_negative_lesson` 与 acceptance `variant_2_retains_negative_lesson_under_compaction`。

这是 §9 Context Compaction「安全过滤」的**反向补集**：compaction 把 failed/rolled_back/secret 从 summary 中排除，而本节在**安全前提下受控保留失败教训**，二者共享同一套安全分级口径。

当前 gate 对 failed/rolled_back 分支一刀切 hard reject（`gate.py:109-112`），coding agent 因此丢失「以前为什么错、哪个命令失败过、哪条路径不要再走」的负向学习信号。升级方向：**失败分支不作为正向上下文注入，但失败原因以「负向证据 / 避坑提示」受控注入**。

- [x] **Gate 三路输出**：I1 已完成。把 `accept / reject` 二元升级为 `accept / degrade / reject`；failed/rolled_back 且安全（非 secret/destructive/tool_sensitive/production_env）→ `degrade` 进负向通道；危险/secret/production 操作仍 hard reject。新增 `GateConfig.enable_failure_learning`，仅 variant_2 启用；baseline_0/baseline_1/variant_1 保持现有策略语义且不启用 failure learning。controller 接线已在 I3 完成；inspect/replay/metrics 完整接线已在 I4 完成。
- [x] **Packer `avoided_attempts` block**：I2 已完成 runtime `NegativeEvidence` DTO、共享 `retrieval/negative_evidence.py` builder（safe raw、unsafe sanitized、二次 redaction、source-state 去重、`max_blocks` 截断、固定模板）与 packer `avoided_attempts` 渲染。排序在 `project_memory`/`project_constraints` 之后、`tool_evidence` 之前（正向约束先定方向），ordinary（可被预算丢弃）。非危险失败保留原文（经二次 redaction）+ must-not-execute 框；destructive/secret/tool_sensitive/production-env 原始 memory hard reject，仅由共享 builder 生成不含原命令/参数/路径的固定模板安全提示（gate 不网开一面）。inspect/replay 三路径重建已在 I4 完成。
- [x] **Controller 主路径接线**：I3 已完成 hot path 调用共享 builder、`pack_context(negative_evidence=...)`、accepted/rejected/degraded 计数闭合、`context_packing.metadata` 记录 `degraded_count` / `hard_rejected_count` / retained `negative_evidence_count` / retained `sanitized_negative_evidence_count` / built+dropped negative evidence 计数，并输出 safe negative evidence 与 sanitized notice 两类 warning。demo/benchmark evaluator 已把 `avoided_attempts` 排除在正向污染/action 判定之外，case_1..case_9 acceptance 保持通过。I3 review 已修复 replay `_ACCEPTED_DECISIONS` 兼容问题和预算 drop 误报 injected 的 profile/warning 问题，复审未发现 P0/P1/P2 缺陷。
- [x] **Inspect / Replay / Observability 接线**：I4 已完成 `inspect_access` 与 replay original-view 通过共享 builder 重建 `avoided_attempts`，degrade 不再进入正向 accepted memory；replay 对缺失 source memory 只输出 warning、不恢复 raw failed text，并将 `reject(sanitized)→accept/degrade`、`degrade→accept` 判为 critical；observability summary/report/dashboard 模型新增 `degraded_negative_evidence_count` / `sanitized_failure_notice_count` / `negative_evidence_block_count`，degrade 不计入正向 failed-branch injection。
- [x] **Benchmark `case_10`（safe failure learning）+ `case_11`（sanitized destructive）**：I5 已完成。关键 evaluator 正/负向块显式分区（`contaminated`/action 只看正向区，negative_lesson/unsafe_negative_leakage 只看负向区）；runs 36→44；新增 acceptance `variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`，benchmark `acceptance.passed=true`（10/10 checks）。
- [x] **文档 / 项目记忆同步**：I6 已完成。`ROADMAP`、`CONTEXT_COMPACTION_PLAN`、Failure-aware 计划和 `.ai` project memory 已统一标记 I1-I6 完成；后续 Phase 3.5 SDK/LangGraph adapter/CLI（§6）、6-strategy benchmark expansion / eval-table persistence（§7）、ROADMAP §13 Security & Consistency Hardening H1-H18、以及 §10/§11 Provider Registry / Key Ontology 均已完成。
- [x] **I7 compaction-negative retained facts**：I7.1-I7.6 已完成。Dropped standard `avoided_attempts` blocks now retain safe `RetainedNegativeEvidence` metadata in compaction logs without entering positive `retained_facts` or prompt context; replay/metrics/reports/trace bundle/dashboard/benchmark all surface the metadata separately and redacted. Benchmark now includes `case_13_compaction_retains_negative_lesson`; reproducibility acceptance is `13/13`.
- [ ] **后续候选（本节衍生）**：stale → 「过时警告」降级（首批不做，避免破坏 case_9 `variant_2_excludes_stale_memory`）。
- **贯穿约束**：负向通道在 gate 之后从既有 candidate 派生，不新增检索入口、不绕过 §1 的 `_RETRIEVABLE_STATUSES` 生命周期过滤；I7 触碰 compaction 路径时须重申该约束。

---

## 10. Provider Registry（统一外部能力抽象）

当前已有真实 `LLMExtractionProvider`；后续 embedding / summarizer / LLM-judge 都会引入外部模型，且与「benchmark 可复现」「LLM key 不稳定」存在张力。建议抽象一个统一的 provider 注册层，**一处解决「确定性 default ↔ 真实模型 ↔ 可复现」的冲突**：

- [x] **Provider 抽象族**：`LLMExtractionProvider`（已有）、`EmbeddingProvider`、`SummarizerProvider`、`JudgeProvider`，统一约定：deterministic fallback + config-gate 启用真实实现 + 失败降级（沿用 extraction 管线已验证的模式）。**完成（2026-06-13）：新增轻量 `app.providers` registry/base、deterministic/OpenAI-compatible embedding provider、contract-only no-op judge、settings-based `providers/factory.py`、FastAPI DI/runtime registry 注入；`MemoryRuntime._prepare_embedding(...)` 与 `RetrievalController._embed_query(...)` 已接入 embedding provider，并在 provider 失败、非 256 维、NaN/inf 时降级到 deterministic `stable_embedding(...)`；settings-derived embedding providers 固定使用 256-dim pgvector contract（即使 `MEMTRACE_EMBEDDING_DIM` 被误配为其他值）；repository-level `ensure_embedding(...)` backfill 保留；benchmark runtime 现在显式传入 `deterministic_provider_registry()`，不受真实 provider 环境变量影响。**
- [x] **Provider capability metadata**：声明各 provider 是否确定性、是否需要网络、支持的端点类型，benchmark 据此自动选确定性路径以保可复现。**完成（2026-06-13）：`ProviderCapabilities.snapshot()` 已提供稳定、递归冻结、脱敏的 capability snapshot；retrieval-policy-v2 已纳入 retrieval-relevant `embedding`/`summarizer` snapshots 并排除 `judge`，显式 provider override（包括 `summarizer_provider=`）会反映实际 provider；replay policy drift 通过 public `RetrievalController.provider_snapshot` 与 hot-path retrieval 同源重建 hash；P8 conformance 覆盖 policy snapshot 非 secret、仅 retrieval-relevant provider、benchmark env isolation。**
- [x] 关联：§0 真实 embedding 决策、§1 LLM key 风险、§9 可配置 summarizer 都落到这一层。**§10 Provider Registry 当前计划项已完成并通过 P10 full regression / benchmark / reproduce closeout；最终复审补齐 summarizer real/degraded factory wiring 测试；真实 LLM judge 行为、storage-backed ontology 管理和更大治理继续留在后续 roadmap。**

## 11. Controlled Memory Key Ontology（受控记忆 key 本体）

§1 已记录「LLM key 不稳定破坏冲突解析」。当前缓解手段是系统提示里的 key 词表，建议升级为正式的 **key schema registry**（比「语义去重」更早、更实用、更可控）：

- [x] **受控 key 本体表**：如 `project.runtime` / `project.package_manager` / `project.test_command` / `project.database` / `tool.command.failed` / `endpoint.current` / `endpoint.deprecated` / `user.preference.*`，定义单值/多值语义与 supersede 规则。**进展（2026-06-13）：P5 已完成 `app.memory.key_ontology`，提供 canonical specs、alias、single/multi cardinality、默认 `MemoryType`/`MemoryScope`、安全 free-form 校验、wildcard 默认继承与稳定 LLM prompt rendering；最终复审已补齐 canonical schema 完整性测试，并锁定 `tool.command.failed` 存在但不可由 LLM 抽取。**
- [x] **抽取侧校验/归一**：LLM 候选的 key 必须映射到本体（或显式标记为 free-form），不在本体内的同义概念归一到规范 key，根治 key 漂移。**进展（2026-06-13）：P7 已完成；`ExtractionCandidate.free_form`、ontology-rendered `_SYSTEM_PROMPT`、`build_results(...)` alias canonicalization、unknown non-free-form drop、unsafe free-form reject、controlled/free-form 默认 type/scope override 均已覆盖。**
- [x] **本体作为单一真相源**：当前单值语义分散在三处（`writer` supersede、`resolver._SINGLE_VALUED_KEYS`、`llm_extractor._SYSTEM_PROMPT`），靠人工保持同步。2026-06-13 审查已发现 `resolver._SINGLE_VALUED_KEYS` 落后于 LLM 受控 key 契约并临时补齐（见 §1.1）；本体落地后应让三处都从同一注册表派生，消除漂移根因。**进展（2026-06-13）：P6 已迁移 writer runtime constants、resolver single-valued semantics、runtime active-memory identity 与 supersede matching 到 ontology；历史 alias（如 `project.pkg_manager`）会与 canonical `project.package_manager` 共享冲突/替换语义；最终复审修复 package-manager correction 上下文（如 `npm -> bun`）误写 `project.runtime` 的边界。**
- [x] 关联：§1 LLM key 风险、resolver 冲突解析、§10 ExtractionProvider。**§11 当前 code-defined ontology slice 已完成并通过 final affected suite / full regression / reproducibility closeout；后续若需要 hosted/admin 可编辑 ontology，应作为 storage-backed governance/administration 独立设计，不属于本轮。**

## 12. Documentation & Showcase（展示资产）

系统内核已强，但缺「可被他人理解/复现/接入」的展示层——这是当前观感性价比最高的补强之一：

- [x] **README 架构图 + Quickstart**：已添加顶层 `README.md`，包含 Mermaid 架构图、deterministic Quickstart、PostgreSQL/API 可选路径、报告说明和关键 API。可复现入口为 `./scripts/reproduce.sh`；core compose 仍由现有 `docker-compose.yml` 提供 pgvector PostgreSQL 基线。
- [x] **Demo GIF / 截图** + `demo_report` / `benchmark_report` / `llm_bench_report` 示例产物：本轮不提交二进制 GIF/截图，改为可再生成展示产物；`./scripts/reproduce.sh` 生成 `demo_report`、`benchmark_report`、`observability_report`，README 记录可选 real-LLM bench 生成 `llm_bench_report`。
- [x] **技术博客**：`docs/blog/why-agent-memory-is-not-just-rag.md` 已添加，讲 failed-branch isolation / workspace isolation / stale rejection / tool safety / state-aware retrieval / replay observability。

---

## 13. 安全与一致性加固（Security & Consistency Hardening）★ 2026-06-13 审查产出

源自一次覆盖六大模块的全量代码审查（详细清单见 §1.1）。这些不是新功能，而是把现有承诺（脱敏纵深、后端等价、确定性、数据一致）补全到生产级。**H1-H18 已完成并通过最终回归；历史上 H1-H18 完成后主线回到 §10/§11 Provider Registry / Controlled Memory Key Ontology，且 §10/§11、Phase 4、Integrations、R1、OTel/OpenInference exporter core slice 均已完成。**

### 13.1 安全闭环（优先）
- [x] **正向打包路径脱敏**：H1 已完成；packer 对 prompt context 渲染前的正向块统一 `redact()`，与负向证据路径形成对称纵深防御；复审后已明确带 secret/destructive/tool-sensitive 标记的 memory 即使在 ablation 策略也直接 gate reject。
- [x] **`variant_1` gate 收敛**：H2 已完成；仅 relaxed failed/rolled_back hard rejection，保留 hard/risk safety policy，并新增 quarantined / secret / destructive / tool-sensitive 非绕过安全底线。
- [x] **鉴权去装饰化**：H3 已完成；对齐 ADR-016 增加默认关闭的轻量 token 校验依赖，SDK/CLI bearer token 在启用时生效。

### 13.2 一致性 / 并发
- [x] **`next_sequence_no` 原子化**：H5 已完成；runtime 通过 `Repository.append_event(...)` 原子追加事件，SQL 在同一事务内持有 namespaced advisory lock、分配 `sequence_no` 并插入；ORM/迁移约束名已对齐初始迁移已有的 `uq_event_run_seq`，`0006_security_consistency_hardening` 作为 hardening 边界不重复创建同列唯一约束。
- [x] **检索超时路径统一**：H6 已完成；prelude / non-prelude timeout 都落同一 minimal access 形态，timeout 只包裹 trace 构造，成功 trace 的日志持久化与 `access_count` mutation 在 timeout 窗口外执行，消除 split-brain。
- [x] **后端 isomorphism 补全**：H4 已完成；`StateTreeError` 映射为 HTTP 400 / SDK `BadRequestError`，`replay_access` missing-run 检查下沉到 `MemoryRuntime` 并在 HTTP/in-process SDK 中统一为 NotFound。
- [x] **gate log 确定性排序**：H7 已完成；`list_gate_logs` 在 InMemory/SQL 均按 `(created_at, gate_id)` 排序，hot-path 与 replay accepted context 重建统一用 `(-final_score, memory_id)` tie-break，消除虚假 order-changed diff 与 InMemory/SQL 行为差异。
- [x] **ORM/迁移索引对齐**：H8 已完成；ORM 显式声明 `ix_context_compaction_logs_workspace_created(workspace_id, created_at)` 并移除 workspace 单列 index，使 `create_all` metadata 与 `0005_context_compaction` migration 对齐。

### 13.3 精度 / 健壮性
- [x] **token 估算独立化**：H11 已完成；不复用剔停用词的检索分词器，改用独立 regex 预算估算，保留 stopwords、CJK/no-space 单元和结构化 `key=value` 事实，并让 `_truncate_text` 在双语场景预算闭合。
- [x] **summarizer LLM provenance 校验放宽**：H12 已完成；用 `must_retain_facts` 自身 provenance 播种 allow-set，避免合法 LLM 输出被恒判 invented，同时保留 top-level source id 精确保留与 invented provenance 拒绝。
- [x] **状态机边界**：H13 已完成；`apply_finish` 处理 `rolled_back`，`finish_step` / rollback 缺失 state node 或 `state_node_id=None` 时显式抛 `StateTreeError`，且校验发生在 step 写入或 buffered flush 等副作用前，并复用 H4 的后端等价错误映射。
- [x] **benchmark 公平性快照整体化**：H14 已完成；对受测 workspace 做整体 memory 快照/恢复（而非仅 `access_count`），并在策略检索期间出现新 memory 时失败，防止 §3.2 Reflection 调度器落地后公平性静默失效。
- [ ] **其余 Low 项**：见 §1.1 末条。**2026-06-30 closeout 已复核**：`tool_sensitive_present` 误判、`last_accessed_at` 死字段、报告路径 TOCTOU、naive datetime 健壮性、episodic risk 屏蔽均已修复/确认修复；仅 read-modify-write 竞态（in-memory dev/test）与 CLI/evaluator 判定重复（受 SDK↔apps/api 包边界限制）作为低价值后续 cleanup 保留。

### 13.4 横切运行时保障（Cross-cutting Runtime Hardening）

外部审查（2026-06-13）补充的横切层：不是新核心机制，而是让 mem-trace 像一个严肃的「trace-first / replayable」Agent Memory Runtime。已核对源码现状，标注真缺口 vs 已部分存在需聚合。其中 **Policy Contract + Conformance Suite 价值最高**，与本轮 replay/repeatability/一致性加固最契合，应优先于 §10/§11。

- [x] **(A) Retrieval Policy Contract / policy snapshot ★最高价值**：H9 已完成；`MemoryAccessLog` 持久化 `policy_version` / `policy_hash` / `policy_snapshot`，snapshot 覆盖 strategy、top_k、effective token budget、GateConfig、vector/include_all/lifecycle filter、packer reserve、provider determinism 路径；成功与 timeout access 均落快照；replay 对老 access 报 `policy_snapshot_missing`，对 hash 不一致报 `policy_drift`，从而区分 data drift 与 policy/code/config drift。
- [x] **(B) Runtime Invariant & Conformance Suite ★最高价值**：H10 已完成并经复审加固；`apps/api/tests/conformance/` 聚合 strategy conformance（六策略 × workspace/lifecycle/secret/quarantine/destructive/tool-sensitive safety-floor，含非 baseline 正向对照与 candidate/gate 排除断言）、backend conformance（in-process/HTTP shared-runtime cross read-write 与 sequence monotonicity）、replay conformance（不新增 access/gate/profile/compaction rows、不 bump memory）。后续 Provider/Ontology/Scheduler/MCP 等新入口应继续纳入此套件。
- [x] **(C) Trace Bundle / Debug Export**：H16 已完成；新增 `TraceBundle(trace-bundle-v1)` / `TraceBundleValidation`、`MemoryRuntime.export_trace_bundle(...)` / `export_access_bundle(...)` / validation-only schema check，默认 redacted，覆盖 run/steps/events/state-tree/memories/access/gate/profile/compaction logs，保留 ids/policy snapshot 字段但不实现 production write-import。
- [x] **(D) Schema Compatibility & Migration Policy**：H15 已完成；`test_migrations.py` 现在机器校验所有 Alembic version 文件的 revision/down_revision/upgrade/downgrade 声明，新增非空列必须带 server default 或 backfill，并提供 `MEMTRACE_TEST_DATABASE_URL` 保护的可选 PostgreSQL `alembic upgrade head` smoke。
- [x] **(E) Dogfood Agent Scenarios**：H17 已完成；`examples/dogfood/` 增加 coding-agent recovery（failed npm → recover bun → variant_2 避免重复）、multi-session project constraint carryover、destructive failure sanitized 三个 no-network deterministic harness，并由 SDK example smoke tests 固化。

**H11/H12/H14 post-review closeout (2026-06-13):** H11 policy snapshots now include the token-estimator version and truncation coverage includes ASCII/mixed CJK boundaries; H12 no longer widens top-level memory source ids from fact-local `source_memory_id`, rejects spaced invented summary facts, and validates rule fallback through the same path as LLM output; H14 also rejects snapshot memories that disappear or move out of the benchmark workspace. Review follow-ups additionally redacted compacted retained-fact keys and made auth malformed/non-ASCII credential handling fail closed.

---

## 附：推荐推进顺序（建议）

> 原则：先补「展示/可观测/可复现」与「贴合定位的 compaction」，把「重型基建/高级存储/生态入口」后置并设触发条件，**严防范围膨胀**。下列顺序覆盖 §1–§13 的全部待办；§8 为明确不做、不参与排期。

1. ~~**清立即决策**（§0）~~ ✅ **已完成 (2026-06-10)**：embedding 保留确定性 default + 真实作可选 provider（ADR-015）；auth 走轻量 Hosted-Demo Safety Mode（ADR-016）；secret 默认不存原文（ADR-017）。
2. ~~**Phase 3-A 后端可观测性**（§2）~~ ✅ **已完成 (2026-06-10)**：Retrieval Replay + eval 表 + Quality/Safety profiler + 最小 JSON/MD/HTML 报告，Issues 1-8 全部完成并端到端验证。
3. ~~**展示资产 + 可复现基线**（§12 + §7 部分）~~ ✅ **已完成 (2026-06-10)**：README + Mermaid 架构图 + deterministic Quickstart + `scripts/reproduce.sh` / `scripts/smoke.sh` + demo/benchmark/observability 可再生成报告 + optional LLM bench 指引 + 技术博客 + integration reproducibility tests。
4. ~~**Context Compaction**（§9 + §5/§10 协同子集）~~ ✅ **核心闭环已完成 (2026-06-11)**：C0-C5 完成 packer 超预算补偿、durable compaction log、observability/replay、SummarizerProvider、rolling history summary、压缩质量 benchmark/report/replay 同步；剩余协同项为 §5「completed subgoal → summary node」与 §10 Provider 抽象族。
5. ~~**Failure-aware Negative Memory Injection**（§9.1）~~ ✅ **I1-I7 已完成 (2026-06-14)**：I1 gate 三路 `accept/degrade/reject`、I2 `NegativeEvidence` DTO + shared builder + packer `avoided_attempts`、I3 controller hot-path wiring、I4 replay/metrics/inspect sync、I5 benchmark/evaluator 扩展、I6 文档/项目记忆同步、I7 compaction-negative retained metadata 均已完成。benchmark 已含 `case_10` safe failure learning、`case_11` sanitized destructive failure、`case_13_compaction_retains_negative_lesson`，acceptance 包含 `variant_2_retains_negative_lesson_under_compaction`，当前 reproducibility 为 13/13。
6. ~~**Phase 3.5 SDK / Adapter / CLI**（§6 前段）~~ ✅ **已完成 (2026-06-12)**：Python SDK + in-process/HTTP backends + LangGraph Adapter + custom-loop / LangGraph 示例 + CLI 入口 + README 三入口说明 + S6 项目记忆同步均已完成，证明「可插拔 runtime」。S6 复审还修复了 `flush_session` 对含 `/` 的 arbitrary `session_id` 的 HTTP/in-process 等价性缺口。历史上此时 TS SDK / OTel / MCP / IDE 插件仍后置；截至当前，INT-A TypeScript SDK、INT-B MCP Server、INT-C MCP config templates 与 OTel/OpenInference exporter core slice 均已完成，仅专用 IDE 扩展仍需 MCP adoption feedback 触发。
7. ~~**完整 6 策略对比 + benchmark 落库**（§7 主线）~~ ✅ **已完成 (2026-06-12)**：6 策略（含 `long_context` / `variant_3` reflection-lite）逐层量化；新增 `case_12_reflection_retention` 与 acceptance `variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat`；benchmark 现额外落 `eval_*` 表，并已加固同一 repo 重复落库运行的 workspace 隔离；Task 11 已完成 full regression / reproducibility / report-shape / project-memory sync；I7 后当前全局 benchmark/reproducibility acceptance 为 13/13。P4-B 已让 `variant_3` 在存在 scheduler `MemoryRetentionSignal` 时使用持久化 `reflection_priority`，默认 benchmark/reproduce 仍保留 deterministic fallback 以保持稳定。原先的 §10/§11 Provider Registry / Key Ontology 候选已被 §13 安全与一致性加固（ADR-020）前置。
8. ~~**安全与一致性加固**（§13；源自 2026-06-13 全量审查 §1.1 + 外部审查横切补充）~~ ✅ **已完成 (2026-06-13)**。分四批，**完整覆盖 §13.1/§13.2/§13.3/§13.4**：
   - ~~**8a 安全闭环（§13.1，最优先）**~~ ✅ **已完成 (2026-06-13)**：H1 正向打包脱敏 + H2 `variant_1` gate 收敛 + H3 默认关闭轻量鉴权。
   - ~~**8b 一致性/并发（§13.2）**~~ ✅ **已完成 (2026-06-13)**：H4 后端 isomorphism、H5 `next_sequence_no` 原子化、H6 检索超时 split-brain、H7 gate log 确定性排序、H8 ORM/迁移 compaction 索引对齐均已完成。
   - ~~**8c 横切运行时保障 High（§13.4-A/B，★最高价值）**~~ ✅ **已完成 (2026-06-13)**：Retrieval Policy Contract / policy snapshot + Runtime Invariant & Conformance Suite 已完成，replay 现可区分 data drift vs policy drift，并把 lifecycle/workspace/secret/isomorphism 不变量聚成机器校验套件。
   - ~~**8d 精度/健壮性 + 其余横切（§13.3 + §13.4-C/D/E）**~~ ✅ **已完成 (2026-06-13)**：状态机边界 H13、token 估算独立化 H11、summarizer provenance 验证 H12、benchmark 公平性快照整体化 H14、H15 migration policy、H16 redacted trace bundle、H17 dogfood harness、H18 docs/project-memory closeout 均已完成并验证。§1.1 末条 Low 项保留为后续 opportunistic cleanup，不阻塞 §10/§11。
9. ~~**Provider Registry + Key Ontology**（§10 + §11）~~ ✅ **已完成 (2026-06-13)**：统一 `LLMExtractionProvider/EmbeddingProvider/SummarizerProvider/JudgeProvider` 抽象族 + capability metadata（承接 §0 embedding 决策、§9 summarizer）；受控记忆 key 本体表 + 抽取侧归一（根治 §1 LLM key 漂移，并消除 §11「本体作为单一真相源」记录的三处单值语义漂移）；benchmark deterministic provider isolation + provider snapshot conformance + P10 closeout + final review hardening（fixed 256-dim provider boundary、`npm -> bun` correction、ontology schema coverage、summarizer factory wiring）均已完成。
10. **Phase 4 async/lifecycle/governance**：`docs/design/PHASE4_PLATFORM_PLAN.md` 的 P4-A1-P4-A5、P4-B1-P4-B4、P4-C1-P4-C2、P4-D1-P4-D4 已完成并完成 full regression 验证。P4-A 覆盖 async settings/contracts、Celery/Redis/idempotency、candidate buffer、写入模式矩阵、async enqueue fallback、dev compose；P4-B 覆盖 lifecycle policy/audit、retention signal storage、访问时间戳、scheduler 函数、maintenance wrapper、`variant_3` scheduler signal source、benchmark/replay closeout；P4-C 覆盖 redacted `memory_versions`、semantic-change versioning、ontology-backed `memory_conflicts`、read-only versions/conflicts API 与 dashboard table surfacing；P4-D 覆盖 default-off API key/workspace authorization、quota service、redaction state machine/raw-payload guard、docs/project-memory closeout。2026-06-14 full Phase 4 review 继续加固了 event extraction 幂等、workspace mismatch 无副作用、lifecycle stale update 防护、secret digest HMAC/omit、replay retained-negative redaction、dashboard version parity 与 SDK Phase 4 读 API。Phase 4 剩余项主要是远期 admin/manual conflict review、完整 JWT/membership 与 production distributed quota override；integrations INT-A TypeScript SDK、INT-B MCP Server、INT-C MCP config templates / IDE thin-layer decision 均已完成。
11. ~~**R1 Release Readiness / Public Adoption**~~ ✅ **已完成 (2026-06-14)**：`docs/design/RELEASE_READINESS_PLAN.md` 已完成。command inventory、README public landing page、getting-started/concepts/MCP/benchmark/deployment/release-checklist 用户与维护者文档、canonical release-readiness smoke、TypeScript package metadata/package-shape checks、Python package metadata/CLI readiness、GitHub Actions verification matrix、Python/JS verification rerun、tracked-file/public-doc release hygiene、benchmark/reproduce closeout、ROADMAP/`.ai` sync 均已完成；默认 quickstart 只列 no-network 命令为无条件路径，HTTP/TS/MCP/Redis/LLM 路径均标明前置条件或 env-gated。R1 closeout 验证：`uv run python -m app.benchmark.runner --output-dir reports` 生成 13 个 acceptance check 且全部为 true；`bash scripts/reproduce.sh` 打印 `acceptance.passed=true (13/13 checks true)`；`bash scripts/check-release-hygiene.sh` 打印 `release hygiene checks passed`。R1 后推荐的 OpenTelemetry/OpenInference exporter 已完成 core slice closeout；除非 adoption feedback 重新排序，后续可从 Phase 3-B dashboard、maintenance scheduler/admin workflow、advanced retrieval/storage 等候选中重新选择。
12. ~~**Phase 3-B Showcase Dashboard**（§2，选定 2026-06-17）~~ ✅ **已完成 (2026-06-20)**：`apps/web` React/TS dashboard 已完成 WEB-A/WEB-B scaffold/data boundary，WEB-C visual system，WEB-D Overview/run gallery，WEB-E Run Explorer，WEB-F Access Replay / Memory Flow，WEB-G Benchmark Lab，WEB-H Memory Atlas / Ops Read-Only，WEB-I fixture-backed Showcase / screenshot workflow，WEB-J testing/docs/project-memory closeout。`/v1/dashboard/ui` 仍保持轻量静态查看器；dashboard 仍为 read-only frontend over `/v1`，没有新增 runtime/gate/retrieval/admin mutation 语义。
13. **Phase 5 高级存储**（§4）：ES/Neo4j 混合检索 + 图谱 provenance + 多路融合 + Query Planner + 多跳检索，**仅在触发条件满足时启动**。
14. **远期 / scale-only**：§5 状态树其余能力（subgoal 自动推断 / 完整 node_type / MAGE 四操作）、§6 专用 IDE 扩展 / Go-Rust 组件、§7 小规模 LoCoMo/MemoryArena。TS SDK、MCP Server、MCP config templates 与 OTel/OpenInference exporter core slice 均已完成；专用 IDE 扩展仍需 MCP adoption 反馈作为触发条件。其余远期项**均设触发条件，不主动排期。**

> **贯穿性约束（非排期项，但每一步都要遵守，来自 §1）**：① 任何新检索路径必须重新应用生命周期过滤（`_RETRIEVABLE_STATUSES`），否则泄漏退役记忆；② 切 pg16 镜像需 `docker-compose down -v`（破坏性，运维注意）；③ profiler 亚毫秒阶段读 0ms 属预期非 bug。
