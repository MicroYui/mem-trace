可以。既然你**不冲论文，只是做简历项目**，那这个方向反而更应该收敛：**不要做“大而全的个人知识库”，也不要完整复刻 MemoryBear/Comet；你应该做一个更偏 Agent Infra 的 Memory Runtime 项目。**

我建议项目定位为：

> **MemTrace：面向长程 Agent 的状态感知记忆运行时与性能画像系统**
> 核心不是“用户上传文档然后 RAG”，而是“Agent 在多轮任务执行过程中，如何写入、检索、过滤、压缩、回滚、评估 memory”。

这个定位比普通 RAG 知识库更贴你简历：**Agent Harness / Memory Runtime / 状态管理 / 工具调用 / 异步任务 / 检索调度 / 可观测性**。

---

## 1. Comet 和 MemoryBear 是否值得参考？

值得，但参考点不一样。

### Comet：适合参考“完整 AI 知识库 + 个人记忆助手”的工程骨架

Comet 的 README 里把自己定位为“个人 AI 知识库与记忆助手”，核心功能包括文档/网页/图片入库、ES 向量 + BM25 混合检索、记忆三元组抽取、Neo4j 四层溯源图谱、LangChain Agent 编排知识库/记忆/联网工具、SSE 流式输出、图谱/时间线/仪表盘可视化等。([GitHub][1])

它的工程分层也比较适合你学：FastAPI 后端按 controller → service → repository → model/db 分层，横切能力放在 core 下，包括 rag、memory、agent、llm、storage 等子系统。([GitHub][1]) Comet 的 memory 目录也按 preprocessing、extraction、retrieval、clustering、prompts 组织，比较适合你参考“记忆写入流水线”的拆法。([GitHub][2])

**你可以重点学 Comet 的这些东西：**

1. **工程目录组织**：controller/service/repository/model/db 的后端分层。
2. **RAG 与 Memory 分离**：RAG 处理文档知识，Memory 处理用户经历、偏好、事件、画像。
3. **Neo4j 四层溯源图谱**：来源 → 片段 → 陈述 → 实体，这比单纯实体关系图更适合解释“这条记忆从哪里来的”。
4. **异步任务链路**：文档解析、图片描述、记忆萃取、社区聚类走 Celery。
5. **Agent 工具编排**：知识库、记忆、联网作为 tools，让模型自主选择。
6. **多租户隔离**：业务表带 user_id，API Key 用 Fernet 加密，这些是很好的后端项目细节。([GitHub][1])

但你不要照抄 Comet 的产品形态。Comet 更像“个人知识库 + AI 助手”，简历含金量容易被面试官理解成“又一个 RAG 知识库”。

---

### MemoryBear：适合参考“记忆生命周期 + 服务化 API + 异步队列架构”

MemoryBear 的定位是 “Perceive · Extract · Associate · Forget”，强调从感知、抽取、关联到遗忘的完整生命周期。它的 README 明确说自己不是静态知识存储，而是 memory encoding、knowledge consolidation、forgetting 的动态系统。([GitHub][3])

它的核心功能包括语义解析、三元组抽取、时间锚定、Neo4j 图存储、ES 关键词 + 语义向量混合检索、记忆强度 + 时间衰减的遗忘机制、定时 reflection、一套 FastAPI 管理 API 和服务 API。([GitHub][3])

MemoryBear 的异步架构也很值得参考：它把 Celery 拆成 memory_tasks、document_tasks、periodic_tasks 三类队列，分别处理高并发记忆读写、CPU-bound 文档解析和定时反思任务。([GitHub][3])

更有价值的是它的代码结构。MemoryBear 的 core 下有 agent、memory、moderation、permissions、rag、tools、workflow、quota、security、transaction_monitor、uow 等模块，说明它不是单纯 demo，而是往服务化、权限、配额、事务和工作流方向扩展。([GitHub][4]) 其 memory 模块内部又拆了 agent、analytics、llm_tools、models、ontology_services、pipelines、read_services、storage_services 等子目录。([GitHub][5])

MemoryBear 的 `MemoryService` 也很值得看：它把记忆模块设计成统一 Facade，外部调用方只依赖 MemoryService；职责包括检查 memory.enabled 门禁、把消息写入 memory_messages 表、分派给 SlidingWindowScheduler，而具体业务逻辑继续下沉到 pipeline/engine/repository。([GitHub][6])

**你可以重点学 MemoryBear 的这些东西：**

