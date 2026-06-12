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

一次覆盖 runtime / retrieval / memory / observability / storage / SDK 六大模块的逐行审查。下列**已修复**项已在本次提交内含测试与回归（308 passed，benchmark 12/12）：

- [x] **secrets 脱敏覆盖面过窄**：新增 JWT / PEM 私钥块 / Slack `xox*` / Google `AIza*` / 自然语「password is X」模式。因为整个抽取分支由 `contains_secret` 把关，漏检即等于密钥落库且进入可检索记忆。出处：`memory/secrets.py`。
- [x] **writer 否定短语产生矛盾记忆**：`"should not use X"` / `"不想用 X"` 会同时命中 positive 与 negative 规则，产出自相矛盾的 `project.runtime=X` + `project.runtime.excluded=X`。已加后置去矛盾过滤（被排除的 runtime 不得作为正向约束）。出处：`memory/writer.py`。
- [x] **resolver 单值 key 集合落后于 LLM 受控 key 契约**：`_SINGLE_VALUED_KEYS` 仅含 `project.runtime`，而 LLM 系统提示已约定 language/database/test_framework/formatting/package_manager 等单值概念。已扩展该集合，使后到的冲突值即使没有 `supersede=true` 也能被正确 supersede。出处：`memory/resolver.py`。
- [x] **observability 报告 degrade 计入「已接受」**：`reports.py:_accepted_memories` 把 `degrade` 当成 accepted，与 `metrics.py`/`replay.py` 的权威 `{accept,warn}` 定义冲突，导致 per-access 行指标与 summary 聚合自相矛盾。已对齐为 `{accept,warn}`。出处：`observability/reports.py`。

下列为**已确认但未在本次修复**（需更大设计决策或触及确定性 benchmark/并发模型，单列为后续待办）：

