# MemTrace Architecture

> 项目定位：面向长程 LLM Agent 的状态感知记忆运行时与性能画像系统。  
> 核心目标：不要做“大而全的个人知识库”，而是实现一个可接入 Agent Loop 的 Memory Runtime，让 Agent 在多轮任务中可以可靠地写入、检索、过滤、压缩、回滚、评估 memory。

---

## 0. Executive Summary

MemTrace 的推荐架构是：

```text
MemTrace = Memory Gateway / SDK
         + Agent Trace Collector
         + Execution State Tree
         + Write Pipeline
         + Step-aware Retrieval Controller
         + Memory Admission Gate
         + Conflict / Version Manager
         + Reflection / Forgetting Scheduler
         + Phase-aware Profiler
         + Evaluation Dashboard
```

它和传统 RAG / 个人知识库的区别不在于“多接一个向量库”，而在于把 memory 作为 Agent Runtime 的一等组件：

1. **状态感知**：按 Agent 执行状态树组织 trace，区分 active path、failed branch、completed subgoal。
2. **步骤感知**：每个 step 都可以根据 task intent、tool intention、active state path 动态生成检索策略。
3. **安全感知**：把 memory search 视为 trust boundary，通过 admission gate 过滤过期、跨域、失败分支、工具敏感记忆。
4. **生命周期完整**：写入、去重、冲突、版本、反思、遗忘、归档可追踪。
5. **可观测可评估**：内建 profiler，按 construction、retrieval、gate、context packing、generation、maintenance 分阶段归因 token、latency、命中率和污染率。

最终项目在简历中的表达应是：

> MemTrace is a state-aware memory runtime for long-horizon LLM agents. It upgrades vector-memory retrieval into execution-state-aware context construction, step-level adaptive retrieval, memory admission gate, and phase-aware profiling.

---

## 1. 动机评估

### 1.1 为什么不做普通知识库

普通个人知识库 / RAG 项目常见形态是：文档入库、分块、embedding、向量检索、重排、拼 prompt、生成答案。这个方向工程上能跑通，但作为简历项目容易被理解为“又一个 RAG demo”。

MemTrace 更应该解决 Agent 场景下的 runtime 问题：

- Agent 任务是多步骤、多工具、多分支的，不只是一次问答。
- 失败分支、过期事实、错误反思如果被长期记住，会污染后续决策。
- 长程 Agent 需要知道“当前走到哪一步”，而不是只按语义相似度找历史文本。
- Memory 的价值需要被评估：到底节省了 token，提升了成功率，还是引入了错误？

因此本项目的主线不是“更大的知识库”，而是“更可靠的 Agent Memory Runtime”。

### 1.2 目标用户与典型场景

目标用户：

1. 正在构建长程 Agent 的开发者。
2. 需要追踪 Agent 记忆读写和工具调用影响的 infra / 平台工程师。
3. 需要演示 Agent 状态管理、记忆安全、可观测性的个人项目作者。

典型场景：

```text
用户让 Agent 完成一个多阶段任务：调研 → 规划 → 修改代码 → 运行测试 → 修复错误 → 总结。

MemTrace 需要记录：
- 每一步 message / tool call / tool result / error；
- 哪些事实被写入长期 memory；
- 当前 active path 是什么；
- 哪些失败分支被隔离；
- 每次回答前检索了哪些 memory；
- gate 为什么拒绝或放行某条 memory；
- memory 对 token、latency、任务成功率的影响。
```

### 1.3 成功标准

最小成功标准：

- 能接入一个 demo Agent。
- 能记录完整 Agent trace。
- 能构建 execution state tree。
- 能抽取并保存多类型 memory。
- 能在后续 step 做状态感知检索。
- 能通过 gate 隔离失败分支和跨 workspace 记忆。
- 能展示一次 run 的 trace、state tree、memory flow、token / latency breakdown。

简历级成功标准：

- 有可复现实验，对比 `no memory`、`vector memory`、`state-aware memory`、`state-aware + gate`。
- 能解释为什么普通向量检索不足以支撑 production-grade long-horizon agent。
- 能展示 profiler 如何定位 memory construction / retrieval / context packing 的成本瓶颈。

---

## 2. 外部项目与论文调研结论

### 2.1 Comet

Comet 更像“个人 AI 知识库 + 记忆助手”。它的价值在于完整工程骨架：FastAPI 分层、RAG 与 Memory 分离、PostgreSQL / Elasticsearch / Neo4j / Redis、多模态入库、图谱溯源、Agent 工具编排、SSE 与 Dashboard。

MemTrace 可借鉴：

- controller / service / repository / model / db 分层。
- RAG knowledge 与 user / agent memory 分离。
- 来源 → 片段 → 陈述 → 实体的 provenance 思路。
- 后台任务处理解析、抽取、聚类、图谱更新。

MemTrace 不应照搬：

- 不优先做文档、网页、图片、OCR 大而全入库。
- 不把项目定位成个人知识库。
- 不让炫酷图谱前端掩盖 Agent Runtime 主线。

### 2.2 MemoryBear

MemoryBear 的核心启发是记忆生命周期：Perceive、Extract、Associate、Forget。它还体现了服务化架构价值：MemoryService Facade、三类 Celery 队列、记忆强度、时间衰减、定时 reflection、权限、配额、事务监控。

MemTrace 可借鉴：

- 所有外部系统只依赖 MemoryService / MemoryRuntime Facade。
- 记忆写入不一定每条消息同步抽取，可以用候选池、滑动窗口、idle flush。
- 异步任务分队列，避免 CPU-bound 解析和 IO-bound memory 写入互相拖垮。
- 记忆强度、时间衰减、usage frequency、association activity。

MemTrace 应收敛：

- 只保留与 Agent Runtime 相关的生命周期能力。
- 文档解析、复杂社区聚类、完整后台管理不作为 MVP 主线。

### 2.3 Mem0

Mem0 是通用 Agent 记忆层，强调 SDK / API / CLI、自托管、云服务、多框架集成、语义 + BM25 + 实体 + 时间信号融合检索。

MemTrace 可借鉴：

- 把记忆层作为独立基础设施，而不是嵌在单个 Agent 内。
- 提供 Python SDK、HTTP API、CLI 三种开发者入口。
- 检索融合语义、关键词、实体、时间、metadata。
- 提供 Docker Compose、benchmark、集成示例。

MemTrace 需要补足：

- ADD-only 容易导致长期膨胀，因此必须有压缩、归档、冲突、过期策略。
- Memory 写入和检索需要可审计、可删除、可解释。

### 2.4 Letta / MemGPT

Letta 强调有状态 Agent、长期记忆、模型无关、memory blocks、tools、skills、subagents、Python / TypeScript SDK。

MemTrace 可借鉴：

- memory block 思路：human、persona、project、task、procedure。
- Agent 与 memory runtime 解耦。
- 模型无关，支持 OpenAI-compatible、Anthropic、本地模型。
- 让 Agent 可以显式管理一部分 memory，但 runtime 仍要有外部规则约束。

### 2.5 Zep / Graphiti

Zep 的重点是 end-to-end context engineering 与 temporal knowledge graph。Graphiti 通过 `valid_at` / `invalid_at` 表达事实何时有效、何时失效。

MemTrace 可借鉴：

- 事实必须带时间有效性，不要把所有 memory 视为永远有效。
- 当前事实、历史事实、失效事实要区分。
- 图谱适合表达实体、事件、关系、provenance，而不是替代所有存储。

### 2.6 LangMem

LangMem 适合 LangGraph / LangChain 生态，强调长期记忆、Agent 主动管理、后台整理、可插拔 store。

MemTrace 可借鉴：