1. **MemoryService Facade**：所有外部系统只调用统一入口，内部再分派 write/read/reflection。
2. **Sliding Window Scheduler**：不是每条消息都立刻萃取，而是候选池 + 窗口调度 + 空闲 flush。
3. **Memory enabled 门禁**：应用级、会话级、用户级 memory 开关。
4. **三队列异步架构**：memory、document、periodic 分开，避免 CPU-bound 和 IO-bound 任务互相拖垮。
5. **遗忘与反思机制**：usage frequency、association activity、time decay、daily reflection。
6. **API 分层**：管理 API 给后台配置，服务 API 给 agent/workflow 调用。
7. **权限、配额、安全、事务监控**：这些都是简历项目里很容易讲出“工程性”的地方。

不过也要注意：MemoryBear 很大，如果你照着全做，会变成“什么都有，但每个都不深”。简历项目最好抓住一个更尖锐的主题。

---

## 2. 我建议你的项目不要叫“知识库”，而叫“Memory Runtime”

你最适合做的是：

```text
Agent Memory Runtime
= MemoryService + State Tree + Step Retrieval + Admission Gate + Profiler
```

也就是把 Memory 从一个数据库功能，升级成 Agent Loop 里的运行时组件。

最终对外可以这样描述：

> 设计并实现一个面向长程 LLM Agent 的 Memory Runtime，将传统“向量检索 + prompt 注入”升级为 step-aware retrieval、execution-state-aware context construction、memory admission gate 和 phase-aware profiler；支持对多轮任务中的记忆写入、检索、压缩、冲突、遗忘、工具调用影响进行追踪和评估。

这句话比“我做了一个 AI 知识库”强很多。

---

## 3. 完整模块设计

### 总体架构

```text
┌──────────────────────────────┐
│ Agent / LangGraph / OpenClaw │
└──────────────┬───────────────┘
               │ trace / message / tool call
               ▼
┌──────────────────────────────┐
│ Memory Gateway / SDK          │
│ - write_event                 │
│ - retrieve_context            │
│ - commit_step                 │
│ - rollback_branch             │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ Memory Runtime Core           │
│ 1. Session & State Tree        │
│ 2. Write Pipeline              │
│ 3. Retrieval Controller        │
│ 4. Admission Gate              │
│ 5. Conflict Resolver           │
│ 6. Reflection / Forgetting     │
│ 7. Profiler                    │
└───────┬─────────┬────────────┘
        │         │
        ▼         ▼
┌────────────┐ ┌───────────────┐
│ PostgreSQL │ │ Redis / Queue │
│ metadata   │ │ async tasks   │
└────────────┘ └───────────────┘
        │         │
        ▼         ▼
┌────────────┐ ┌───────────────┐
│ Neo4j      │ │ Elasticsearch │
│ graph mem  │ │ vector + BM25 │
└────────────┘ └───────────────┘
        │
        ▼
┌──────────────────────────────┐
│ Dashboard / Evaluation        │
│ - trace replay                │
│ - token / latency / recall    │
│ - memory hit / utilization    │
│ - conflict / safety metrics   │
└──────────────────────────────┘
```

技术栈可以直接选：

| 层        | 技术                                    |
| -------- | ------------------------------------- |
| 后端       | FastAPI + SQLAlchemy + Alembic        |
| 异步任务     | Celery + Redis                        |
| 元数据      | PostgreSQL                            |
| 图记忆      | Neo4j                                 |
| 混合检索     | Elasticsearch vector + BM25           |
| Agent 编排 | LangGraph 或你自己的轻量 Agent Loop          |
| LLM 适配   | OpenAI-compatible client              |
| 前端可选     | React + Ant Design + ECharts / X6     |
| 可观测性     | 自研 trace 表 + dashboard，后续可接 LangSmith |

---

## 4. 核心模块拆解

### 模块一：Memory Gateway / SDK

这是整个项目的入口，类似 MemoryBear 的 MemoryService Facade。MemoryBear 的设计里，外部 controller、Celery、Agent、Workflow MemoryWriteNode 都只依赖 MemoryService，而 MemoryService 再调用 Pipeline。([GitHub][6])

你也应该这样设计：

```python
class MemoryRuntime:
    async def write_event(self, event: AgentEvent) -> WriteResult:
        ...

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        ...

    async def commit_step(self, step: AgentStep) -> None:
        ...

    async def rollback_branch(self, branch_id: str) -> None:
        ...

    async def profile_run(self, run_id: str) -> RunProfile:
        ...
```

Agent 侧只知道这几个 API，不关心 Neo4j、ES、Postgres、Celery 的细节。

这个模块的简历价值是：**统一 Agent Memory 接入层，屏蔽存储、检索、调度和异步写入细节。**