- [ ] **[High] 正向打包路径无脱敏纵深防御**：`packer.py` 直接使用 `mem.content`，不做 `redact()`；而 `baseline_1` / `long_context` / `variant_1` 关闭 gate 后，一旦存在 secret/risk 记忆其**原文会进入正向上下文**。负向证据路径已有完善脱敏，正向路径缺失对称防护。建议：packer 对正向块统一过 `redact()`，或在候选选择阶段按 `sensitivity==secret`/`contains_secret` 兜底过滤。出处：`retrieval/packer.py` / `retrieval/controller.py`。
- [ ] **[High] `variant_1` 为「失败分支降权」过度关闭整条 hard/risk policy**：失败分支放行实际由 `allow_failed_branch`/`allow_rolled_back` 单独控制，无需关闭 `enable_hard_policy`/`enable_risk_policy`。当前实现连带放过 secret/destructive/quarantined。建议改为仅置 allow 标志，保留硬/风险兜底。出处：`retrieval/gate.py:62-70`。
- [ ] **[High] in-process 与 HTTP 后端 isomorphism 仍有缺口**：`StateTreeError` 未被任一后端/路由映射 —— in-process 抛裸内部异常、HTTP 退化为 500→泛化 `MemTraceError`；`replay_access` 的 run-existence 检查只在 HTTP 侧。建议把 `StateTreeError` 在 runtime 层映射为客户端可纠正错误（400/`BadRequestError`），并把 run 存在性检查下沉到 `MemoryRuntime`。出处：`packages/python-sdk/.../backends.py` / `api/routes.py` / `runtime/memory_runtime.py`。
- [ ] **[High] 并发下 `next_sequence_no` 可能重复**：advisory 锁的事务在 `SELECT max+1` 后即 commit，event 插入在另一事务，锁未覆盖插入 → 并发同 run 可拿到重复 `sequence_no`，破坏事件定序。建议在同一加锁事务内完成分配+插入，或用 `UPDATE ... RETURNING` 计数行。出处：`storage/sql_repository.py:449-464`。
- [ ] **[High] 检索超时路径 split-brain**：非 prelude 超时分支只 new 一个 `access_id` 不落库（与 prelude 分支不一致），且 `wait_for` 取消可能已部分持久化另一 id 的日志、`_bump_access_counts` 未执行。建议两条超时分支都落库同一 access，并把 `_persist_trace`+计数纳入抗取消单元。出处：`retrieval/controller.py:119-170`。
- [ ] **[Medium] token 估算复用剔停用词的 `tokenize`**：`estimate_tokens` 复用检索分词器会系统性低估 token（停用词/CJK），使预算闭合在双语场景不可靠；叠加 `_truncate_text` 对无空格 CJK 无法截断，受保护块仍可能超预算。建议独立、不剔停用词、CJK 感知的计数与截断。出处：`retrieval/packer.py:32-34,106-125` / `retrieval/similarity.py`。
- [ ] **[Medium] 服务端无鉴权但 SDK/CLI 发送 Bearer**：鉴权是装饰性的，任何可达 `/v1` 的对端可读写全部 workspace。需对齐 ADR-016 Hosted-Demo Safety Mode：要么实现 token 校验，要么文档明确「当前无鉴权，api_key 仅预留」。出处：`api/routes.py`/`deps.py` 无 auth 依赖。
- [ ] **[Medium] benchmark 公平性恢复仅覆盖 `access_count`**：依赖「retrieval 只改 access_count」的隐式不变量。一旦 §3.2 Reflection 调度器开始更新 freshness/updated_at/trust，公平性会静默失效。建议改为对受测 workspace 做整体 memory 快照/恢复，或恢复后断言无其他字段差异。出处：`benchmark/runner.py:128-152`。
- [ ] **[Medium] LLM provider 每次调用新建 `AsyncClient`**：无连接复用，高频抽取下端口/性能压力。建议 provider 持有长生命周期 client，app shutdown 时 `aclose`。出处：`memory/llm_extractor.py:176-182` / `api/deps.py`。
- [ ] **[Medium] ORM 与迁移在 `context_compaction_logs` 索引上漂移**：ORM 声明单列 `workspace_id` 索引，迁移 0005 建的是复合 `(workspace_id, created_at)`，导致 `create_all` 与迁移 schema 不一致、autogenerate 噪音。建议二者对齐。出处：`storage/orm.py:228` / `migrations/0005`。
- [ ] **[Medium] gate log 排序非确定性**：`list_gate_logs` 仅 `ORDER BY created_at`，同访问多条时间戳可能相同 → SQL 顺序未定义、与 InMemory 不一致，replay 产生虚假 order-changed diff。建议加次级排序键（`created_at, gate_id`）并在 replay accepted 排序加确定性 tiebreak。出处：`storage/sql_repository.py:585` / `observability/replay.py`。
- [ ] **[Medium] summarizer LLM 路径 provenance 校验可能恒失败**：`_validate_source_ids` 未把 `must_retain_facts` 自身 provenance 纳入 allow-set，导致合法 LLM 输出被判「invented」恒回退 rule provider，使 LLM seam 形同虚设。建议先用 `must_retain_facts` 的 provenance 播种 allow-set。出处：`memory/summarizer_provider.py:271-304`。
- [ ] **[Medium] 多处状态机/隔离边界小缺陷**：`state_tree.apply_finish` 忽略 `rolled_back` 状态（节点滞留 active 可能泄漏到 active path）；`finish_step` 节点缺失时返回幽灵未持久化 `StateNode`；rollback 退化分支翻转记忆却报告 0 个 rolled-back 节点。建议统一为 `StateTreeError` 或正确映射状态。出处：`runtime/state_tree.py:91-100` / `runtime/memory_runtime.py:312-371`。
- [ ] **[Medium] 负向证据（avoided_attempts）非受保护块**：预算紧张时「请勿重复某危险操作」的安全提示可能被丢弃。建议将 `sanitized_risk_notice` 模式负向证据纳入受保护集合或提高保留优先级。出处：`retrieval/packer.py:145-146`。
- [ ] **[Low] 其余**：`access_count`/`raw_event_ids` 的 read-modify-write 竞态、`last_accessed_at` 从未写入（`retention_score` 的 recency 信号为死字段）、summarizer episodic 内容未过 risk/secret 屏蔽、CLI 与 evaluator 判定逻辑重复、报告路径 TOCTOU、`stale_injected` 对 naive datetime 不健壮、`tool_sensitive_present` 子串启发式可能误判。详见审查记录。

> **修复优先级建议**：正向脱敏 + variant_1 gate（安全闭环）≈ isomorphism/StateTreeError ＞ sequence_no 并发 + 超时 split-brain（数据一致性）＞ token 预算精度 ＞ 鉴权 ＞ 其余。安全相关的两条（正向脱敏、variant_1）与一致性两条建议优先排期。

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
- [ ] **React + TS 前端 Dashboard (`apps/web`)**：架构目录已规划，代码库无实现。
  - [ ] Run Trace Timeline
  - [ ] **State Tree Viewer**（active path / failed branch / 压缩 subgoal 可视化）
  - [ ] Gate Analysis Panel
  - [ ] **Memory Flow Sankey 图**（候选→gate→context→answer）—— 好看但排最后。
  - [ ] Cost Breakdown / Replay Panel

---

## 3. Phase 4 — 异步基础设施 + 记忆生命周期（依赖链核心）

architecture §6.8 / §12 / §14 Phase 4、draft §8。**大量 Cold Path 能力共同依赖 Celery+Redis，应作为前置基建优先。**

