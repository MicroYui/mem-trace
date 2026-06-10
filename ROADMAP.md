# MemTrace 后续工作路线图 (ROADMAP)

> 本文件是「未来要做的事情」的权威清单。新会话启动后，连同 `.ai/PROJECT_STATE.md` 一起阅读即可知道当前进度与后续待办。
>
> - **进度基线**：P0 + P1 完成；**P2 完成 (6/6)**，含真实 OpenAI 兼容 LLM extraction provider（已对火山方舟 deepseek 实测）+ 真实 LLM 验证 bench（`app/benchmark/llm_bench.py`）。
> - **来源**：`architecture.md`（完整架构，自带 Phase 标注）、`draft.md`（原始愿景，范围远大于 MVP）、`.ai/MVP_SCOPE.md`（Out of Scope）、`.ai/OPEN_QUESTIONS.md`、`.ai/DECISIONS.md`、`.ai/PROJECT_STATE.md`。
> - **维护约定**：完成一项后在此勾掉并同步更新 `.ai/PROJECT_STATE.md` 与 `.ai/IMPLEMENTATION_PLAN.md`。区分两类来源——「愿景级」(draft) vs 「已决策推迟」(ADR/MVP_SCOPE)。

---

## 0. 即时待决策 (OPEN QUESTIONS)

来自 `.ai/OPEN_QUESTIONS.md` §Remaining，需先拍板再动手：

- [ ] **真实 embedding 模型替换**：当前是确定性 hashed bag-of-words（blake2b, dim 256），相似度是 proxy。**倾向方案：保留确定性 default 作为 benchmark 基线，真实 embedding 作为可选 provider（见 §10 Provider Registry，config-gate 切换）**。出处：OPEN_Q #1 / PROJECT_STATE 风险#1 / ADR-014。
- [ ] **Auth model**：MVP 无 API-key/workspace auth。**倾向方案：托管 demo 前做轻量 Hosted-Demo Safety Mode（API-key stub + workspace-scoped demo token + 不持久化原文 secret + demo reset + rate limit + 只读公开报告），而非完整多租户治理（后者见 §3.4）**。出处：OPEN_Q #3 / MVP_SCOPE Out-of-Scope #5。
- [ ] **Raw secret payload**：当前 redact 后持久化、不保留原始 secret。**倾向方案：默认不存原文；若做 `raw_payload_ref` 必须加密且默认关闭**。出处：OPEN_Q #4 / architecture §6.2。

---

## 1. 技术债 / 已知风险

来自 `.ai/PROJECT_STATE.md` Open Risks 与 `.ai/PITFALLS.md`：

- [ ] **进程内 candidate buffer 不跨 worker 共享**：当前单进程，多 worker 部署会失效。architecture 明确把 Redis-backed buffer 推迟到 post-P2。出处：PROJECT_STATE / ADR 注。
- [ ] **生命周期过滤是单点**：superseded/archived 过滤只在 retrieval candidate 阶段（`_RETRIEVABLE_STATUSES`）。**任何新检索路径必须重新应用此过滤**，否则会泄漏退役记忆。出处：PITFALLS。
- [ ] **LLM key 不稳定性**：模型对同一概念可能分配不同 key，破坏 key-based 冲突解析。已用受控 key 词表系统提示缓解，但仍是真实 LLM 路径脆弱点。**根治方向见 §11 Controlled Memory Key Ontology（schema registry，比「语义去重」更早更实用）**。出处：PROJECT_STATE / llm_extractor `_SYSTEM_PROMPT`。
- [ ] **PG15 数据卷与 pg16 镜像不兼容**：切换需 `docker-compose down -v`（破坏性）。运维注意。
- [ ] **profiler 亚毫秒阶段读为 0ms**：四舍五入所致，属预期非 bug（真实负载下非 0）。
- [ ] **检索超预算是丢弃式截断、无压缩补偿**：`packer.pack_context` 超出 `token_budget` 时整块 `break` 丢弃低优先级 block，被丢内容没有任何二次摘要/折叠，可能静默丢失约束。根治方案见 §9 Context Compaction。出处：`packer.py:pack_context`。

---

## 2. Phase 3 — 可观测性与可视化（★ 最高性价比，优先做）

对齐 architecture §6.9 / §14 Phase 3、draft §9。当前仅有表格 API（`GET /v1/dashboard/tables`，ADR-013）。**先做不依赖前端的 P3-A，再做可视化 P3-B（先 HTML/表，后 React 大前端）。**