---

### 模块二：Agent Trace Collector

你不能只存对话消息，要存 Agent 执行过程。

建议事件模型如下：

```text
AgentEvent
- event_id
- run_id
- session_id
- user_id
- step_id
- parent_step_id
- role: user / assistant / tool / system
- event_type:
  - message
  - thought
  - tool_call
  - tool_result
  - memory_read
  - memory_write
  - error
  - branch_start
  - branch_end
- content
- tool_name
- tool_args_digest
- status: success / failed / cancelled
- created_at
```

这点很关键。普通记忆系统只记“用户说了什么”，而你的项目要记“Agent 做了什么、哪个分支成功、哪个分支失败、哪些记忆影响了工具调用”。

这就是你和 Comet/MemoryBear 的差异。Comet 更偏个人知识库和图谱记忆，MemoryBear 更偏记忆生命周期；你要强调 **agent runtime trace**。

---

### 模块三：Execution State Tree

这是项目最核心的亮点，参考 MAGE，但不必完整复现论文。

MAGE 的核心观点是：传统 memory 按语义相似度组织历史，会把有效轨迹和错误轨迹混在一起；它提出用层级状态树维护 long-horizon agent 的执行状态，通过 Grow、Compress、Maintain、Revise 四类操作管理 active path。([arXiv][7])

你可以实现一个工程版：

```text
StateNode
- node_id
- run_id
- parent_id
- node_type:
  - root
  - subgoal
  - step
  - tool_call
  - recovery
- status:
  - active
  - completed
  - failed
  - abandoned
- summary
- raw_event_ids
- memory_refs
- token_cost
- created_at
- updated_at
```

状态树的规则：

1. 每个 agent run 有一棵 tree。
2. 当前上下文只从 active root-to-current path 构造。
3. failed branch 默认不进入 prompt。
4. completed subgoal 被压缩成 summary。
5. rollback 时从某个 node 开新 branch。
6. 记忆检索时优先检索 active path 相关 memory。

这部分是你简历里最能讲清楚的创新点：

> 传统 memory 基于语义相似度检索，容易把失败分支、过期信息和当前状态混合。我引入 execution state tree，将 agent trace 组织为 active path / failed branch / completed subgoal，并在构造上下文时只注入当前有效执行路径，从而降低长任务中的状态污染。

---

### 模块四：Write Pipeline

这一部分参考 Comet 和 MemoryBear。

Comet 的 memory 系统包括预处理、三元组萃取、向量化、去重、事件萃取、图谱检索、社区聚类等阶段。([GitHub][8]) MemoryBear 也强调从非结构化对话/文档中抽取 declarative information、triples、temporal anchoring 和 summaries。([GitHub][3])

你可以设计成：

```text
Write Pipeline
1. Candidate Buffer
   - 收集最近 N 条 AgentEvent
   - Redis active key 判断会话是否空闲

2. Chunk / Window
   - 按时间窗口、step、subgoal 切块
   - 区分 user fact / agent state / tool evidence

3. Memory Extraction
   - fact: 用户偏好、约束、身份、长期需求
   - event: 某时间发生过什么
   - state: 当前任务进展、决策、失败原因
   - skill: 某类任务的成功经验

4. Dedup & Merge
   - exact hash
   - semantic similarity
   - entity-level merge
   - conflict detection

5. Storage
   - Postgres 存 metadata
   - ES 存 text + embedding + BM25
   - Neo4j 存 entity / event / relation / provenance

6. Async Reflection
   - 定时合并
   - 过期检查
   - 低价值记忆降权
```

一个很好的分类是把记忆分成四类：

| 类型                   | 例子                 | 生命周期          |
| -------------------- | ------------------ | ------------- |
| Profile Memory       | 用户偏好、长期身份、稳定约束     | 长期，低频更新       |
| Episodic Memory      | 某次任务、某次对话、某个事件     | 中期，可摘要        |
| Procedural Memory    | 某类任务怎么做、失败经验       | 长期，高价值        |
| Working State Memory | 当前 run 的状态、工具结果、分支 | 短期，随 run 结束压缩 |

这比单纯“事实三元组”更适合 Agent Infra。

---

### 模块五：Retrieval Controller

这一部分参考 MRAgent 和 AdaMEM。

MRAgent 批评静态 retrieve-then-reason，提出让 LLM reasoning 融入 memory access，通过 Cue-Tag-Content 图和 active reconstruction 迭代探索、剪枝检索路径。([arXiv][9]) AdaMEM 批评只在 episode 开头检索记忆，提出 test-time adaptive memory，让 agent 在长任务展开过程中动态生成短期策略记忆并适配当前步骤。([arXiv][10])