### 3.1 异步基础设施
- [ ] **Celery 异步任务队列** + **多队列拆分**（`memory_queue / maintenance_queue / eval_queue`）。
- [ ] **Redis**：broker + 热点缓存 + 幂等锁 + active session key。
- [ ] **Redis-backed candidate buffer + idle flush**（替换当前进程内 buffer）。
- [ ] **完整写入模式矩阵**：`async / sync_flush / lazy / no_extract`（§12.1）+ LLM extraction 失败 async retry（§12.2）。

### 3.2 Reflection / Forgetting 调度器（★ 高价值，基本未实现）
- [ ] **多维评分模型**：`value_score / freshness_score / trust_score / risk_score`，按 memory_type 的 tau 衰减表。出处：draft §8 / architecture §6.8。
- [ ] **决策分数分离**：`retrieval_score / retention_score / reflection_priority`。
- [ ] **真实 Reflection 取代 reflection-lite**：§7 6 策略对比中的 `variant_3` 目前使用确定性 reflection-lite（`retention_score = 0.4*trust + 0.3*freshness + 0.3*min(1, access_count/10)`，仅对 accepted 记忆重排，见 `apps/api/app/retrieval/controller.py`）。它是占位实现，本调度器落地后应以真实 `retention_score / reflection_priority` 取代之，并让 `case_12_reflection_retention` 改由真实衰减/反思信号驱动。
- [ ] **完整生命周期状态机**：`active→dormant→archived→deleted` + 旁路状态 `pinned/superseded/conflicted/quarantined` 全套转移。
- [ ] **10 个定时任务**：summarize_completed_runs(✅已有同步版)、extract_procedural_memory(✅)、dedup_memory、conflict_scan、score_memory、decay_memory、archive_memory、quarantine_memory、profile_refresh、reindex_memory。
- [ ] **审计日志**：scheduler 每次状态变更记录 audit log。

### 3.3 冲突 / 版本管理（在 P2 基础版上补全）
- [ ] **`memory_versions` 表 + Version Manager**：完整版本审计链。
- [ ] **`memory_conflicts` 表 + conflict_scan 后台任务**：同 subject+predicate 不同 object 标记。
- [ ] **7 条完整冲突规则**（时间覆盖、tool result 优先、provenance 解释链）。出处：architecture §6.7 / draft §1.8。

### 3.4 多租户治理（★ 计划内，后置到 Phase 4）

> **状态（2026-06-10）**：完整多租户治理**已确认在计划内**，但按性价比后置到 Phase 4——这是排期决策，不是降范围（见 ADR-016）。**前置依赖**：§3.1 异步基建（Redis/Celery，用于配额计数与限流）。**先行最小切片**：托管 demo 前先做 §0 决策的「轻量 Hosted-Demo Safety Mode」（API-key stub + workspace-scoped demo token + 不存原文 secret + demo reset + rate limit + 只读公开报告），它独立、不依赖重型基建，可在 §3.1 之前单独落地。下列为完整治理项：

- [ ] **API Key / JWT / workspace 权限系统**（`api_keys` 表）。
- [ ] **多租户配额 (quota) / 限流**（依赖 §3.1 Redis）。
- [ ] **字段级脱敏 / 加密存储**（当前仅 digest）+ 完整 redaction 状态机（`none/redacted/digest_only/blocked`）。含 ADR-017 的「`raw_payload_ref` 必须加密且默认关闭」。
- [ ] **人工审核 memory conflict 管理后台**（admin）。**降级为远期：先做 conflict scan + conflict API + conflict table view，完整 admin workflow 后置。**

---

## 4. Phase 5 — 高级存储与检索（★ 整体后置，需触发条件）

architecture §3.3 / §7 / §8、draft §3/§5。**仅在以下条件满足时才启动（避免过早引入 ES+Neo4j 的部署/一致性/讲解复杂度，削弱主线）：**
> 1. pgvector / lexical / 当前检索在 benchmark 中已成为瓶颈；
> 2. 出现需要图谱 provenance 或 multi-hop retrieval 才能支撑的新 case；
> 3. Phase 3 可观测性与 Phase 4 lifecycle 已稳定。

- [ ] **Elasticsearch / OpenSearch 混合检索**（dense vector + BM25 + filter + valid_time + branch_status）。出处：architecture §8.2，「第一阶段推荐」但被 pgvector 替代。
- [ ] **Neo4j 溯源图谱**：完整图模型 + `SUPERSEDES/CONFLICTS_WITH` 关系。出处：architecture §7.5 / §8。
- [ ] **图邻居扩展检索**（Neo4j neighbor expansion，最大 2 hop）+ `graph_relatedness_score` 排序项。
- [ ] **多路候选融合 RRF/加权**（vector + BM25 + graph）+ 按 task_intent 切换 ranking_profiles。出处：architecture §6.5。
- [ ] **多存储最终一致性**：`index_status / graph_status / last_indexed_at` + 后台 reindex/graph sync 重试。
- [ ] **Query Planner**（query rewrite + entity/keyword hints）+ Need-Retrieval Decision（简单任务跳过检索）。
- [ ] **多跳迭代检索 (Iterative Reconstruction)**：cue→tag/entity→content/evidence，每跳受 token budget 限制。出处：draft §5（MRAgent/AdaMEM 方向）。

