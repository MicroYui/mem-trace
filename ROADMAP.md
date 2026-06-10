# MemTrace 后续工作路线图 (ROADMAP)

> 本文件是「未来要做的事情」的权威清单。新会话启动后，连同 `.ai/PROJECT_STATE.md` 一起阅读即可知道当前进度与后续待办。
>
> - **进度基线**：P0 + P1 完成；**P2 完成 (6/6)**，含真实 OpenAI 兼容 LLM extraction provider（已对火山方舟 deepseek 实测）+ 真实 LLM 验证 bench（`app/benchmark/llm_bench.py`）。
> - **来源**：`architecture.md`（完整架构，自带 Phase 标注）、`draft.md`（原始愿景，范围远大于 MVP）、`.ai/MVP_SCOPE.md`（Out of Scope）、`.ai/OPEN_QUESTIONS.md`、`.ai/DECISIONS.md`、`.ai/PROJECT_STATE.md`。
> - **维护约定**：完成一项后在此勾掉并同步更新 `.ai/PROJECT_STATE.md` 与 `.ai/IMPLEMENTATION_PLAN.md`。区分两类来源——「愿景级」(draft) vs 「已决策推迟」(ADR/MVP_SCOPE)。

---

## 0. 即时待决策 (OPEN QUESTIONS)

来自 `.ai/OPEN_QUESTIONS.md` §Remaining，需先拍板再动手：

- [ ] **真实 embedding 模型替换**：当前是确定性 hashed bag-of-words（blake2b, dim 256），相似度是 proxy。替换只需改 `similarity.stable_embedding`，但要解决「如何保持 benchmark 可复现」（保留确定性路径或配置开关）。出处：OPEN_Q #1 / PROJECT_STATE 风险#1 / ADR-014。
- [ ] **Auth model**：MVP 无 API-key/workspace auth。托管 demo 前是否需要 API-key stub。出处：OPEN_Q #3 / MVP_SCOPE Out-of-Scope #5。
- [ ] **Raw secret payload**：当前 redact 后持久化、不保留原始 secret。未来 `raw_payload_ref` 是否存加密原始事件。出处：OPEN_Q #4 / architecture §6.2。

---

## 1. 技术债 / 已知风险

来自 `.ai/PROJECT_STATE.md` Open Risks 与 `.ai/PITFALLS.md`：

- [ ] **进程内 candidate buffer 不跨 worker 共享**：当前单进程，多 worker 部署会失效。architecture 明确把 Redis-backed buffer 推迟到 post-P2。出处：PROJECT_STATE / ADR 注。
- [ ] **生命周期过滤是单点**：superseded/archived 过滤只在 retrieval candidate 阶段（`_RETRIEVABLE_STATUSES`）。**任何新检索路径必须重新应用此过滤**，否则会泄漏退役记忆。出处：PITFALLS。
- [ ] **LLM key 不稳定性**：模型对同一概念可能分配不同 key，破坏 key-based 冲突解析。已用受控 key 词表系统提示缓解，但仍是真实 LLM 路径脆弱点。可考虑「语义去重 / 同义 key 映射」根治。出处：PROJECT_STATE / llm_extractor `_SYSTEM_PROMPT`。
- [ ] **PG15 数据卷与 pg16 镜像不兼容**：切换需 `docker-compose down -v`（破坏性）。运维注意。
- [ ] **profiler 亚毫秒阶段读为 0ms**：四舍五入所致，属预期非 bug（真实负载下非 0）。

---

## 2. Phase 3 — 可观测性与可视化（高价值、简历亮点）

对齐 architecture §6.9 / §14 Phase 3、draft §9。当前仅有表格 API（`GET /v1/dashboard/tables`，ADR-013）。

- [ ] **完整 phase-aware Profiler**：扩到 architecture §6.9 的 10 阶段归因（Ingestion/Construction/Retrieval/Rerank/Gate/Context Packing/Generation/Maintenance/Quality/Safety）。
- [ ] **Quality & Safety 指标**：命中正确记忆、错误记忆注入、跨域泄漏、失败分支污染、工具参数漂移（部分 benchmark 已覆盖，需统一到 profiler）。
- [ ] **Retrieval Replay**：`replay_retrieval(access_id)` / `replay_run(run_id)` 复现检索→重排→gate→packing。出处：architecture §6.1/§6.9。
- [ ] **React + TS 前端 Dashboard (`apps/web`)**：架构目录已规划，代码库无实现。
  - [ ] Run Trace Timeline
  - [ ] **Memory Flow Sankey 图**（候选→gate→context→answer）
  - [ ] **State Tree Viewer**（active path / failed branch / 压缩 subgoal 可视化）
  - [ ] Cost Breakdown / Gate Analysis / Replay Panel
- [ ] **eval 表落地**：`eval_cases / eval_runs / eval_results`（当前 benchmark 仅文件报告 + 内存表）。出处：architecture §7.1。

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
- [ ] **人工审核 memory conflict 管理后台**（admin）。