工程上你不需要搞复杂训练，可以做一个轻量版本：

```text
Retrieval Controller
1. Query Planner
   - 从当前 step、active state path、tool intention 生成检索 query

2. Candidate Retrieval
   - ES vector top-k
   - BM25 top-k
   - Neo4j neighbor expansion
   - recent active path memory

3. Contextual Rerank
   - task relevance
   - state relevance
   - recency
   - confidence
   - source reliability

4. Iterative Reconstruction
   - 第一跳找 cue
   - 第二跳找 tag/entity
   - 第三跳找 content/evidence
   - 每跳受 token budget 限制

5. Context Packing
   - profile first
   - active state second
   - evidence third
   - noisy memory excluded
```

检索请求结构可以这样设计：

```json
{
  "run_id": "r1",
  "step_id": "s12",
  "query": "下一步应该调用哪个部署工具？",
  "task_intent": "tool_selection",
  "active_state_path": ["root", "subgoal_2", "step_12"],
  "allowed_memory_types": ["procedural", "episodic", "state"],
  "token_budget": 1200,
  "safety_level": "normal"
}
```

简历上可以写：

> 实现 step-aware retrieval controller，根据当前 agent step、active state path、tool intention 动态规划检索策略，融合向量召回、BM25、图邻居扩展与短期状态记忆，并基于 token budget 进行上下文裁剪。

---

### 模块六：Memory Admission Gate

这是安全和工程亮点，参考 MemGate。

MemGate 的核心观点是：相似 memory 不一定适合注入上下文，长期记忆会成为 durable control channel，可能导致 cross-domain leakage、tool-call drift、memory-induced jailbreak 等问题；它把 memory search 视为 trust boundary，在 vector store 和 LLM 之间插入 query-conditioned gate。([arXiv][11])

你不需要训练 9M 模型，可以做规则 + LLM 小判别器 + metadata gate：

```text
Admission Gate Score
= relevance_score
+ state_match_score
+ permission_score
+ freshness_score
- conflict_penalty
- safety_risk_penalty
- failed_branch_penalty
```

过滤规则：

| 场景                 | 策略                   |
| ------------------ | -------------------- |
| 记忆属于失败分支           | 默认不注入，只作为 warning    |
| 记忆来自别的 workspace   | 直接拒绝                 |
| 记忆和当前任务 domain 不一致 | 降权                   |
| 记忆包含工具参数建议         | 提高安全审查等级             |
| 新旧事实冲突             | 交给 conflict resolver |
| 用户明确要求不要记住         | 不写入长期 memory         |

这部分非常适合面试讲，因为它连接了 memory 和 tool safety。

---

### 模块七：Conflict Resolver / Version Manager

这部分不用做太复杂，但一定要有。

建议每条 memory 都有：

```text
MemoryItem
- memory_id
- user_id
- workspace_id
- type
- content
- subject
- predicate
- object
- valid_time_start
- valid_time_end
- transaction_time
- confidence
- source_event_id
- source_run_id
- status: active / dormant / archived / superseded / conflicted / quarantined / pinned / deleted
```

冲突处理规则：

1. 同 subject + predicate，但 object 不同 → conflict candidate。
2. 有明确时间的新事实覆盖旧事实。
3. 没有时间的新事实不直接覆盖，标记为 uncertain。
4. 用户显式纠正优先级最高。
5. tool result 高于 assistant 口头推断。
6. failed branch 里的事实不能覆盖 completed branch 的事实。

例子：

```text
旧记忆：用户项目使用 Node.js
新记忆：用户说“这个项目以后用 Bun，不用 Node.js”
处理：
- 新增 Bun 记忆 active
- 旧 Node.js 标记 superseded
- 保留 provenance，允许解释“之前是 Node.js，后来改为 Bun”
```

这就是你之前问的“如果 bun 而不是 node，这种 memory 怎么处理”的工程答案。

---

### 模块八：Reflection / Forgetting

这部分参考 MemoryBear。MemoryBear 里有记忆强度、时间衰减、usage frequency、association activity、dormancy → decay → clearance 的生命周期，还有定时 reflection 做一致性检查、价值评估、关联优化。([GitHub][3])

但 MemTrace 不应该用单一 `memory_strength` 直接决定“保留、删除、注入 prompt”。更合理的做法是拆成多维评分，再按场景决策：

```text
value_score      # 这条记忆有没有长期价值
freshness_score  # 这条记忆是否仍然新鲜
trust_score      # 这条记忆是否可信
risk_score       # 这条记忆是否危险
```