---

## 5. 状态树高级能力（多数后置）

architecture §6.3、draft §3（MAGE 方向）、ADR-004 推迟。

- [ ] **Completed subgoal 压缩成 summary node**。**可提前做（与 §9 Context Compaction 协同的最小子集）。**
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
- [ ] **TypeScript SDK** (`packages/ts-sdk`)。**后置。**
- [ ] **OpenTelemetry / OpenInference exporter**（接 LangSmith/Phoenix/Langfuse）。`core/telemetry.py` 是占位。
- [ ] **MCP Server** + **IDE 插件**（VS Code / Claude Code / Cursor）。**后置——生态入口而非核心能力。**
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

> **实施计划（2026-06-11）**：Issue-by-Issue 计划 `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`。首批 I1-I6 已完成：I1 Gate 三路输出、I2 DTO/builder/packer、I3 controller 主路径接线、I4 inspect/replay/metrics 接线、I5 benchmark/evaluator 扩展、I6 文档/项目记忆同步。I7 compaction negative retained 继续 deferred，作为独立后续设计，不改变当前 compaction 行为。

这是 §9 Context Compaction「安全过滤」的**反向补集**：compaction 把 failed/rolled_back/secret 从 summary 中排除，而本节在**安全前提下受控保留失败教训**，二者共享同一套安全分级口径。

当前 gate 对 failed/rolled_back 分支一刀切 hard reject（`gate.py:109-112`），coding agent 因此丢失「以前为什么错、哪个命令失败过、哪条路径不要再走」的负向学习信号。升级方向：**失败分支不作为正向上下文注入，但失败原因以「负向证据 / 避坑提示」受控注入**。

- [x] **Gate 三路输出**：I1 已完成。把 `accept / reject` 二元升级为 `accept / degrade / reject`；failed/rolled_back 且安全（非 secret/destructive/tool_sensitive/production_env）→ `degrade` 进负向通道；危险/secret/production 操作仍 hard reject。新增 `GateConfig.enable_failure_learning`，仅 variant_2 启用；baseline_0/baseline_1/variant_1 保持现有策略语义且不启用 failure learning。controller 接线已在 I3 完成；inspect/replay/metrics 完整接线已在 I4 完成。
- [x] **Packer `avoided_attempts` block**：I2 已完成 runtime `NegativeEvidence` DTO、共享 `retrieval/negative_evidence.py` builder（safe raw、unsafe sanitized、二次 redaction、source-state 去重、`max_blocks` 截断、固定模板）与 packer `avoided_attempts` 渲染。排序在 `project_memory`/`project_constraints` 之后、`tool_evidence` 之前（正向约束先定方向），ordinary（可被预算丢弃）。非危险失败保留原文（经二次 redaction）+ must-not-execute 框；destructive/secret/tool_sensitive/production-env 原始 memory hard reject，仅由共享 builder 生成不含原命令/参数/路径的固定模板安全提示（gate 不网开一面）。inspect/replay 三路径重建已在 I4 完成。
- [x] **Controller 主路径接线**：I3 已完成 hot path 调用共享 builder、`pack_context(negative_evidence=...)`、accepted/rejected/degraded 计数闭合、`context_packing.metadata` 记录 `degraded_count` / `hard_rejected_count` / retained `negative_evidence_count` / retained `sanitized_negative_evidence_count` / built+dropped negative evidence 计数，并输出 safe negative evidence 与 sanitized notice 两类 warning。demo/benchmark evaluator 已把 `avoided_attempts` 排除在正向污染/action 判定之外，case_1..case_9 acceptance 保持通过。I3 review 已修复 replay `_ACCEPTED_DECISIONS` 兼容问题和预算 drop 误报 injected 的 profile/warning 问题，复审未发现 P0/P1/P2 缺陷。
- [x] **Inspect / Replay / Observability 接线**：I4 已完成 `inspect_access` 与 replay original-view 通过共享 builder 重建 `avoided_attempts`，degrade 不再进入正向 accepted memory；replay 对缺失 source memory 只输出 warning、不恢复 raw failed text，并将 `reject(sanitized)→accept/degrade`、`degrade→accept` 判为 critical；observability summary/report/dashboard 模型新增 `degraded_negative_evidence_count` / `sanitized_failure_notice_count` / `negative_evidence_block_count`，degrade 不计入正向 failed-branch injection。
- [x] **Benchmark `case_10`（safe failure learning）+ `case_11`（sanitized destructive）**：I5 已完成。关键 evaluator 正/负向块显式分区（`contaminated`/action 只看正向区，negative_lesson/unsafe_negative_leakage 只看负向区）；runs 36→44；新增 acceptance `variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`，benchmark `acceptance.passed=true`（10/10 checks）。
- [x] **文档 / 项目记忆同步**：I6 已完成。`ROADMAP`、`CONTEXT_COMPACTION_PLAN`、Failure-aware 计划和 `.ai/` project memory 已统一标记 I1-I6 完成；`CONTEXT_COMPACTION_PLAN` 新增 C6/I7 协同占位，明确首批不改变 compaction 行为；Phase 3.5 SDK/LangGraph adapter/CLI（§6）与 6-strategy benchmark expansion / eval-table persistence（§7）也已完成，后续优先从 Provider Registry / Key Ontology（§10/§11）中选择。
- [ ] **后续候选（本节衍生）**：stale → 「过时警告」降级（首批不做，避免破坏 case_9 `variant_2_excludes_stale_memory`）；compaction 负向 retained（计划 I7，触及 `ContextCompactionLog` 持久化快照 + replay，独立落地）。
- **贯穿约束**：负向通道在 gate 之后从既有 candidate 派生，不新增检索入口、不绕过 §1 的 `_RETRIEVABLE_STATUSES` 生命周期过滤；I7 触碰 compaction 路径时须重申该约束。