- 记忆能力是可组合工具。
- 热路径实时记忆与后台异步整理分离。
- 存储接口抽象，便于从内存切到 Postgres / Vector / Graph。

### 2.7 论文趋势

结合 2026 年前后的 Agent Memory 调研和系统论文，关键趋势如下：

1. **长上下文不是长期记忆的通用解**：历史越长，prefill 成本越高，且 recall 不一定更好。
2. **Agent Memory 是 write-manage-read 闭环**：只做 retrieval 不够，写入和维护同样重要。
3. **从相似度检索走向任务 / 状态 / 因果相关检索**：当前 step、工具意图、执行状态会影响需要的记忆。
4. **结构化与图记忆提升多跳关系表达**：但 construction 成本更高，需要 profiler 量化。
5. **Memory search 是 trust boundary**：相似不代表应该注入，尤其是个人记忆、工具参数、跨域信息。
6. **Profiler 应成为架构核心**：memory construction、retrieval、generation、maintenance 需要分阶段归因成本。

---

## 3. 技术路线评估

### 3.1 推荐技术栈

| 层 | 推荐 | 原因 |
|---|---|---|
| 后端 API | Python + FastAPI | Agent / LLM / embedding / LangChain / LangGraph 生态成熟，开发效率高 |
| ORM / Migration | SQLAlchemy 2.x + Alembic | 类型化、异步支持、迁移标准化 |
| 元数据存储 | PostgreSQL | 事务、版本、日志、权限、JSONB、索引能力强 |
| 短期缓存 / 锁 / 队列 broker | Redis | active session key、幂等锁、Celery broker、热点缓存 |
| 异步任务 | Celery | Python 生态稳定，便于拆 memory / maintenance / eval 队列 |
| 向量 + BM25 | Elasticsearch 或 OpenSearch | 兼容 BM25、dense vector、filter、profile；生产理解度高 |
| 图存储 | Neo4j | 适合实体、事件、关系、provenance、邻居扩展 |
| Agent 编排 | 自研轻量 Agent Loop + LangGraph adapter | 主线是 Memory Runtime，不应被框架锁死 |
| LLM Client | OpenAI-compatible adapter | 方便接 OpenAI、Azure、DeepSeek、Qwen、Claude proxy、本地模型 |
| 前端 | React + TypeScript + Ant Design + ECharts / React Flow | Dashboard、timeline、state tree、memory flow 展示成熟 |
| 可观测性 | 自研 profile tables + OpenTelemetry optional | 先保证 memory-specific 指标，再对接通用 tracing |
| 部署 | Docker Compose | 简历项目可复现；服务多但一键启动 |

### 3.2 语言适配分析

#### Python：推荐作为主语言

优点：

- LLM / Agent / embedding / RAG 生态最完整。
- FastAPI 能快速交付 API、OpenAPI、异步接口。
- Celery、SQLAlchemy、Neo4j、Elasticsearch 客户端成熟。
- 便于快速迭代 extraction、rerank、gate、eval。

缺点：

- 高并发 CPU-bound 任务性能一般。
- 类型约束弱于 Go / Rust。
- 长期需要注意任务隔离、连接池、异步阻塞。

结论：主后端使用 Python，配合严格类型、Pydantic schema、ruff / mypy / pytest 控制质量。

#### TypeScript：推荐作为前端与可选 SDK

优点：

- 前端必选。
- 很多 Agent 应用在 Node / TS 生态，提供 TS SDK 有利于接入。

结论：前端使用 TS；SDK 第一阶段先做 Python，第二阶段补 TS。

#### Go：适合未来高性能 Gateway / Worker

优点：

- 高并发、低内存、部署简单，适合 API Gateway、trace ingestion、collector。

缺点：

- LLM / Agent 原型生态不如 Python。

结论：不作为 MVP 主语言。后续如果 ingestion QPS 上来，可把 Trace Collector / Gateway 单独用 Go 重写。

#### Rust：适合未来性能内核，但不建议 MVP

优点：

- 性能、安全、适合 embedding index adapter、日志压缩、profile analyzer。

缺点：

- 开发周期较长，LLM 原型效率不如 Python。

结论：不建议初期使用。

### 3.3 存储路线评估

#### PostgreSQL-only MVP

优点：简单、易部署、事务一致、可用 pgvector。  
缺点：BM25、复杂图检索、profile 分析能力受限。  
适用：最小原型。

#### PostgreSQL + Elasticsearch

优点：满足 metadata + hybrid retrieval，足以支撑 MVP 评测。  
缺点：图关系表达弱。  
适用：第一阶段推荐。

#### PostgreSQL + Elasticsearch + Neo4j

优点：完整表达 metadata、hybrid retrieval、provenance graph、state / entity relation。  
缺点：部署和一致性复杂。  
适用：最终架构。

推荐路径：

```text
Phase 1: PostgreSQL + pgvector 或 Elasticsearch 二选一
Phase 2: PostgreSQL + Elasticsearch
Phase 3: 引入 Neo4j 做 graph memory 与 provenance
```

---

## 4. 总体架构

```text
┌────────────────────────────────────────────────────────────────────┐
│                         Agent / Application                         │
│  LangGraph / custom Agent Loop / coding agent / workflow service     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ SDK / HTTP / OpenTelemetry-like event
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                         Memory Gateway                              │
│  - auth / workspace / quota                                          │
│  - write_event                                                       │
│  - retrieve_context                                                  │
│  - start_step / finish_step / rollback_branch                        │
│  - profile_run / replay_run                                          │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                         Runtime Core                                 │
│ ┌──────────────────────┐ ┌──────────────────────┐                   │
│ │ Agent Trace Collector│ │ Execution State Tree │                   │
│ └──────────────────────┘ └──────────────────────┘                   │
│ ┌──────────────────────┐ ┌──────────────────────┐                   │
│ │ Write Pipeline       │ │ Retrieval Controller │                   │
│ └──────────────────────┘ └──────────────────────┘                   │
│ ┌──────────────────────┐ ┌──────────────────────┐                   │
│ │ Admission Gate       │ │ Conflict Manager     │                   │
│ └──────────────────────┘ └──────────────────────┘                   │
│ ┌──────────────────────┐ ┌──────────────────────┐                   │
│ │ Reflection Scheduler │ │ Phase-aware Profiler │                   │
│ └──────────────────────┘ └──────────────────────┘                   │
└───────────────┬──────────────────────┬─────────────────────────────┘
                │                      │
                ▼                      ▼
┌───────────────────────────┐  ┌──────────────────────────────────────┐
│ PostgreSQL                 │  │ Redis / Celery                       │
│ metadata / trace / logs    │  │ queues / active keys / locks         │
└───────────────┬───────────┘  └──────────────────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
┌────────────────┐ ┌────────────────┐
│ Elasticsearch  │ │ Neo4j          │
│ vector + BM25  │ │ graph memory   │
└────────────────┘ └────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                         Dashboard / Evaluation                       │
│  - Run timeline                                                      │
│  - State tree viewer                                                 │
│  - Memory flow                                                       │
│  - Token / latency / cost breakdown                                  │
│  - Retrieval replay                                                  │
│  - Benchmark comparison                                              │
└────────────────────────────────────────────────────────────────────┘
```

---

## 5. 核心设计原则

1. **Facade first**：外部系统只依赖 MemoryRuntime，不直接接触 ES / Neo4j / Celery。
2. **Trace first**：先记录事实，再做抽取；抽取错误可重跑，原始 trace 不丢。
3. **State-aware over similarity-only**：检索必须考虑 active path、branch status、step intent。
4. **Async by default, sync when required**：写入抽取默认异步；强一致需求可同步 flush。
5. **Provenance everywhere**：每条 memory 都能追溯到 source event、run、state node。
6. **Gate before prompt**：所有候选 memory 必须经过 admission gate 才能进入上下文。
7. **Profiler as runtime policy input**：profile 不只是看板，而是驱动降级、批处理、fallback。
8. **Portable adapters**：LLM、embedding、vector store、graph store、agent framework 都可替换。
9. **MVP 收敛**：先做 Agent trace、state tree、retrieval、gate、profiler，不做大而全文档知识库。