其中：

```text
value_score =
  0.35 * normalized_usage
+ 0.30 * task_success_contribution
+ 0.20 * user_pin
+ 0.15 * procedural_reuse_potential

freshness_score = exp(-age_days / tau(memory_type))

trust_score =
  0.35 * source_reliability
+ 0.25 * extraction_confidence
+ 0.20 * provenance_quality
+ 0.20 * branch_validity

risk_score =
  0.30 * conflict_severity
+ 0.25 * rejection_rate
+ 0.20 * failed_branch_penalty
+ 0.15 * tool_sensitive_penalty
+ 0.10 * cross_domain_penalty
```

不同 memory 类型使用不同衰减速度：

| Memory 类型            | tau      | 说明                  |
| -------------------- | -------- | ------------------- |
| Working State Memory | 1 day    | 当前 run 状态，任务结束后快速衰减 |
| Episodic Memory      | 30 days  | 对话、任务、PR 等中期事件     |
| Profile Memory       | 180 days | 用户偏好、稳定约束，慢衰减      |
| Procedural Memory    | 365 days | 可复用流程与经验，慢衰减       |
| Tool Evidence Memory | 14 days  | API 行为、repo 结构等依环境变化 |

然后拆成三类决策：

```text
retrieval_score =
  0.35 * semantic_relevance
+ 0.25 * state_match_score
+ 0.15 * freshness_score
+ 0.15 * trust_score
- 0.25 * risk_score
- failed_branch_penalty

retention_score =
  value_score * trust_score * freshness_score * policy_multiplier
  - risk_score

reflection_priority =
  0.30 * conflict_severity
+ 0.25 * procedural_reuse_potential
+ 0.20 * duplication_score
+ 0.15 * compression_gain
+ 0.10 * task_success_contribution
```

其中 `retention_score` 只用于 active / dormant / archived 的状态迁移参考，不能直接触发永久删除。永久删除必须来自用户删除、合规策略或明确过期策略。

生命周期与状态机：

```text
active → dormant → archived → deleted
         ↘ superseded / conflicted / quarantined / pinned
```

策略示例：

| 条件              | 动作          |
| --------------- | ----------- |
| 高价值、高可信         | active      |
| user_pin = true | pinned，不自动删除 |
| 低访问、无冲突         | dormant     |
| 长期不用、可追溯        | archived    |
| 被明确覆盖           | superseded  |
| 与当前事实冲突         | conflicted  |
| 高风险或工具敏感        | quarantined |
| 用户要求删除          | deleted     |

定时任务：

| 任务                       | 频率        | 作用        |
| ------------------------ | --------- | --------- |
| summarize_completed_runs | 每次 run 结束 | 压缩长期轨迹    |
| dedup_memory             | 每天        | 合并重复事实    |
| score_memory             | 每天        | 计算 value / freshness / trust / risk |
| decay_memory             | 每天        | 按类型衰减低价值记忆 |
| conflict_scan            | 每天        | 找矛盾事实     |
| quarantine_memory         | 每天        | 隔离高风险、失败分支、工具敏感记忆 |
| graph_community          | 每周        | 重建实体社区    |
| profile_refresh          | 每周        | 生成用户画像摘要  |

这部分不需要做得很学术，但要能展示：检索排序、保留策略、反思优先级是三套不同决策；failed branch memory 默认不进入 active context；user-pinned memory 不自动衰减；superseded memory 保留版本和 provenance；high-risk memory 进入 quarantine；scheduler 每次修改状态都记录 audit log。

---

### 模块九：Profiler / Evaluation Dashboard

这个是我最建议你做的亮点。因为很多 memory 项目有图谱、有检索、有前端，但很少有**memory workload profiler**。

Agent Memory characterization 这篇论文提出要从系统层面对 agent memory workload 做画像，并把系统分成 long-context memory、flat RAG memory、structure-augmented RAG memory、agentic control flow 等范式，同时关注 construction、retrieval、generation 等阶段。([arXiv][12])

你的 profiler 可以记录：

| 阶段         | 指标                           |
| ---------- | ---------------------------- |
| Write      | 萃取耗时、LLM 调用次数、写入条数、去重率       |
| Retrieve   | ES 耗时、Neo4j 耗时、候选数、rerank 耗时 |
| Gate       | 通过数、拒绝数、拒绝原因                 |
| Context    | 注入 token、压缩率、active path 占比  |
| Generation | 输出 token、延迟、工具调用次数           |
| Quality    | 命中正确记忆、是否引用错误记忆、任务成功率        |
| Safety     | 跨域泄漏、失败分支污染、工具参数漂移           |