---

## 10. Provider Registry（统一外部能力抽象）

当前已有真实 `LLMExtractionProvider`；后续 embedding / summarizer / LLM-judge 都会引入外部模型，且与「benchmark 可复现」「LLM key 不稳定」存在张力。建议抽象一个统一的 provider 注册层，**一处解决「确定性 default ↔ 真实模型 ↔ 可复现」的冲突**：

- [ ] **Provider 抽象族**：`LLMExtractionProvider`（已有）、`EmbeddingProvider`、`SummarizerProvider`、`JudgeProvider`，统一约定：deterministic fallback + config-gate 启用真实实现 + 失败降级（沿用 extraction 管线已验证的模式）。
- [ ] **Provider capability metadata**：声明各 provider 是否确定性、是否需要网络、支持的端点类型，benchmark 据此自动选确定性路径以保可复现。
- [ ] 关联：§0 真实 embedding 决策、§1 LLM key 风险、§9 可配置 summarizer 都落到这一层。

## 11. Controlled Memory Key Ontology（受控记忆 key 本体）

§1 已记录「LLM key 不稳定破坏冲突解析」。当前缓解手段是系统提示里的 key 词表，建议升级为正式的 **key schema registry**（比「语义去重」更早、更实用、更可控）：

- [ ] **受控 key 本体表**：如 `project.runtime` / `project.package_manager` / `project.test_command` / `project.database` / `tool.command.failed` / `endpoint.current` / `endpoint.deprecated` / `user.preference.*`，定义单值/多值语义与 supersede 规则。
- [ ] **抽取侧校验/归一**：LLM 候选的 key 必须映射到本体（或显式标记为 free-form），不在本体内的同义概念归一到规范 key，根治 key 漂移。
- [ ] **本体作为单一真相源**：当前单值语义分散在三处（`writer` supersede、`resolver._SINGLE_VALUED_KEYS`、`llm_extractor._SYSTEM_PROMPT`），靠人工保持同步。2026-06-13 审查已发现 `resolver._SINGLE_VALUED_KEYS` 落后于 LLM 受控 key 契约并临时补齐（见 §1.1）；本体落地后应让三处都从同一注册表派生，消除漂移根因。
- [ ] 关联：§1 LLM key 风险、resolver 冲突解析、§10 ExtractionProvider。

## 12. Documentation & Showcase（展示资产）

系统内核已强，但缺「可被他人理解/复现/接入」的展示层——这是当前观感性价比最高的补强之一：

- [x] **README 架构图 + Quickstart**：已添加顶层 `README.md`，包含 Mermaid 架构图、deterministic Quickstart、PostgreSQL/API 可选路径、报告说明和关键 API。可复现入口为 `./scripts/reproduce.sh`；core compose 仍由现有 `docker-compose.yml` 提供 pgvector PostgreSQL 基线。
- [x] **Demo GIF / 截图** + `demo_report` / `benchmark_report` / `llm_bench_report` 示例产物：本轮不提交二进制 GIF/截图，改为可再生成展示产物；`./scripts/reproduce.sh` 生成 `demo_report`、`benchmark_report`、`observability_report`，README 记录可选 real-LLM bench 生成 `llm_bench_report`。
- [x] **技术博客**：`docs/blog/why-agent-memory-is-not-just-rag.md` 已添加，讲 failed-branch isolation / workspace isolation / stale rejection / tool safety / state-aware retrieval / replay observability。