---

## 6. 模块设计

### 6.1 Memory Gateway / SDK

### 职责

- 对外暴露统一 API。
- 处理认证、workspace 隔离、配额、幂等、版本兼容。
- 将 Agent event 转换成内部 canonical schema。
- 屏蔽存储、队列、检索、图谱、profiler 细节。

### API 草案

```python
class MemoryRuntime:
    async def start_run(self, request: StartRunRequest) -> AgentRun:
        """创建一次 Agent run，并初始化 root state node。"""

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        """开启一个 step，并创建或绑定对应 state node。"""

    async def write_event(self, event: AgentEvent) -> WriteEventResult:
        """记录 Agent 事件，并触发可选异步抽取。"""

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        """结束 step，写入 success / failed / cancelled 状态并更新 state tree。"""

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        """按当前 step / state / intent 检索并组装上下文。"""

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        """从指定 state node 回滚并开启新分支。"""

    async def flush_session(self, session_id: str) -> FlushResult:
        """强制处理候选 buffer。"""

    async def profile_run(self, run_id: str) -> RunProfile:
        """返回分阶段性能画像。"""

    async def replay_retrieval(self, access_id: str) -> ReplayResult:
        """复现某次 memory retrieval。"""
```

### HTTP Endpoint 草案

```text
POST /v1/runs
POST /v1/steps/start
POST /v1/events
POST /v1/steps/finish
POST /v1/context/retrieve
POST /v1/branches/rollback
POST /v1/sessions/{session_id}/flush
GET  /v1/runs/{run_id}/profile
GET  /v1/runs/{run_id}/timeline
GET  /v1/runs/{run_id}/state-tree
GET  /v1/memories/{memory_id}
PATCH /v1/memories/{memory_id}
DELETE /v1/memories/{memory_id}
POST /v1/evals/run
```

### SDK 设计

第一阶段提供 Python SDK：

```python
from memtrace import MemTrace

mt = MemTrace(api_key="...", workspace_id="w1")

run = await mt.start_run(session_id="sess1", task="修复测试失败")
step = await mt.start_step(run_id=run.run_id, intent="debugging")

await mt.write_event(
    run_id=run.run_id,
    step_id=step.step_id,
    event_type="tool_call",
    content="call pytest",
    tool_name="bash",
)

await mt.finish_step(run_id=run.run_id, step_id=step.step_id, status="success")

ctx = await mt.retrieve_context(
    run_id=run.run_id,
    step_id=step.step_id,
    query="如何修复刚才的测试失败？",
    task_intent="debugging",
    token_budget=1200,
)
```

第二阶段补 TypeScript SDK，重点支持前端和 Node Agent。

---

### 6.2 Agent Trace Collector

### 职责

- 记录 Agent 多轮执行的原始事件。
- 支持 message、thought、tool_call、tool_result、memory_read、memory_write、error、branch_start、branch_end。
- 为 state tree、write pipeline、profiler 提供事实来源。

### AgentEvent Schema

```text
AgentEvent
- event_id: uuid
- tenant_id: string
- user_id: string
- workspace_id: string
- session_id: string
- run_id: string
- step_id: string
- parent_step_id: string | null
- state_node_id: string | null
- sequence_no: int
- event_source: sdk | http | langgraph | replay | import
- visibility: extractable | promptable | profiler_only | private
- raw_payload_ref: string | null
- redaction_status: none | redacted | digest_only | blocked
- causality_id: string | null
- role: user | assistant | tool | system | runtime
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
  - checkpoint
- content: text
- content_digest: string
- tool_name: string | null
- tool_args_digest: string | null
- status: pending | success | failed | cancelled
- token_input: int
- token_output: int
- latency_ms: int
- metadata: jsonb
- created_at: timestamp
```

### 设计要点

- `content_digest` 用于幂等与去重。
- `sequence_no` 是 run 内单调递增序号，用于修复异步写入时 `created_at` 不能严格排序的问题。
- `event_source` 标记事件来自 SDK、HTTP、LangGraph adapter、replay 还是导入。
- `visibility` 控制事件是否允许被 memory extraction 使用、是否允许进入 prompt、是否仅用于 profiler。
- `raw_payload_ref` 用于大 tool result 或压缩 blob，避免把大内容直接塞进 `content`。
- `redaction_status` 记录脱敏状态，避免 secret / token / tool args 误入 memory。
- `causality_id` 关联一次 LLM output 里的 memory read、tool call、tool result。
- 工具参数只默认存 digest；完整参数可加密存储或脱敏存储。
- `state_node_id` 可在 `finish_step` 后回填。
- event 不直接等于 memory。event 是事实日志，memory 是经过筛选、抽取、合并后的长期记录。

---

### 6.3 Execution State Tree

### 职责

- 将 Agent trace 组织为树，而不是线性对话。
- 支持 active path、failed branch、completed subgoal、recovery branch。
- 控制上下文构造时哪些状态可进入 prompt。

### StateNode Schema

```text
StateNode
- node_id: uuid
- tenant_id: string
- workspace_id: string
- run_id: string
- parent_id: uuid | null
- node_type: root | subgoal | step | tool_call | recovery | summary
- status: active | completed | failed | abandoned | rolled_back
- goal: text
- summary: text
- raw_event_ids: uuid[]
- memory_refs: uuid[]
- branch_reason: text | null
- failure_reason: text | null
- token_cost: int
- depth: int
- path: ltree/string
- created_at: timestamp
- updated_at: timestamp
```

### 状态规则

1. 每个 run 有一棵 state tree。
2. 当前上下文优先从 active root-to-current path 构造。
3. failed / abandoned branch 默认不进入上下文，只可作为 warning 或 debug evidence。
4. completed subgoal 被压缩成 summary node。
5. rollback 会将目标 node 之后的 path 标记为 rolled_back，并开启 recovery branch。
6. 检索 memory 时优先匹配 active path、相同 subgoal、相同 tool context。

### MVP 生成规则

MVP 阶段不依赖 LLM 自动推断复杂 subgoal，而是采用显式事件驱动：

```text
start_run       → 创建 root node
start_step      → 创建 step node，挂到当前 active node 下
write_event     → message / tool_call / tool_result 绑定到当前 step node
finish_step     → 将 step 标记 success / failed / cancelled
rollback_branch → 标记目标 node 之后的路径为 rolled_back，并创建 recovery node
```

第一版 State Tree 只实现：

```text
root
  ├── step_1
  │   └── tool_call_1
  ├── step_2
  │   └── tool_call_2
  ├── step_3_failed
  └── step_4_recovery
```

`subgoal` 与 `summary` 是 P2 能力；MVP 只要求能证明 failed branch isolation 与 active path context construction。

### Active Path Context Builder

输入：`run_id`, `current_step_id`, `token_budget`。  
输出：按优先级裁剪后的 state context。

优先级：

```text
1. 当前 step 的直接事件
2. active parent subgoal summary
3. 最近成功 tool result
4. unresolved error / blocker
5. completed subgoal summary
6. failed branch warning（默认不注入细节）
```

### 为什么这是核心亮点

传统 memory 按语义相似度组织历史，容易把失败轨迹和有效轨迹混在一起。Execution State Tree 将 Agent 历史变成状态管理问题，能显式隔离失败分支、压缩完成子目标、支持回滚和重放。

---