Dashboard 页面可以有四个图：

1. **Run Trace Timeline**：每一步 tool call / memory read / memory write。
2. **Memory Flow Sankey**：候选记忆 → gate → context → answer。
3. **Cost Breakdown**：construction / retrieval / generation token 与 latency。
4. **State Tree Viewer**：active path、failed branch、compressed subgoal。

这比做一个炫酷知识图谱更有简历价值。

---

## 5. 数据表设计

### PostgreSQL 核心表

```text
users
workspaces
agent_runs
agent_steps
agent_events
state_nodes
memory_items
memory_versions
memory_access_logs
memory_gate_logs
memory_conflicts
memory_profiles
eval_cases
eval_results
```

### memory_items

```text
memory_id
user_id
workspace_id
memory_type
content
summary
subject
predicate
object
source_event_id
source_run_id
source_state_node_id
confidence
importance
value_score
freshness_score
trust_score
risk_score
retention_score
reflection_priority
status
valid_time_start
valid_time_end
created_at
updated_at
```

### state_nodes

```text
node_id
run_id
parent_id
node_type
status
goal
summary
raw_event_ids
memory_refs
branch_reason
token_cost
created_at
updated_at
```

### memory_access_logs

```text
access_id
run_id
step_id
query
retrieval_strategy
candidate_count
accepted_count
rejected_count
token_budget
actual_tokens
latency_ms
created_at
```

### memory_gate_logs

```text
gate_id
access_id
memory_id
relevance_score
state_match_score
freshness_score
safety_score
final_score
decision
reject_reason
```

---

## 6. 具体开发步骤

### 第一阶段：7 天做出最小可用版本

目标：**能跑通 Agent → 写入 trace → 构建 state tree → 检索 memory → 返回上下文。**

任务：

1. 搭 FastAPI 项目骨架。
2. PostgreSQL 建表：run、step、event、state_node、memory_item。
3. 实现 MemoryRuntime Facade。
4. 实现 `write_event()`。
5. 实现简单 state tree：root → step → tool_call。
6. 实现简单 memory extraction：先用 LLM 抽 JSON。
7. 实现 ES vector + BM25 检索。
8. 实现一个 demo agent：多步骤任务，例如“帮我规划一个项目实现路线，然后根据前面选择继续执行”。

验收标准：

```text
- 能记录每轮 Agent step
- 能把用户偏好/约束抽成 memory
- 下一轮能按 query 检索出来
- 能展示一次 run 的 trace
```

---

### 第二阶段：第 2–3 周做出简历亮点

目标：**状态树 + step-level retrieval + gate。**

任务：

1. 加 active path context builder。
2. 支持 failed branch 隔离。
3. 支持 completed subgoal summary。
4. 检索时加入 state_path filter。
5. 做 admission gate。
6. 做 memory_access_logs 和 gate_logs。
7. 加一个 benchmark 脚本，比较：

   * no memory
   * vector memory
   * state-aware memory
   * state-aware + gate

验收标准：

```text
- 失败分支不会污染后续回答
- 当前 step 能动态检索不同 memory
- gate 能拒绝跨 workspace / failed branch / stale memory
- 有一组可复现评测结果
```

---

### 第三阶段：第 4–5 周做 profiler 和 dashboard

目标：**让项目看起来像 Agent Infra，而不是 demo。**

任务：

1. Run timeline 页面。
2. State tree 可视化页面。
3. Memory access 表格。
4. Token / latency breakdown。
5. Memory hit / reject / utilization 统计。
6. Trace replay：给定 run_id 重放一次 memory retrieval。
7. README 写清楚架构图、模块图、评测结果。

验收标准：

```text
- 面试时可以打开 dashboard 展示一次完整 agent run
- 能看到每一步用了哪些 memory、拒绝了哪些 memory、花了多少 token
- 能讲清楚你的系统为什么比普通 RAG memory 更稳
```

---

### 第四阶段：第 6–8 周增强工程性

目标：**补齐生产级细节。**

任务：

1. Celery 异步写入 pipeline。
2. Redis active conversation key。
3. idle flush。
4. dedup task。
5. reflection task。
6. conflict resolver。
7. API Key / JWT / workspace 权限。
8. Docker Compose 一键启动。
9. 单元测试 + 集成测试。
10. 压测脚本。

这阶段做完，项目就比较完整了。

---

## 7. 推荐你最终做哪些功能，不做哪些功能

### 必做