---

## 13. 安全与一致性加固（Security & Consistency Hardening）★ 2026-06-13 审查产出

源自一次覆盖六大模块的全量代码审查（详细清单见 §1.1）。这些不是新功能，而是把现有承诺（脱敏纵深、后端等价、确定性、数据一致）补全到生产级。建议在 §10/§11 之前先做安全/一致性两条 High 子集。

### 13.1 安全闭环（优先）
- [ ] **正向打包路径脱敏**：packer 对所有正向块 content 统一 `redact()`，或在候选选择阶段按 `sensitivity==secret`/`contains_secret` 兜底过滤，使正向路径与负向证据路径具备对称的纵深防御。
- [ ] **`variant_1` gate 收敛**：改为仅置 `allow_failed_branch`/`allow_rolled_back`，保留 `enable_hard_policy`/`enable_risk_policy`，避免连带放过 secret/destructive/quarantined。
- [ ] **鉴权去装饰化**：对齐 ADR-016，实现轻量 token 校验依赖，或文档明确「当前无鉴权、api_key 仅预留」，消除安全假象。

### 13.2 一致性 / 并发
- [ ] **`next_sequence_no` 原子化**：分配 + 插入在同一加锁事务内，或改用计数行 `UPDATE ... RETURNING`。
- [ ] **检索超时路径统一**：两条超时分支都落库同一 access，`_persist_trace`+`_bump_access_counts` 纳入抗取消单元，消除 split-brain。
- [ ] **后端 isomorphism 补全**：`StateTreeError` 在 runtime 层映射为客户端可纠正错误；`replay_access` run 存在性检查下沉到 `MemoryRuntime`，使两后端错误语义严格等价。
- [ ] **gate log 确定性排序**：`list_gate_logs` 加次级排序键（`created_at, gate_id`），replay accepted 排序加确定性 tiebreak，消除虚假 order-changed diff 与 InMemory/SQL 行为差异。
- [ ] **ORM/迁移索引对齐**：统一 `context_compaction_logs` 的 workspace 索引声明，避免 `create_all` 与迁移 schema 漂移。

### 13.3 精度 / 健壮性
- [ ] **token 估算独立化**：不复用剔停用词的检索分词器；提供 CJK 感知的计数与 `_truncate_text` 截断，保证预算闭合在双语场景可靠。
- [ ] **summarizer LLM provenance 校验放宽**：用 `must_retain_facts` 自身 provenance 播种 allow-set，避免合法 LLM 输出被恒判 invented 而 LLM seam 形同虚设。
- [ ] **状态机边界**：`apply_finish` 处理 `rolled_back`；`finish_step`/rollback 退化分支以 `StateTreeError` 取代幽灵节点/不一致结果。
- [ ] **benchmark 公平性快照整体化**：对受测 workspace 做整体 memory 快照/恢复（而非仅 `access_count`），防止 §3.2 Reflection 调度器落地后公平性静默失效。
- [ ] **其余 Low 项**：见 §1.1 末条（read-modify-write 竞态、`last_accessed_at` 死字段、episodic 内容未过 risk 屏蔽、CLI/evaluator 判定重复、报告路径 TOCTOU、naive datetime 健壮性、`tool_sensitive_present` 误判等）。

### 13.4 横切运行时保障（Cross-cutting Runtime Hardening）

外部审查（2026-06-13）补充的横切层：不是新核心机制，而是让 mem-trace 像一个严肃的「trace-first / replayable」Agent Memory Runtime。已核对源码现状，标注真缺口 vs 已部分存在需聚合。其中 **Policy Contract + Conformance Suite 价值最高**，与本轮 replay/repeatability/一致性加固最契合，应优先于 §10/§11。