### 6.4 Write Pipeline

### 职责

- 将原始 AgentEvent 转换为长期 memory。
- 支持候选缓冲、窗口切分、LLM 抽取、去重、合并、冲突检测、索引写入。
- 平衡 freshness 与 latency。

### Pipeline

```text
1. Ingest Event
   - write raw event to PostgreSQL
   - append candidate to Redis buffer
   - mark active session key

2. Candidate Buffer
   - collect recent N events
   - group by run / step / state node
   - wait for idle flush or explicit flush

3. Window Builder
   - split by step, subgoal, time window
   - classify content: user fact / agent state / tool evidence / reflection candidate

4. Extraction
   - profile memory: user preferences, stable constraints
   - episodic memory: event / decision / conversation
   - procedural memory: reusable workflow / failure lesson
   - working state memory: current run progress / blocker

5. Normalize
   - canonical subject / predicate / object
   - temporal anchors
   - confidence / importance / sensitivity

6. Dedup & Merge
   - exact hash
   - semantic similarity
   - entity-level merge
   - version update

7. Conflict Detection
   - same subject + predicate + different object
   - time validity overlap
   - source priority comparison

8. Storage & Index
   - PostgreSQL metadata
   - Elasticsearch text + embedding + BM25
   - Neo4j entity / relation / provenance

9. Profile & Log
   - extraction latency
   - LLM calls
   - memories created / updated / rejected
```

### Memory 类型

| 类型 | 示例 | 生命周期 | 检索优先级 |
|---|---|---|---|
| Profile Memory | 用户偏好、长期身份、稳定约束 | 长期，低频更新 | 高 |
| Episodic Memory | 某次任务、某次对话、某个事件 | 中期，可摘要 | 中 |
| Procedural Memory | 某类任务怎么做、失败经验、工具流程 | 长期，高价值 | 高 |
| Working State Memory | 当前 run 状态、工具结果、分支 | 短期，run 后压缩 | 极高但局部 |
| Project Memory | 项目架构、技术选型、历史决策 | 中长期，workspace 级 | 高 |

### MemoryItem Schema

```text
MemoryItem
- memory_id: uuid
- tenant_id: string
- user_id: string
- workspace_id: string
- session_id: string | null
- run_id: string | null
- memory_type: profile | episodic | procedural | working_state | project
- content: text
- summary: text
- subject: string | null
- predicate: string | null
- object: string | null
- entities: jsonb
- source_event_id: uuid
- source_run_id: uuid
- source_state_node_id: uuid | null
- confidence: float
- importance: float
- value_score: float
- freshness_score: float
- trust_score: float
- risk_score: float
- retention_score: float
- reflection_priority: float
- sensitivity: public | internal | private | secret
- status: active | dormant | archived | superseded | conflicted | quarantined | pinned | deleted
- valid_time_start: timestamp | null
- valid_time_end: timestamp | null
- transaction_time: timestamp
- embedding_id: string | null
- graph_node_id: string | null
- index_status: pending | indexed | failed | stale
- graph_status: pending | synced | failed | stale
- last_indexed_at: timestamp | null
- last_graph_synced_at: timestamp | null
- created_at: timestamp
- updated_at: timestamp
```

### Memory Write Policy

MVP 阶段必须控制“什么不该写”，避免 memory 污染：

| 内容 | 默认策略 |
|---|---|
| 用户显式长期偏好 | 写 profile / project memory |
| 当前任务临时状态 | 写 working_state，run 完成后摘要 |
| 工具成功结果 | 写 tool_evidence / working_state |
| 工具失败结果 | 写 failed_branch evidence，默认 quarantined |
| assistant 推断 | 低 confidence，默认不生成 profile |
| 网页 / 外部输入 | 低 source trust，必须带 provenance |
| secret / token / key | 不写入，或只写 redacted digest |
| 用户说不要记 | 不写入长期 memory，只写 audit log |

抽取策略分两级：规则抽取优先，LLM 抽取只处理长期偏好、项目约束、run summary 和候选 procedural memory。第一版不对每条 event 做 LLM extraction。

---

### 6.5 Retrieval Controller

### 职责

- 根据当前 step 生成检索策略。
- 融合 active state path、向量召回、BM25、metadata filter、graph expansion、recent memory。
- 对候选做 rerank、budget packing，再交给 admission gate。

### RetrievalRequest

```json
{
  "tenant_id": "t1",
  "workspace_id": "w1",
  "user_id": "u1",
  "session_id": "sess1",
  "run_id": "r1",
  "step_id": "s12",
  "query": "下一步应该调用哪个部署工具？",
  "task_intent": "tool_selection",
  "tool_intention": "deploy",
  "active_state_path": ["root", "subgoal_2", "step_12"],
  "allowed_memory_types": ["procedural", "episodic", "working_state", "project"],
  "token_budget": 1200,
  "safety_level": "normal"
}
```

### 检索阶段

```text
1. Need-Retrieval Decision
   - 当前 step 是否需要 memory
   - 如果只是简单格式化任务，可跳过

2. Query Planner
   - rewrite query with task intent
   - add active state summary
   - generate entity / keyword hints

3. Candidate Retrieval
   - vector top-k
   - BM25 top-k
   - metadata filters: user/workspace/type/status/time
   - state path memory
   - Neo4j neighbor expansion

4. Candidate Fusion
   - reciprocal rank fusion or weighted sum
   - remove duplicates

5. Contextual Rerank
   - relevance
   - state match
   - recency
   - confidence
   - source reliability
   - tool sensitivity

6. Admission Gate
   - permission / safety / conflict / branch validity

7. Context Packing
   - pack by token budget
   - preserve provenance
   - produce model-ready memory context
```

### Ranking Score

```text
retrieval_score =
  0.30 * semantic_score
+ 0.20 * bm25_score
+ 0.20 * state_match_score
+ 0.10 * recency_score
+ 0.10 * confidence_score
+ 0.05 * importance_score
+ 0.05 * graph_relatedness_score
```

这组权重只作为默认 profile。实际实现应按 `task_intent` 选择 ranking profile，避免所有场景使用同一套权重：

```yaml
ranking_profiles:
  debugging:
    semantic: 0.20
    bm25: 0.15
    state_match: 0.30
    recency: 0.15
    confidence: 0.10
    procedural: 0.10
  planning:
    semantic: 0.25
    bm25: 0.15
    state_match: 0.20
    project: 0.20
    procedural: 0.15
    recency: 0.05
```

典型 intent：`debugging` 更重视 recent tool_result / failed error / procedural memory；`planning` 更重视 project / profile / procedural memory；`tool_selection` 更重视 tool evidence、procedural memory 与 safety。

### Context Packing 格式

输出给 LLM 的上下文不应是无结构 top-k 文本，而应按运行时语义分块：

```text
[Active State]
- Current goal:
- Last successful tool result:
- Current blocker:

[Relevant Project Memory]
- ...

[User Preferences]
- ...

[Procedural Hints]
- ...

[Warnings]
- failed branch memories excluded: N
- stale memories rejected: N
```

默认 packing 顺序：active state → immediate tool evidence → project constraints → user profile → procedural memory → episodic memory → warnings。

### 输出 MemoryContext

```text
MemoryContext
- access_id
- context_blocks:
  - block_id
  - memory_id
  - memory_type
  - content
  - reason
  - provenance
  - token_count
- rejected_candidates:
  - memory_id
  - reason
- profile:
  - candidate_count
  - accepted_count
  - rejected_count
  - retrieval_latency_ms
  - gate_latency_ms
  - packed_tokens
```

---

### 6.6 Memory Admission Gate

### 职责