---

## 4. Phase 5 — 高级存储与检索

architecture §3.3 / §7 / §8、draft §3/§5。pgvector 触顶或需要图能力时再做。

- [ ] **Elasticsearch / OpenSearch 混合检索**（dense vector + BM25 + filter + valid_time + branch_status）。出处：architecture §8.2，「第一阶段推荐」但被 pgvector 替代。
- [ ] **Neo4j 溯源图谱**：完整图模型 + `SUPERSEDES/CONFLICTS_WITH` 关系。出处：architecture §7.5 / §8。
- [ ] **图邻居扩展检索**（Neo4j neighbor expansion，最大 2 hop）+ `graph_relatedness_score` 排序项。
- [ ] **多路候选融合 RRF/加权**（vector + BM25 + graph）+ 按 task_intent 切换 ranking_profiles。出处：architecture §6.5。
- [ ] **多存储最终一致性**：`index_status / graph_status / last_indexed_at` + 后台 reindex/graph sync 重试。
- [ ] **Query Planner**（query rewrite + entity/keyword hints）+ Need-Retrieval Decision（简单任务跳过检索）。
- [ ] **多跳迭代检索 (Iterative Reconstruction)**：cue→tag/entity→content/evidence，每跳受 token budget 限制。出处：draft §5（MRAgent/AdaMEM 方向）。

---

## 5. 状态树高级能力

architecture §6.3、draft §3（MAGE 方向）、ADR-004 推迟。

- [ ] **Subgoal 自动推断**（当前仅显式 `root/step/recovery`）。
- [ ] **Completed subgoal 压缩成 summary node**。
- [ ] **完整 node_type**：`root/subgoal/step/tool_call/recovery/summary`。
- [ ] **MAGE 四类操作**：Grow / Compress / Maintain / Revise。

---

## 6. SDK / 集成 / 可观测性导出

architecture §3/§9/§External、MVP_SCOPE Out-of-Scope #3、§15 明确「后做」。

- [ ] **TypeScript SDK** (`packages/ts-sdk`) + 独立 **Python SDK** 包。
- [ ] **LangGraph Adapter**（before/after node 钩子）。
- [ ] **OpenTelemetry / OpenInference exporter**（接 LangSmith/Phoenix/Langfuse）。`core/telemetry.py` 是占位。
- [ ] **MCP Server** + **IDE 插件**（VS Code / Claude Code / Cursor）。
- [ ] **CLI 入口**（Python SDK / HTTP / CLI 三入口之一）。
- [ ] **Go Trace Collector / Gateway**（QPS 上来后重写）、**Rust profile analyzer**（§3.2 / §15）。

---

## 7. 评估 / Benchmark 扩展

- [x] **真实 LLM bench 扩展场景**（`app/benchmark/llm_bench.py`，现 8 场景）：✅ 已实现并实测——memory_override / scale_retrieval / llm_vs_rule / nl_extraction + 新增 failed_branch_isolation / workspace_isolation / stale_rejection / tool_safety。多端点可移植性对比经 `MEMTRACE_LLM_BENCH_ENDPOINTS`（JSON 列表）支持，单端点经标准 `MEMTRACE_LLM_*`。火山方舟 deepseek 实测 8/8 PASS。
- [ ] **完整 6 策略对比**：no memory / long-context / vector / state-aware / +gate / +reflection（+reflection 依赖 §3.2）。出处：architecture §6.10。
- [ ] **小规模 LoCoMo / MemoryArena**（§15 标注「可做小规模，不优先刷榜」）。
- [ ] **压测脚本 + 集成测试补全 + Docker Compose 全栈一键**（api + postgres + redis + es + neo4j + worker + frontend）。出处：draft §12.4 / §11。

---

## 8. 明确不做（Out of Scope，记录以避免重复讨论）

architecture §15 / draft §7 / MVP_SCOPE：

- 图片 OCR / 音频 / 多模态摄取、大而全文档知识库。
- 复杂社区发现 / 全量知识图谱前端。
- 训练式 MemGate 小模型（高风险候选可用 LLM-judge，但不训练模型）。
- LoCoMo/MemoryArena 全量刷榜。
- 多 Agent 协作平台。

---

## 附：推荐推进顺序（建议）

1. **先清待决策**（§0）——尤其真实 embedding 与 auth，影响后续多处。
2. **Phase 3 可观测性/前端**（§2）——价值高、相对独立、是项目亮点，不依赖重型基建。
3. **Phase 4 异步基建**（§3.1）作为前置，再叠加 Reflection/Forgetting（§3.2）与冲突/版本（§3.3）。
4. **Phase 5 高级存储**（§4）在 pgvector 触顶或需要图能力时启动。
5. SDK/集成（§6）与评估扩展（§7）按需穿插。