| 功能                    | 原因                      |
| --------------------- | ----------------------- |
| Agent trace collector | 和普通知识库拉开差异              |
| Execution state tree  | 简历最大亮点                  |
| Step-level retrieval  | 对齐 AdaMEM/MRAgent 趋势    |
| Admission gate        | 对齐 memory safety，工程含金量高 |
| Profiler              | 面试展示效果最好                |
| Async write pipeline  | 后端工程能力                  |
| Conflict resolver     | 长期记忆必须有                 |
| Docker Compose        | 可复现                     |

### 可以做，但不要优先

| 功能             | 原因                  |
| -------------- | ------------------- |
| 图片 OCR         | Comet 有，但和你项目主线关系不大 |
| 音乐推荐/情绪陪伴      | 容易跑偏                |
| 大而全的知识图谱前端     | 好看但不一定有含金量          |
| 复杂社区聚类         | 可以后补                |
| 训练 MemGate 小模型 | 不冲论文，没必要            |
| LoCoMo 全量评测    | 可以做小规模，不必完整刷榜       |

---

## 8. 你可以参考的具体项目内容

### 从 Comet 学

1. `api/app/core/memory` 的目录拆法：preprocessing、extraction、retrieval、clustering、prompts。([GitHub][2])
2. `api/app/core/agent` 的工具编排结构：orchestrator、tools、web_search、prompts。([GitHub][13])
3. 四存储架构：PostgreSQL + Elasticsearch + Neo4j + Redis。([GitHub][1])
4. 文档写法：README 里把核心功能、技术栈、架构、启动步骤、目录结构、开发约定都写清楚。([GitHub][1])

### 从 MemoryBear 学

1. `MemoryService` Facade 设计。([GitHub][6])
2. 三队列 Celery：memory_tasks、document_tasks、periodic_tasks。([GitHub][3])
3. memory 生命周期：extract、associate、forget、reflect。([GitHub][3])
4. Graph-first + hybrid search 架构。([GitHub][3])
5. 管理 API 与服务 API 分离。([GitHub][3])
6. core 下 permissions、moderation、quota、transaction_monitor、workflow 等工程模块。([GitHub][4])

### 从论文趋势学

1. MRAgent：不要只 top-k 检索，要让 reasoning 参与 memory access。([arXiv][9])
2. MAGE：不要只按语义组织历史，要按执行状态组织 agent trace。([arXiv][7])
3. AdaMEM：不要只在任务开始检索，要 step-level 动态检索。([arXiv][10])
4. MemGate：memory search 是 trust boundary，不是所有相似内容都能进 prompt。([arXiv][11])
5. Agent Memory characterization：要做 phase-aware profiler，拆 construction、retrieval、generation 的系统成本。([arXiv][12])

---

## 9. 最终项目 README 应该怎么写

你的 README 一定不要写成：

> 基于 FastAPI + Neo4j + Elasticsearch 的 AI 记忆系统。

这太普通。

建议写成：

```text
# MemTrace: State-Aware Memory Runtime for Long-Horizon LLM Agents

MemTrace is a memory runtime layer for long-horizon LLM agents.
It upgrades traditional vector-memory retrieval into a state-aware,
step-aware and safety-aware runtime mechanism.

Core features:
- Agent trace collector for messages, tool calls, tool results and failures
- Execution state tree for active-path context construction
- Step-level adaptive memory retrieval
- Hybrid memory store with PostgreSQL, Elasticsearch and Neo4j
- Memory admission gate for stale, unsafe and branch-invalid memories
- Conflict resolver with versioned memory records
- Phase-aware profiler for memory construction, retrieval and generation
- Dashboard for trace replay, state tree visualization and memory flow analysis
```

中文项目介绍可以写：

```text
MemTrace 是一个面向长程 LLM Agent 的状态感知记忆运行时系统。
系统将传统“向量召回 + Prompt 注入”的记忆模式升级为
“执行状态树 + step-level 检索 + 记忆准入门控 + 性能画像”的运行时机制。
```

---

## 10. 简历项目描述可以这样写

你最后简历上可以写：

> **MemTrace：面向长程 LLM Agent 的状态感知记忆运行时系统**
> 设计并实现 Agent Memory Runtime，将传统向量记忆检索升级为基于执行状态树的 step-aware memory access。系统采集 Agent 多轮任务中的 message、tool call、tool result、error 和 branch trace，构建 active path / failed branch / completed subgoal 状态树，并在上下文构造时隔离失败分支、压缩完成子目标，降低长任务状态污染。
> 实现混合记忆存储与检索链路，基于 PostgreSQL 管理元数据、Elasticsearch 支持向量 + BM25 召回、Neo4j 维护实体/事件/状态关联图，并通过 Admission Gate 对 stale、cross-domain、failed-branch 和 tool-sensitive memory 进行准入过滤。
> 构建 phase-aware profiler，对 memory construction、retrieval、gate、context packing、generation 阶段的 token、latency、候选数、通过率、命中率和工具调用影响进行可视化追踪，支持 run replay 和 state tree dashboard，用于评估不同 memory 策略的成本-效果表现。