### 3-A：后端可观测性（无需大前端，优先级最高）
- **实施计划**：见 repo 根目录 `P3A_IMPLEMENTATION_PLAN.md`。执行约定：每完成计划 §11 的一个 Issue，都必须同步更新 `.ai/PROJECT_STATE.md`，并 tick 或注释本节对应 checkbox/sub-checkbox。
- [x] **Retrieval Replay**：`replay_retrieval(access_id)` / `replay_run(run_id)` 复现检索→重排→gate→packing。**这是把系统从「跑过一次 demo」升级为「每次检索决策可复现/可解释/可调试」的关键，优先级最高。** 出处：architecture §6.1/§6.9。Phase 3-A Issue 2 已完成其前置基础：`RetrievalController.trace(...)` side-effect-free pipeline + hot-path trace 持久化重构；Phase 3-A Issue 3 已完成 replay service + deterministic diff semantics + runtime facade；Phase 3-A Issue 4 已完成 Replay HTTP API（`GET /v1/replay/access/{access_id}` / `GET /v1/replay/runs/{run_id}`）与最小 observability summary endpoint。
- [x] **eval 表落地**：`eval_cases / eval_runs / eval_results` 已完成 Phase 3-A Issue 1：新增 eval records、Repository/InMemory/SQL 持久化、dashboard table 字段、Alembic `0004_phase3a_observability.py`，并补 `MemoryAccessLog.top_k` 以支持后续 replay 精确重放。出处：architecture §7.1。
- [ ] **Quality & Safety 指标统一进 profiler**：failed_branch_contamination / stale_injection / tool_safety / workspace_leakage（部分 benchmark 已覆盖，需统一到 profiler）。
- [ ] **完整 phase-aware Profiler**：扩到 architecture §6.9 的 10 阶段归因（Ingestion/Construction/Retrieval/Rerank/Gate/Context Packing/Generation/Maintenance/Quality/Safety）。
- [ ] **最小 Dashboard（静态 HTML 报告优先，不急于上 React）**。

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
- [ ] **完整生命周期状态机**：`active→dormant→archived→deleted` + 旁路状态 `pinned/superseded/conflicted/quarantined` 全套转移。
- [ ] **10 个定时任务**：summarize_completed_runs(✅已有同步版)、extract_procedural_memory(✅)、dedup_memory、conflict_scan、score_memory、decay_memory、archive_memory、quarantine_memory、profile_refresh、reindex_memory。
- [ ] **审计日志**：scheduler 每次状态变更记录 audit log。

### 3.3 冲突 / 版本管理（在 P2 基础版上补全）
- [ ] **`memory_versions` 表 + Version Manager**：完整版本审计链。
- [ ] **`memory_conflicts` 表 + conflict_scan 后台任务**：同 subject+predicate 不同 object 标记。
- [ ] **7 条完整冲突规则**（时间覆盖、tool result 优先、provenance 解释链）。出处：architecture §6.7 / draft §1.8。

### 3.4 多租户治理
- [ ] **API Key / JWT / workspace 权限系统**（`api_keys` 表）。
- [ ] **多租户配额 (quota) / 限流**。
- [ ] **字段级脱敏 / 加密存储**（当前仅 digest）+ 完整 redaction 状态机（`none/redacted/digest_only/blocked`）。
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

- [ ] **【提前·Phase 3.5】独立 Python SDK 包**（`packages/python-sdk`）+ **LangGraph Adapter**（before/after node 钩子）+ `examples/` 下一个 custom-loop 与一个 langgraph 接入示例。证明「任意 agent loop → 接入 MemTrace → trace/retrieve/gate/profiler」。
- [ ] **CLI 入口**（Python SDK / HTTP / CLI 三入口之一）。
- [ ] **TypeScript SDK** (`packages/ts-sdk`)。**后置。**
- [ ] **OpenTelemetry / OpenInference exporter**（接 LangSmith/Phoenix/Langfuse）。`core/telemetry.py` 是占位。
- [ ] **MCP Server** + **IDE 插件**（VS Code / Claude Code / Cursor）。**后置——生态入口而非核心能力。**
- [ ] **【远期·scale-only】Go Trace Collector / Gateway**、**Rust profile analyzer**。**触发条件：Python ingestion QPS 或 profiling 分析成为真实瓶颈时再做；当前阶段重点是机制与评测，不是 QPS。** 出处：architecture §3.2 / §15。

---

## 7. 评估 / Benchmark 扩展

- [x] **真实 LLM bench 扩展场景**（`app/benchmark/llm_bench.py`，现 8 场景）：✅ 已实现并实测——memory_override / scale_retrieval / llm_vs_rule / nl_extraction + 新增 failed_branch_isolation / workspace_isolation / stale_rejection / tool_safety。多端点可移植性对比经 `MEMTRACE_LLM_BENCH_ENDPOINTS`（JSON 列表）支持，单端点经标准 `MEMTRACE_LLM_*`。火山方舟 deepseek 实测 8/8 PASS。
- [ ] **完整 6 策略对比**（★ 优先于 LoCoMo）：no memory / long-context / vector / state-aware / +gate / +reflection（+reflection 依赖 §3.2）。这是最有说服力、最好讲的 benchmark——逐层证明每个机制的收益（无记忆失败 → 全塞污染/高 token → 向量相似但失败分支污染 → 状态感知改善 → +gate 污染率显著下降 → +reflection 长期质量提升）。出处：architecture §6.10。
- [ ] **benchmark report 落库**（配合 §2 eval 表）。
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