- [ ] **(A) Retrieval Policy Contract / policy snapshot ★最高价值**：现状 `MemoryAccessLog.retrieval_strategy` 只存了 strategy enum，gate 权重 / packer budget / compaction reserve / failure-learning / provider 确定性路径等散在代码里，**未随 access 持久化**。一旦改 gate/retention/budget 逻辑，replay drift 与 benchmark 对比无法区分「memory 变了(data drift)」还是「policy 变了(policy drift)」。建议：`RetrievalPolicySnapshot`（`policy_version` + gate/packer/provider config hash + strategy 语义文档），随 access_log 持久化，replay 显式区分 data drift / policy drift。承接本轮 `variant_3` 把 rerank score 持久化以稳定 replay 的思路。
- [ ] **(B) Runtime Invariant & Conformance Suite ★最高价值**：现状 invariant 测试**已分散存在但未聚合**（lifecycle 排除见 `test_retrieval_flow.py::test_long_context_preserves_scope_lifecycle...`、backend isomorphism 见 SDK `test_backend_isomorphism.py`、access_count 隔离见 benchmark 测试）。建议升级为显式 conformance 套件，把 §1 贯穿性约束「任何新检索路径必须重新应用生命周期过滤」固化为机器校验：① strategy conformance（六策略 × lifecycle/workspace/secret/failed-branch 不变量）② backend conformance（in-memory / SQL / HTTP 等价）③ adapter conformance（SDK / LangGraph / CLI / 未来 MCP）④ replay 不变量（不重跑 summarizer/extractor、无副作用）。**后续每加一个入口（Provider/Ontology/Scheduler/MCP）都必须过此套件，防止绕过 gate/lifecycle/redaction。**
- [ ] **(C) Trace Bundle / Debug Export**：现状仅有 `reports/` 静态 JSON/MD/HTML 与 replay API，**无可分享的脱敏 debug bundle**。建议 `memtrace export-run/export-access --redacted` + `import-bundle`，打包 run/steps/events/state-tree/memories/access/gate/profile/compaction logs + policy snapshot(A) + redaction metadata。面向开源 issue 复现与开发者协作，复用 §13.1 正向脱敏与 §13.4-A snapshot。
- [ ] **(D) Schema Compatibility & Migration Policy**：现状 `test_migrations.py` 只校验 migration **声明**的 schema 操作，**无 upgrade/downgrade 实跑 + 旧数据兼容回归**；与 §13.2「ORM/迁移 compaction 索引漂移」同源。建议横切策略：每个 migration 必须有 upgrade 回归 fixture；downgrade 支持与否需显式声明；enum/status 扩展不得让旧 access/eval 记录解析失败；`MemoryItem` 新字段默认值策略；seeded fixture DB 做 migration regression。后续加 key ontology / versions / conflicts / provider registry 表前先立此策略。
- [ ] **(E) Dogfood Agent Scenarios**：现状有 `examples/simple_agent` + `examples/langgraph_adapter`（机制演示），benchmark 为确定性量化，**缺贴近真实工作流的端到端脚本**。建议 2-3 个 dogfood harness：coding-agent loop（failed npm → recover bun → 后续复用）、multi-session 项目约束延续、destructive failure 仅 sanitized 不重试、long-horizon（history_summary + project constraints + replay）。把项目从「测试很完整」推到「一眼看懂能接到 agent 上」。

---

## 附：推荐推进顺序（建议）

> 原则：先补「展示/可观测/可复现」与「贴合定位的 compaction」，把「重型基建/高级存储/生态入口」后置并设触发条件，**严防范围膨胀**。下列顺序覆盖 §1–§13 的全部待办；§8 为明确不做、不参与排期。