- 在候选 memory 进入 prompt 前做准入过滤。
- 处理权限、跨域、过期、冲突、失败分支、工具敏感、用户删除等风险。
- 输出可解释的 accept / reject / degrade / warn 决策。

### Gate Score

Gate 不是单纯打分器，而是 policy engine。硬隔离规则优先，风险规则其次，最后才是相关性打分。

```text
Layer 1: Hard Policy
- tenant / workspace / user scope
- deleted / secret / quarantined
- permission / safety level

Layer 2: Risk Policy
- failed branch
- stale
- conflicted
- tool-sensitive
- cross-domain

Layer 3: Soft Ranking
- relevance
- state match
- confidence
- freshness
```

硬规则命中时直接 reject，不进入 `gate_score` 加权。

```text
gate_score =
  relevance_score
+ state_match_score
+ permission_score
+ freshness_score
+ confidence_score
- conflict_penalty
- safety_risk_penalty
- failed_branch_penalty
- cross_domain_penalty
- tool_sensitive_penalty
```

### Gate 决策

| 场景 | 策略 |
|---|---|
| 不同 tenant / workspace | reject |
| 用户删除或选择不记住 | reject |
| failed branch memory | 默认 reject，可作为 warning |
| stale memory | degrade 或 reject |
| 与 active memory 冲突 | 交给 conflict resolver，默认不直接注入 |
| 包含敏感工具参数 | 脱敏后 degrade，或要求更高 safety_level |
| procedural memory 来源成功率低 | 降权 |
| source 是 tool result | 相比 assistant 推断提高可信度 |

### Gate Log

```text
MemoryGateLog
- gate_id
- access_id
- memory_id
- relevance_score
- state_match_score
- permission_score
- freshness_score
- confidence_score
- safety_score
- final_score
- decision: accept | reject | degrade | warn
- reject_reason
- created_at
```

### 设计价值

Admission Gate 是项目的安全与工程亮点。它说明 MemTrace 不认为“相似内容都应该进入 prompt”，而是把 memory search 当作 Agent 工具调用前的安全边界。

---

### 6.7 Conflict Resolver / Version Manager

### 职责

- 处理长期记忆中的事实冲突、版本覆盖、时间有效性。
- 保留 provenance，避免无审计覆盖。
- 为 retrieval 和 gate 提供 active / superseded / contradicted 状态。

### 冲突规则

1. 同 `subject + predicate`，但 `object` 不同，标记为 conflict candidate。
2. 有明确有效时间的新事实可以覆盖旧事实。
3. 无明确时间的新事实不直接覆盖，先标记 uncertain。
4. 用户显式纠正优先级最高。
5. tool result 高于 assistant 口头推断。
6. completed branch 高于 failed branch。
7. workspace 内事实不能覆盖另一个 workspace 的事实。

### MemoryVersion

```text
MemoryVersion
- version_id
- memory_id
- previous_version_id
- operation: create | update | supersede | contradict | archive | delete
- old_content
- new_content
- reason
- source_event_id
- actor: user | agent | system
- created_at
```

### 示例

```text
旧记忆：项目使用 Node.js
新记忆：用户说“这个项目以后用 Bun，不用 Node.js”

处理：
- 新增 Bun 记忆，status=active
- 旧 Node.js 记忆，status=superseded
- 两条都保留 provenance
- 检索时默认只注入 Bun，但 dashboard 可解释历史变化
```

---

### 6.8 Reflection / Forgetting Scheduler

### 职责

- 在后台整理长期记忆。
- 对 completed run 做摘要。
- 对低价值记忆降权、归档或删除。
- 生成可复用 procedural memory。

### 多维评分模型

Reflection / Forgetting 不能用单一线性 `memory_strength` 直接决定“保留、删除、注入 prompt”。MemTrace 将长期记忆拆成四类信号，并在不同决策场景中分别使用：

```text
value_score      # 有没有长期价值
freshness_score  # 是否仍然新鲜
trust_score      # 是否可信
risk_score       # 是否危险
```

#### Value Score：长期价值

```text
value_score =
  0.35 * normalized_usage
+ 0.30 * task_success_contribution
+ 0.20 * user_pin
+ 0.15 * procedural_reuse_potential
```

`procedural_reuse_potential` 用于识别可沉淀为经验的记忆。例如用户在多个轻量 TS 后端项目中反复选择 `bun + hono + drizzle`，系统可以将其从单次事实提升为 procedural memory。

#### Freshness Score：时效性

不同 memory 类型使用不同衰减速度，而不是统一 `age_decay`：

```text
freshness_score = exp(-age_days / tau(memory_type))
```

| Memory 类型 | tau | 含义 |
|---|---:|---|
| working_state | 1 day | 当前 run 状态，任务结束后快速衰减 |
| episodic | 30 days | 对话、任务、PR 等中期事件 |
| profile | 180 days | 用户偏好、稳定约束，慢衰减 |
| procedural | 365 days | 可复用流程与经验，慢衰减 |
| tool_evidence | 14 days | API 行为、repo 结构等依环境变化 |

明确被新事实覆盖的记忆不依赖自然衰减，而是进入 `superseded` 状态。

#### Trust Score：可信度

```text
trust_score =
  0.35 * source_reliability
+ 0.25 * extraction_confidence
+ 0.20 * provenance_quality
+ 0.20 * branch_validity
```

`branch_validity` 是 MemTrace 的关键维度：来自 successful branch 的事实可信度高于 failed / rolled_back branch；失败分支中的结论默认不能覆盖成功路径记忆。

#### Risk Score：风险

```text
risk_score =
  0.30 * conflict_severity
+ 0.25 * rejection_rate
+ 0.20 * failed_branch_penalty
+ 0.15 * tool_sensitive_penalty
+ 0.10 * cross_domain_penalty
```

如果一条记忆会影响 tool calling，例如默认使用生产密钥、跳过权限检查、部署加 `--force`，即使语义相关，也必须被 Admission Gate 严格审查，必要时进入 `quarantined`。

### 决策分数分离

MemTrace 区分检索排序、保留策略和反思优先级，避免一个分数决定所有事情。

#### A. Retrieval Ranking：是否进入当前 prompt

```text
retrieval_score =
  0.35 * semantic_relevance
+ 0.25 * state_match_score
+ 0.15 * freshness_score
+ 0.15 * trust_score
- 0.25 * risk_score
- failed_branch_penalty
```

一条 memory 长期价值很高，不代表当前 step 应该使用它。当前 prompt 注入优先看语义相关性、执行状态匹配和风险。

#### B. Retention Policy：是否 active / dormant / archived

```text
retention_score =
  value_score * trust_score * freshness_score * policy_multiplier
  - risk_score
```

```text
policy_multiplier =
  1.5  if user_pinned
  1.2  if procedural_memory
  1.0  if normal_memory
  0.7  if episodic_memory
  0.3  if working_state_memory after run completed
  0.0  if user_deleted
```

`retention_score` 只用于降级、归档、reflection 优先级参考，不能直接触发永久删除。永久删除必须来自用户删除、合规策略或明确过期策略。

#### C. Reflection Priority：是否值得后台整理

```text
reflection_priority =
  0.30 * conflict_severity
+ 0.25 * procedural_reuse_potential
+ 0.20 * duplication_score
+ 0.15 * compression_gain
+ 0.10 * task_success_contribution
```

后台 reflection 优先处理矛盾最多、最能沉淀为经验、重复最多、压缩收益最高、对任务成功贡献最大的 memory，而不是优先处理“最活跃”的 memory。

### 生命周期与状态机

```text
active
  ↓
dormant
  ↓
archived
  ↓
deleted

side states:
  pinned       # 用户显式固定，不自动删除
  superseded   # 被新事实覆盖，保留 provenance
  conflicted   # 和其他记忆冲突，等待 resolver
  quarantined  # 高风险，不允许进入 prompt
```