这个描述会比“做了一个 RAG 知识库”强很多。

---

## 11. 最推荐的最终交付物

你最后应该有这些东西：

1. **GitHub repo**

   * README 架构图
   * 快速启动
   * 模块说明
   * benchmark 结果
   * demo GIF / 截图

2. **Docker Compose**

   * api
   * postgres
   * redis
   * elasticsearch
   * neo4j
   * worker
   * frontend 可选

3. **Demo 场景**

   * 长程任务执行
   * 中途失败分支
   * 后续恢复
   * memory 检索
   * gate 拒绝错误记忆
   * profiler 展示成本

4. **评测脚本**

   * no memory
   * vector memory
   * state-aware memory
   * state-aware + gate

5. **技术博客**

   * 为什么 Agent Memory 不是简单 RAG
   * 为什么需要 execution state tree
   * 为什么 memory search 是 trust boundary
   * profiler 如何定位 memory 系统瓶颈

---

## 12. 最终建议

如果你只想做简历项目，我建议不要做 Comet/MemoryBear 那种“大而全个人知识库”。它们值得参考，但你应该提炼成一个更聚焦的系统：

> **一个 Agent Memory Runtime，而不是一个 AI 知识库。**

最小可行版本可以是：

```text
FastAPI + PostgreSQL + Redis + Elasticsearch + Neo4j
+
MemoryService Facade
+
Agent Trace Collector
+
Execution State Tree
+
Step-level Retrieval
+
Admission Gate
+
Profiler Dashboard
```

做到这个程度，就已经足够作为一个很有含金量的 Agent Infra 项目了。面试时你可以非常自然地往这些方向延展：

* Agent Harness 如何管理长期状态；
* Memory 如何和 tool calling 交互；
* 失败分支为什么不能进入上下文；
* 长程任务如何压缩 active path；
* memory search 为什么是安全边界；
* 如何评估 memory 的 token、latency、utilization；
* 为什么普通向量检索不足以支撑 production-grade agent。

[1]: https://github.com/lm041520/Comet "GitHub - lm041520/Comet · GitHub"
[2]: https://github.com/lm041520/Comet/tree/main/api/app/core/memory "Comet/api/app/core/memory at main · lm041520/Comet · GitHub"
[3]: https://github.com/SuanmoSuanyangTechnology/MemoryBear "GitHub - SuanmoSuanyangTechnology/MemoryBear: MemoryBear Equip AI with human-like memory capability · GitHub"
[4]: https://github.com/SuanmoSuanyangTechnology/MemoryBear/tree/main/api/app/core "MemoryBear/api/app/core at main · SuanmoSuanyangTechnology/MemoryBear · GitHub"
[5]: https://github.com/SuanmoSuanyangTechnology/MemoryBear/tree/main/api/app/core/memory "MemoryBear/api/app/core/memory at main · SuanmoSuanyangTechnology/MemoryBear · GitHub"
[6]: https://raw.githubusercontent.com/SuanmoSuanyangTechnology/MemoryBear/main/api/app/core/memory/memory_service.py "raw.githubusercontent.com"
[7]: https://arxiv.org/abs/2606.06090?utm_source=chatgpt.com "Beyond Semantic Organization: Memory as Execution State Management for Long-Horizon Agents"
[8]: https://github.com/lm041520/Comet/tree/main/api "Comet/api at main · lm041520/Comet · GitHub"
[9]: https://arxiv.org/abs/2606.06036?utm_source=chatgpt.com "Memory is Reconstructed, Not Retrieved: Graph Memory for LLM Agents"
[10]: https://arxiv.org/abs/2606.05684?utm_source=chatgpt.com "AdaMEM: Test-Time Adaptive Memory for Language Agents"
[11]: https://arxiv.org/abs/2606.06054?utm_source=chatgpt.com "Beyond Similarity: Trustworthy Memory Search for Personal AI Agents"
[12]: https://arxiv.org/html/2606.06448v1?utm_source=chatgpt.com "Agent Memory: Characterization and System Implications ..."
[13]: https://github.com/lm041520/Comet/tree/main/api/app/core/agent "Comet/api/app/core/agent at main · lm041520/Comet · GitHub"