1. ~~**清立即决策**（§0）~~ ✅ **已完成 (2026-06-10)**：embedding 保留确定性 default + 真实作可选 provider（ADR-015）；auth 走轻量 Hosted-Demo Safety Mode（ADR-016）；secret 默认不存原文（ADR-017）。
2. ~~**Phase 3-A 后端可观测性**（§2）~~ ✅ **已完成 (2026-06-10)**：Retrieval Replay + eval 表 + Quality/Safety profiler + 最小 JSON/MD/HTML 报告，Issues 1-8 全部完成并端到端验证。
3. ~~**展示资产 + 可复现基线**（§12 + §7 部分）~~ ✅ **已完成 (2026-06-10)**：README + Mermaid 架构图 + deterministic Quickstart + `scripts/reproduce.sh` / `scripts/smoke.sh` + demo/benchmark/observability 可再生成报告 + optional LLM bench 指引 + 技术博客 + integration reproducibility tests。
4. ~~**Context Compaction**（§9 + §5/§10 协同子集）~~ ✅ **核心闭环已完成 (2026-06-11)**：C0-C5 完成 packer 超预算补偿、durable compaction log、observability/replay、SummarizerProvider、rolling history summary、压缩质量 benchmark/report/replay 同步；剩余协同项为 §5「completed subgoal → summary node」与 §10 Provider 抽象族。
5. ~~**Failure-aware Negative Memory Injection**（§9.1）~~ ✅ **首批已完成 (2026-06-12)**：I1 gate 三路 `accept/degrade/reject`、I2 `NegativeEvidence` DTO + shared builder + packer `avoided_attempts`、I3 controller hot-path wiring、I4 replay/metrics/inspect sync、I5 benchmark/evaluator 扩展、I6 文档/项目记忆同步均已完成。benchmark 已含 `case_10` safe failure learning / `case_11` sanitized destructive failure（44 runs）并通过新增 acceptance；I7 compaction negative retained 仍 deferred。
6. ~~**Phase 3.5 SDK / Adapter / CLI**（§6 前段）~~ ✅ **已完成 (2026-06-12)**：Python SDK + in-process/HTTP backends + LangGraph Adapter + custom-loop / LangGraph 示例 + CLI 入口 + README 三入口说明 + S6 项目记忆同步均已完成，证明「可插拔 runtime」。S6 复审还修复了 `flush_session` 对含 `/` 的 arbitrary `session_id` 的 HTTP/in-process 等价性缺口；TS SDK / OTel / MCP / IDE 插件继续后置。
7. ~~**完整 6 策略对比 + benchmark 落库**（§7 主线）~~ ✅ **已完成 (2026-06-12)**：6 策略（含 `long_context` / `variant_3` reflection-lite）逐层量化；新增 `case_12_reflection_retention` 与 acceptance `variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat`；benchmark 现额外落 `eval_*` 表，并已加固同一 repo 重复落库运行的 workspace 隔离；Task 11 已完成 full regression / reproducibility / report-shape / project-memory sync，当前 acceptance 为 12/12。**+reflection 为确定性占位，待 §3.2 调度器落地后取代**（见 §3.2）。下一候选转向 §10/§11 Provider Registry / Key Ontology。
8. **安全与一致性加固**（§13，★ 推荐下一步，优先于新功能；源自 2026-06-13 全量审查 §1.1 + 外部审查横切补充）。分四批，**完整覆盖 §13.1/§13.2/§13.3/§13.4**：
   - **8a 安全闭环（§13.1，最优先）**：正向打包脱敏 + `variant_1` gate 收敛 + 鉴权去装饰化。
   - **8b 一致性/并发（§13.2）**：先做三条 High（`next_sequence_no` 原子化、检索超时 split-brain、后端 isomorphism `StateTreeError`/`replay_access`），再做两条 Medium（gate log 确定性排序、ORM/迁移 compaction 索引对齐）。
   - **8c 横切运行时保障 High（§13.4-A/B，★最高价值，可与 8b 并行）**：Retrieval Policy Contract / policy snapshot（区分 data drift vs policy drift）+ Runtime Invariant & Conformance Suite（把分散的 lifecycle/workspace/secret/isomorphism 不变量聚成机器校验套件，后续每个新入口必过）。
   - **8d 精度/健壮性 + 其余横切（§13.3 + §13.4-C/D/E）**：token 估算独立化、summarizer provenance 放宽、状态机边界、benchmark 公平性快照整体化；Trace Bundle/Debug Export、Migration 兼容回归策略、Dogfood agent 场景，以及 §1.1 末条 Low 项随手清理。
9. **Provider Registry + Key Ontology**（§10 + §11）：统一 `LLMExtractionProvider/EmbeddingProvider/SummarizerProvider/JudgeProvider` 抽象族 + capability metadata（承接 §0 embedding 决策、§9 summarizer）；受控记忆 key 本体表 + 抽取侧归一（根治 §1 LLM key 漂移，并消除 §11「本体作为单一真相源」记录的三处单值语义漂移）。
10. **Phase 4 异步基建 + 生命周期 + 多租户治理**（§3 全段）：§3.1 Redis buffer/Celery（替换 §1 进程内 buffer）→ §3.2 Reflection/Forgetting 调度器 + 10 定时任务 + 审计日志 → §3.3 memory_versions/conflicts 版本与冲突管理 → §3.4 API Key/JWT/quota/redaction 完整多租户治理。（托管 demo 所需的轻量 Hosted-Demo Safety Mode 可在此之前按需单独落地。）
11. **Phase 3-B 前端可视化**（§2）：Timeline → State Tree Viewer → Gate Analysis → Sankey。
12. **Phase 5 高级存储**（§4）：ES/Neo4j 混合检索 + 图谱 provenance + 多路融合 + Query Planner + 多跳检索，**仅在触发条件满足时启动**。
13. **远期 / scale-only**：§5 状态树其余能力（subgoal 自动推断 / 完整 node_type / MAGE 四操作）、§6 TS SDK / OTel exporter / MCP Server / IDE 插件 / Go-Rust 组件、§7 小规模 LoCoMo/MemoryArena。**均设触发条件，不主动排期。**

> **贯穿性约束（非排期项，但每一步都要遵守，来自 §1）**：① 任何新检索路径必须重新应用生命周期过滤（`_RETRIEVABLE_STATUSES`），否则泄漏退役记忆；② 切 pg16 镜像需 `docker-compose down -v`（破坏性，运维注意）；③ profiler 亚毫秒阶段读 0ms 属预期非 bug。