状态策略：

| 条件 | 动作 |
|---|---|
| 高价值、高可信 | active |
| user_pin = true | pinned，不自动删除 |
| 低访问、无冲突 | dormant |
| 长期不用、可追溯 | archived |
| 被明确覆盖 | superseded |
| 与当前事实冲突 | conflicted |
| 高风险或工具敏感 | quarantined |
| 用户要求删除 | deleted |

### Scheduler 决策流程

```text
1. Load candidate memories
   - 最近被访问过
   - 很久没访问过
   - 有冲突
   - 来自 completed run
   - 被 gate 多次拒绝
   - 来源于 failed branch

2. Compute scores
   - value_score
   - freshness_score
   - trust_score
   - risk_score
   - retention_score
   - reflection_priority

3. Apply hard policies
   - user_deleted → delete
   - user_pinned → keep active / pinned
   - high_risk → quarantine
   - explicit_superseded → mark superseded

4. Apply soft policies
   - low retention → dormant
   - very low retention → archived
   - high reflection priority → summarize / merge / conflict resolve

5. Emit audit log
   - 为什么降权
   - 为什么归档
   - 为什么拒绝删除
   - 为什么生成 procedural memory
```

### 定时任务

| 任务 | 触发 | 作用 |
|---|---|---|
| summarize_completed_runs | run 结束 | 压缩轨迹，生成 summary node / episodic memory |
| extract_procedural_memory | run 成功后 | 将成功流程沉淀为 procedural memory |
| dedup_memory | 每天 | 合并重复事实 |
| conflict_scan | 每天 | 找出矛盾事实 |
| score_memory | 每天 | 计算 value / freshness / trust / risk / retention / reflection priority |
| decay_memory | 每天 | 按 memory type 与 freshness 策略降级低价值记忆 |
| archive_memory | 每周 | 归档 dormant memory |
| quarantine_memory | 每天 | 隔离高风险、失败分支、工具敏感记忆 |
| profile_refresh | 每周 | 重建用户 / 项目画像摘要 |
| reindex_memory | 按需 | embedding 模型变更后重建索引 |

### 队列拆分

```text
memory_queue      - memory extraction / indexing / conflict
maintenance_queue - scoring / reflection / decay / quarantine / archive / reindex
eval_queue        - benchmark / replay / offline evaluation
```

---

### 6.9 Phase-aware Profiler

### 职责

- 分阶段记录 memory workload 成本。
- 支持 run 级、step 级、memory access 级分析。
- 驱动 runtime policy：降级、批处理、fallback、异步化。

### 阶段划分

| 阶段 | 指标 |
|---|---|
| Ingestion | event 数、写入延迟、幂等冲突 |
| Construction | LLM 调用、embedding 调用、抽取耗时、写入条数、去重率 |
| Retrieval | ES 耗时、Neo4j 耗时、候选数、召回 top-k |
| Rerank | rerank 耗时、模型调用、重排前后差异 |
| Gate | 通过数、拒绝数、拒绝原因、gate latency |
| Context Packing | 注入 token、压缩率、active path 占比 |
| Generation | prompt token、completion token、模型延迟、工具调用次数 |
| Maintenance | reflection 耗时、归档数、冲突数、重索引数 |
| Quality | 命中正确记忆、错误记忆注入、任务成功率 |
| Safety | 跨域泄漏、失败分支污染、工具参数漂移 |

### ProfileEvent

```text
ProfileEvent
- profile_id
- run_id
- step_id
- access_id
- phase
- operation
- latency_ms
- input_tokens
- output_tokens
- embedding_tokens
- llm_calls
- db_calls
- candidate_count
- accepted_count
- rejected_count
- error_code
- metadata
- created_at
```

### Dashboard 视图

1. **Run Trace Timeline**：展示 message / tool call / memory read / memory write / error。
2. **State Tree Viewer**：展示 active path、failed branch、compressed subgoal。
3. **Memory Flow Sankey**：候选 memory → gate → context → answer。
4. **Cost Breakdown**：construction / retrieval / generation token 与 latency。
5. **Gate Analysis**：拒绝原因分布、跨域拦截、失败分支拦截。
6. **Replay Panel**：给定 access_id 复现检索、重排、gate、packing。

---

### 6.10 Evaluation Harness

### 职责

- 用可复现任务衡量不同 memory 策略。
- 避免只做主观 demo。
- 输出简历 / README 可展示的 benchmark。

### 策略对比

```text
baseline_0: no memory
baseline_1: long-context summary
baseline_2: vector memory only
variant_1: state-aware retrieval
variant_2: state-aware retrieval + admission gate
variant_3: state-aware retrieval + gate + reflection
```

### 评估指标

| 类别 | 指标 |
|---|---|
| 任务效果 | success rate、plan completion、tool success rate |
| 记忆质量 | recall@k、precision@k、correct memory hit、stale memory usage |
| 状态污染 | failed branch contamination rate、cross-workspace leakage |
| 效率 | latency、token overhead、retrieval cost、construction cost |
| 稳定性 | replay consistency、timeout rate、fallback rate |
| 治理 | delete effectiveness、permission violation |

### Demo Case

```text
Case A: 用户偏好保持
- 用户前面说“这个项目使用 Bun，不使用 Node.js”。
- 后续 Agent 规划构建命令时应使用 bun。

Case B: 失败分支隔离
- Agent 尝试方案 A 失败，回滚后尝试方案 B 成功。
- 后续检索不应把方案 A 当作推荐路径。

Case C: 工具调用安全
- 旧记忆中有过期 API endpoint。
- Gate 应根据 valid_time / source / workspace 拒绝。

Case D: 程序记忆复用
- 第一次成功修复某类测试失败。
- 第二次相似任务应召回 procedural memory，提高成功率。
```

---

## 7. 数据库设计

### 7.1 PostgreSQL 表

```text
tenants
users
workspaces
api_keys
sessions
agent_runs
agent_steps
agent_events
state_nodes
memory_items
memory_versions
memory_access_logs
memory_gate_logs
memory_conflicts
profile_events
eval_cases
eval_runs
eval_results
```

### 7.2 关键表关系

```text
workspace 1 ── n sessions
workspace 1 ── n agent_runs
agent_run 1 ── n agent_steps
agent_run 1 ── n agent_events
agent_run 1 ── n state_nodes
agent_event 1 ── n memory_items(source_event_id)
memory_item 1 ── n memory_versions
retrieval access 1 ── n memory_gate_logs
run / step / access 1 ── n profile_events
```

### 7.3 索引建议

```text
agent_events(workspace_id, run_id, step_id, created_at)
agent_events(content_digest)
state_nodes(run_id, parent_id)
state_nodes(run_id, status, path)
memory_items(workspace_id, memory_type, status)
memory_items(user_id, workspace_id, subject, predicate)
memory_items(valid_time_start, valid_time_end)
memory_access_logs(run_id, step_id, created_at)
memory_gate_logs(access_id, decision)
profile_events(run_id, phase, created_at)
```

### 7.4 Elasticsearch Index

```text
memory_index
- memory_id
- tenant_id
- workspace_id
- user_id
- memory_type
- content
- summary
- entities
- status
- valid_time_start
- valid_time_end
- confidence
- importance
- strength
- source_state_node_id
- branch_status
- embedding_vector
- created_at
- updated_at
```

查询需要支持：

- vector similarity
- BM25 keyword
- workspace / user / type / status filter
- valid time filter
- branch status filter

### 7.5 Neo4j Graph Model