mem-trace 定位为「long-horizon agent 的状态感知记忆运行时」，而长程 agent 的核心痛点正是 **context window 撑爆**。当前系统对「上下文超限」只做**丢弃式截断**（见 §1 技术债），缺少 LLM-agent 式的 context compaction——即「当上下文/历史超出预算时，把待丢弃或冗长的内容压缩成摘要再注入」。这是一个独立于 §3.2（生命周期衰减）与 §5（状态树压缩）的检索/打包层能力，三者协同但不重叠。

现状盘点：
- ✅ **run 结束摘要**（`summarizer.build_run_summary`，冷路径）：把已结束 run 的 trace 蒸馏成 episodic + procedural memory。压缩的是「已结束轨迹→长期记忆」，**不解决运行中长历史超窗**。
- ✅ **active path 进度块**（`packer.build_active_path_block`）：把 completed 节点 label 串成一句，是拼接展示**非压缩**。
- ❌ **运行时 context compaction**：完全缺失。

待办：
- [ ] **packer 超预算压缩补偿（替代纯丢弃）**：`pack_context` 超 `token_budget` 时，对被丢弃的低优先级块做「合并摘要 / 块内裁剪」而非整块丢弃，至少保留一条「已省略 N 条记忆（含约束 X/Y）」的占位摘要，避免约束静默丢失。出处：§1 技术债 / `packer.py`。
- [ ] **运行中长历史折叠**：当一个 run 的事件流 / 对话历史超过窗口时，对早期历史做增量摘要（rolling summary）再注入上下文，类似 LLM agent 的 conversation compaction。可复用 `summarizer` 的 LLM 化版本。
- [ ] **可配置 summarizer（规则 / LLM 双路）**：compaction 的摘要器需 config-gate（默认规则保 benchmark 可复现；启用 LLM 走 `LLMExtractionProvider` 同款注入 + 失败降级），与 extraction 管线对齐。
- [ ] **压缩质量指标**：在 profiler/benchmark 中加 `compression_ratio` / 压缩前后任务成功率，量化「压缩是否丢了关键信息」。出处：architecture §6.8 `compression_gain`。
- [ ] **协同项（交叉引用）**：state tree 的 completed subgoal → summary node（§5）、生命周期 decay/archive 把旧记忆降级压缩（§3.2）。这三处共同构成完整的「记忆/上下文压缩」体系，建议一并设计。

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
- [ ] 关联：§1 LLM key 风险、resolver 冲突解析、§10 ExtractionProvider。

## 12. Documentation & Showcase（展示资产）

系统内核已强，但缺「可被他人理解/复现/接入」的展示层——这是当前观感性价比最高的补强之一：

- [ ] **README 架构图 + Quickstart**（一条命令起 `compose.core` 跑通 demo）。
- [ ] **Demo GIF / 截图** + `demo_report` / `benchmark_report` / `llm_bench_report` 示例产物。
- [ ] **技术博客**：Why Agent Memory is not just RAG（讲 failed-branch isolation / workspace isolation / stale rejection / tool safety / state-aware retrieval）。

---

## 附：推荐推进顺序（建议）

> 原则：先补「展示/可观测/可复现」与「贴合定位的 compaction」，把「重型基建/高级存储/生态入口」后置并设触发条件，**严防范围膨胀**。

1. **清立即决策**（§0）：embedding 保留确定性 default + 真实作可选 provider；auth 走轻量 Hosted-Demo Safety Mode；secret 默认不存原文。
2. **Phase 3-A 后端可观测性**（§2）：Retrieval Replay > eval 表 > Quality/Safety profiler > 最小 HTML 报告。**最高性价比。**
3. **展示资产**（§12）：README + 架构图 + demo/benchmark 示例 + 博客，让项目「可被理解/复现」。
4. **Context Compaction**（§9）：packer 超预算摘要补偿先做（不依赖重型基建），再做 rolling summary + 可配置 summarizer。
5. **Phase 3.5 SDK / Adapter**（§6）：Python SDK + LangGraph Adapter + custom-loop 示例，证明「可插拔 runtime」。
6. **完整 6 策略对比**（§7）：逐层量化各机制收益（优先于 LoCoMo）。
7. **Phase 4 异步基建 + 生命周期**（§3）：Redis buffer → Celery → score/decay/archive/conflict_scan → audit log。配套 §10 Provider Registry、§11 Key Ontology。
8. **Phase 3-B 前端可视化**（§2）：Timeline → State Tree Viewer → Gate Analysis → Sankey。
9. **Phase 5 高级存储**（§4）：仅在触发条件满足时启动。
10. 远期/scale-only：Go/Rust、MCP/IDE 插件、TS SDK（§6）、LoCoMo（§7）。