```text
(:User)-[:OWNS]->(:Workspace)
(:Workspace)-[:HAS_RUN]->(:Run)
(:Run)-[:HAS_STATE]->(:StateNode)
(:StateNode)-[:PRODUCED]->(:Memory)
(:Memory)-[:MENTIONS]->(:Entity)
(:Memory)-[:ASSERTS]->(:Fact)
(:Fact)-[:ABOUT]->(:Entity)
(:Fact)-[:FROM_EVENT]->(:Event)
(:Memory)-[:SUPERSEDES]->(:Memory)
(:Memory)-[:CONFLICTS_WITH]->(:Memory)
```

Neo4j 不作为 source of truth；source of truth 是 PostgreSQL。图谱用于关系检索、解释和可视化。

### 一致性模型

```text
PostgreSQL    - 强一致 source of truth，保存 trace / memory / version / profile
Elasticsearch - eventually consistent retrieval index，可重建
Neo4j         - eventually consistent graph projection，可重建
Redis         - ephemeral buffer / lock / cache，不保存不可恢复事实
```

如果 ES / Neo4j 索引失败：

```text
1. memory_items 仍然以 PostgreSQL 中的 active 状态为准。
2. 将 index_status / graph_status 标记为 failed 或 stale。
3. 后台 reindex / graph sync task 重试。
4. retrieve_context 可 fallback 到 PostgreSQL recent memory。
```

---

## 8. 请求链路设计

### 8.1 写入链路

```text
Agent emits event
  → SDK.write_event
  → Gateway auth / quota / idempotency
  → PostgreSQL insert agent_event
  → Redis append candidate buffer
  → Profile ingestion
  → if sync_required: run extraction inline
  → else enqueue memory_queue
  → return event_id
```

### 8.2 异步抽取链路

```text
Celery memory worker
  → load buffered events
  → build window by step / subgoal
  → LLM extraction JSON
  → normalize / validate schema
  → dedup / merge / conflict detect
  → write memory_items / versions
  → index Elasticsearch
  → update Neo4j graph
  → write profile_events
```

### 8.3 检索链路

```text
Agent asks for context
  → SDK.retrieve_context
  → Gateway auth / quota
  → load active state path
  → query planner
  → ES vector + BM25
  → Neo4j expansion
  → recent state memory
  → fusion / rerank
  → admission gate
  → context packing
  → write memory_access_logs / gate_logs / profile_events
  → return MemoryContext
```

### 8.4 回滚链路

```text
Agent detects failed path
  → rollback_branch(node_id)
  → mark descendants rolled_back / failed
  → create recovery node
  → update memory_items from failed branch to branch_status=failed
  → future retrieval excludes them by default
  → profiler logs rollback event
```

---

## 9. Agent 接入方式

### 9.1 自研轻量 Agent Loop

MVP 使用自研轻量 loop，避免被 LangGraph 抽象遮蔽 MemTrace 主线。

```text
while not done:
    step = mt.start_step(intent=current_intent)
    mt.write_event(user/assistant/tool events)
    ctx = mt.retrieve_context(current_step)
    response = llm(prompt + ctx)
    if tool_call:
        execute tool
        mt.write_event(tool_result)
    mt.finish_step(step, status="success" or "failed")
```

### 9.2 LangGraph Adapter

第二阶段提供 LangGraph adapter：

- before node：retrieve_context。
- after node：write_event / finish_step。
- on error：write_event(error) / mark failed branch。

### 9.3 OpenTelemetry-like Collector

后续可兼容 OpenTelemetry / OpenInference 风格 trace，便于接入 LangSmith、Phoenix、Langfuse 等工具。但 MemTrace 自身仍保留 memory-specific profile 表。

---

## 10. 目录结构建议

```text
mem-trace/
├── apps/
│   ├── api/                         # FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── events.py
│   │   │   │       ├── retrieval.py
│   │   │   │       ├── runs.py
│   │   │   │       ├── memories.py
│   │   │   │       └── evals.py
│   │   │   ├── core/
│   │   │   │   ├── config.py
│   │   │   │   ├── security.py
│   │   │   │   └── telemetry.py
│   │   │   ├── runtime/
│   │   │   │   ├── memory_runtime.py
│   │   │   │   ├── trace_collector.py
│   │   │   │   ├── state_tree.py
│   │   │   │   ├── write_pipeline.py
│   │   │   │   ├── retrieval_controller.py
│   │   │   │   ├── admission_gate.py
│   │   │   │   ├── conflict_resolver.py
│   │   │   │   ├── reflection_scheduler.py
│   │   │   │   └── profiler.py
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   ├── repositories/
│   │   │   ├── services/
│   │   │   ├── workers/
│   │   │   └── integrations/
│   │   │       ├── llm/
│   │   │       ├── embedding/
│   │   │       ├── vector_store/
│   │   │       ├── graph_store/
│   │   │       └── agents/
│   │   ├── migrations/
│   │   └── tests/
│   └── web/                         # React dashboard
│       ├── src/
│       │   ├── pages/
│       │   ├── components/
│       │   ├── api/
│       │   └── charts/
│       └── tests/
├── packages/
│   ├── python-sdk/
│   └── ts-sdk/
├── examples/
│   ├── simple_agent/
│   ├── langgraph_adapter/
│   └── benchmark_cases/
├── docker/
├── docker-compose.yml
├── architecture.md
└── README.md
```

---

## 11. 安全、权限与治理

### 11.1 多租户隔离

- 所有主表带 `tenant_id`、`workspace_id`。
- API key 绑定 tenant / workspace scope。
- 默认禁止跨 workspace 检索。
- Gate 层再次检查候选 memory scope。

### 11.2 敏感信息处理

- tool args 默认只存 digest。
- 可配置字段级脱敏。
- `sensitivity=secret` 的 memory 默认不进入 prompt，只能作为存在性 warning。
- 支持用户删除与删除日志。

### 11.3 幂等与审计

- write_event 使用 `event_id` 或 `content_digest + step_id` 幂等。
- 所有 memory 更新写 memory_versions。
- 所有检索与 gate 决策写 access / gate log。

### 11.4 Prompt Injection 与 Memory Poisoning 防护

- memory extraction prompt 固定 JSON schema，并做 Pydantic 校验。
- 来自工具输出、网页、用户输入的内容标记 source trust。
- 低可信 source 不可直接生成 procedural memory。
- 反思型 memory 需要成功 run 或人工确认才能升为高 confidence。

---

## 12. Runtime 策略与降级

### 12.0 Hot Path / Cold Path

第一版必须优先保证热路径可用，不把耗时的 LLM extraction、graph sync、reflection 放进用户请求链路。

```text
Hot Path:
- start_run / start_step / finish_step
- write_event
- retrieve_context
- rule-based admission_gate
- context_packing
- profile_event append

Cold Path:
- LLM extraction
- dedup / merge
- reflection
- conflict scan
- archive / decay
- Neo4j update
- benchmark / replay
```

热路径原则：

1. `retrieve_context` 默认 2s 内返回。
2. profiler 写失败不能阻塞主流程。
3. Neo4j 不可用不能阻塞检索。
4. LLM extraction 默认不在用户请求路径里。
5. gate 默认规则版，LLM judge 只用于高风险候选。

### 12.1 Freshness vs Latency

| 模式 | 行为 | 适用 |
|---|---|---|
| async | 写 event 后异步抽取 | 默认，高吞吐 |
| sync_flush | 当前请求等待抽取完成 | 用户显式更正、关键偏好 |
| lazy | 检索时发现 buffer 未处理再补处理 | demo / 低流量 |
| no_extract | 只记录 trace，不抽取 | 高风险或低价值内容 |

### 12.2 Fallback

```text
ES unavailable       → fallback to PostgreSQL recent memory
Neo4j unavailable    → skip graph expansion
LLM extraction fails → store raw event, retry async
Gate model timeout   → rule-based gate only
Embedding fails      → BM25 only
Profiler write fails → do not block user path, enqueue retry
```

### 12.3 Timeout 与上限

- retrieve_context 总超时：默认 2s。
- graph expansion 最大 hop：2。
- candidate top-k：默认 vector 30 + BM25 30 + graph 20。
- gate LLM 判别：默认关闭或只对高风险 memory 开启。
- context packing token budget：由 request 指定，默认 1200。

---

## 13. 测试策略

### 13.1 单元测试

- State tree 状态转移。
- Active path builder。
- Dedup / merge。
- Conflict resolver。
- Admission gate rules。
- Context packing token budget。
- API schema validation。

### 13.2 集成测试

- write_event → async extraction → retrieve_context。
- failed branch rollback → retrieval excludes failed memory。
- workspace A memory 不可被 workspace B 检索。
- memory delete 后不可进入 context。
- ES / Neo4j fallback。

### 13.3 E2E Demo 测试

- 运行 demo Agent 完成多步骤任务。
- 故意制造失败分支。
- 验证 dashboard 显示 timeline、state tree、memory flow。

### 13.4 Benchmark

- 固定 eval cases。
- 固定模型和 embedding 配置。
- 输出 JSON + Markdown 报告。
- 对比 no memory / vector / state-aware / state-aware+gate。

核心差异化指标：

```text
failed_branch_contamination_rate
stale_memory_injection_rate
cross_workspace_leakage_rate
tool_sensitive_memory_rejection_rate
correct_active_path_hit_rate
memory_token_overhead
cost_per_successful_task
```

其中 `failed_branch_contamination_rate` 是 MemTrace 相对普通 vector memory 最重要的证明指标：失败方案和成功方案都可能语义相关，但 MemTrace 能通过 state tree 与 gate 默认拒绝 failed branch memory。

---

## 14. 实施路线图

### Phase 0：项目骨架

目标：可启动、可迁移、可测试。

- FastAPI skeleton。
- PostgreSQL / Redis / Elasticsearch docker-compose。
- SQLAlchemy models + Alembic。
- Python SDK skeleton。
- 基础 CI：ruff、mypy、pytest。

### Phase 1：Memory Runtime MVP

目标：跑通 Agent → trace → state tree → memory → retrieval。

- MemoryRuntime Facade。
- write_event。
- agent_events / state_nodes / memory_items。
- 简单 state tree：root → step → tool_call。
- LLM JSON extraction。
- ES vector + BM25 检索。
- retrieve_context。
- demo Agent。

验收：

```text
- 能记录每轮 Agent step。
- 能抽取用户偏好 / 项目约束。
- 后续 step 能检索并注入。
- 能查看 run timeline。
```

### Phase 2：状态感知与 Gate

目标：形成项目差异化。

- active path context builder。
- failed branch isolation。
- completed subgoal summary。
- retrieval 加 state_path filter。
- admission gate rule engine。
- memory_access_logs / gate_logs。
- rollback_branch。

验收：

```text
- 失败分支不会污染后续回答。
- 当前 step 能动态检索不同 memory。
- gate 能拒绝跨 workspace / failed branch / stale memory。
```

### Phase 3：Profiler 与 Dashboard

目标：让项目像 Agent Infra，而不是 demo。

- profile_events。
- Run timeline。
- State tree viewer。
- Memory flow sankey。
- Token / latency breakdown。
- Retrieval replay。

验收：

```text
- 面试时可展示一次完整 run。
- 能看到每步用了哪些 memory、拒绝哪些 memory、花多少 token。
```

### Phase 4：生命周期与工程增强

目标：补齐长期运行能力。

- Celery memory / maintenance / eval queues。
- Candidate buffer + idle flush。
- conflict resolver。
- reflection / forgetting。
- Neo4j provenance graph。
- API key / workspace 权限。
- benchmark report。

验收：

```text
- 长期 memory 可合并、过期、归档、解释。
- 有可复现实验报告。
- Docker Compose 一键启动完整系统。
```

---

## 15. 明确不做或后做的内容

### 不优先做

- 图片 OCR、音频、网页收藏、大文件知识库。
- 复杂社区发现和全量知识图谱前端。
- 训练 MemGate 小模型。
- 完整 LoCoMo / MemoryArena 刷榜。
- 多 Agent 协作平台。

### 可作为后续增强

- Go Trace Collector。
- Rust profile analyzer。
- OpenTelemetry / OpenInference exporter。
- MCP server。
- VS Code / Claude Code / Cursor 插件。
- 人工审核 memory conflict 的管理后台。

---

## 16. 风险与应对

| 风险 | 后果 | 应对 |
|---|---|---|
| 架构过大 | 做不完 | Phase 1 只做 PostgreSQL + ES + demo Agent |
| LLM 抽取不稳定 | memory 污染 | JSON schema 校验、confidence、source trust、可重跑 |
| 多存储一致性复杂 | 数据错乱 | PostgreSQL source of truth，ES / Neo4j 可重建 |
| Gate 太复杂 | 延迟高 | 默认 rule-based，高风险才 LLM judge |
| Dashboard 耗时 | 影响核心 | 先做 timeline + table，后做 Sankey / graph |
| Benchmark 难 | 说服力不足 | 设计小而稳定的 4 个 demo cases |
| 长期存储膨胀 | 成本失控 | strength、decay、archive、delete |

---

## 17. 最终推荐方案

最终推荐：**以 Python + FastAPI 为主，先做 Runtime Core 和 Profiler，采用 PostgreSQL + Elasticsearch 起步，后续补 Neo4j。**

推荐 MVP 边界：

```text
必须做：
- MemoryRuntime Facade
- Agent Trace Collector
- Execution State Tree
- Write Pipeline 简化版
- Step-aware Retrieval
- Admission Gate 规则版
- Profile Events
- Demo Agent

暂缓：
- 大型知识库导入
- 多模态
- 复杂图谱聚类
- 训练式 gate
- 完整企业后台
```

推荐最终交付物：

1. Docker Compose 一键启动。
2. README 架构图与 demo GIF。
3. Dashboard 展示一次完整 run。
4. Benchmark 报告。
5. 技术博客：为什么 Agent Memory 不是简单 RAG。

---

## 18. 参考资料

### 开源项目

- Comet: https://github.com/lm041520/Comet
- MemoryBear: https://github.com/SuanmoSuanyangTechnology/MemoryBear
- Mem0: https://github.com/mem0ai/mem0
- Letta: https://github.com/letta-ai/letta
- Zep: https://github.com/getzep/zep
- LangMem: https://github.com/langchain-ai/langmem
- Arize Phoenix: https://github.com/Arize-ai/phoenix

### 论文与综述

- Agent Memory: Characterization and System Implications of Stateful LLM Agents: https://arxiv.org/html/2606.06448
- Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers: https://arxiv.org/html/2603.07670v1
- A-MEM: Agentic Memory for LLM Agents: https://arxiv.org/abs/2502.12110
- Graph-based Agent Memory: Taxonomy, Techniques, and Applications: https://arxiv.org/html/2602.05665v1
- Agentic Memory paper list: https://github.com/Shichun-Liu/Agent-Memory-Paper-List

### 生态与可观测性

- Mem0 State of AI Agent Memory 2026: https://mem0.ai/blog/state-of-ai-agent-memory-2026
- LiteLLM OpenTelemetry integration: https://docs.litellm.ai/docs/observability/opentelemetry_integration
- LangSmith Observability: https://www.langchain.com/langsmith/observability
- Langfuse OpenTelemetry integration: https://langfuse.com/integrations/native/opentelemetry
- OpenLLMetry / Traceloop: https://www.traceloop.com/openllmetry
