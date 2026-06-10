# MemTrace MVP Plan

> MVP 目标：先跑通 `Agent trace → state tree → state-aware retrieval → admission gate → profiler` 这条热路径。第一版不追求完整知识库、复杂图谱或漂亮 Dashboard，而是证明 MemTrace 相比普通 vector memory 能减少失败分支污染、过期记忆注入和工具敏感记忆风险。

---

## 1. MVP 一句话目标

在一个 coding / debugging demo agent 中，验证 MemTrace 可以：

```text
1. 记录 Agent 执行轨迹。
2. 基于显式 step 事件构建简化 execution state tree。
3. 在后续 step 中做 state-aware retrieval。
4. 用 rule-based admission gate 过滤 failed-branch / stale / cross-workspace / tool-sensitive memory。
5. 用 profiler 展示每次 retrieval、gate、context packing 的成本和决策原因。
```

MVP 不证明“MemTrace 是完整长期记忆平台”，只证明它的核心差异化闭环成立。

---

## 2. 范围边界

### 2.1 P0 必须实现

```text
MemoryRuntime Facade
AgentRun / AgentStep / AgentEvent
StateNode 简化树
PostgreSQL schema
write_event
start_step / finish_step
rollback_branch minimal
retrieve_context
rule-based admission gate
memory_access_logs minimal
memory_gate_logs minimal
profile_events
GET /v1/access/{access_id} minimal
demo agent
1 个主 demo case：Bun vs Node.js + failed branch isolation
```

### 2.2 P1 形成差异化

```text
active path context builder
failed branch isolation 泛化
PostgreSQL + pgvector retrieval 增强
basic dashboard tables
4 个必做 benchmark cases
benchmark report
```

### 2.3 P2 之后再做

```text
LLM extraction pipeline
candidate buffer
dedup / merge
simple conflict resolver
completed run summary
procedural memory 初版
```

### 2.4 明确后置

```text
Neo4j
TypeScript SDK
完整 React Dashboard
Celery 多队列
OpenTelemetry integration
复杂 Reflection / Forgetting Scheduler
Sankey 图
图谱可视化
多租户 quota 复杂治理
MCP / IDE 插件
```

---

## 3. 第一版实现哪些 API

MVP API 按 runtime trace 系统设计。一个 step 内可以有多个 event，因此使用 `start_step → write_event* → finish_step`。

### 3.1 Runtime API

```text
POST /v1/runs
POST /v1/steps/start
POST /v1/events
POST /v1/steps/finish
POST /v1/context/retrieve
POST /v1/branches/rollback

GET  /v1/runs/{run_id}/timeline
GET  /v1/runs/{run_id}/state-tree
GET  /v1/runs/{run_id}/profile
GET  /v1/access/{access_id}
GET  /v1/steps/{step_id}
GET  /v1/memories?run_id=&workspace_id=
```

### 3.2 非 MVP API

```text
PATCH  /v1/memories/{memory_id}
DELETE /v1/memories/{memory_id}
POST   /v1/sessions/{session_id}/flush
POST   /v1/evals/run
POST   /v1/replay/{access_id}
```

这些接口可以在 P1/P2 后补。MVP benchmark 可以直接用脚本调用内部 service。

`GET /v1/access/{access_id}` 是后续 dashboard / replay 的基础，MVP 需要返回完整检索过程：

```json
{
  "query": "如何运行测试？",
  "candidates": [],
  "gate_decisions": [],
  "context_blocks": [],
  "profile": {}
}
```

### 3.3 Python Facade

```python
class MemoryRuntime:
    async def start_run(self, request: StartRunRequest) -> AgentRun:
        ...

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        ...

    async def write_event(self, event: AgentEvent) -> WriteEventResult:
        ...

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        ...

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        ...

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        ...
```

### 3.4 最小调用链

```python
run = await mt.start_run(session_id="sess1", task="修复 pytest 失败")

step = await mt.start_step(run_id=run.run_id, intent="debugging")
await mt.write_event(run_id=run.run_id, step_id=step.step_id, event_type="tool_call", tool_name="bash")
await mt.write_event(run_id=run.run_id, step_id=step.step_id, event_type="tool_result", status="failed")
await mt.finish_step(run_id=run.run_id, step_id=step.step_id, status="failed")

await mt.rollback_branch(
    run_id=run.run_id,
    step_id=step.step_id,
    reason="npm unavailable",
)

recovery = await mt.start_step(run_id=run.run_id, intent="debugging", recovery_from_step_id=step.step_id)
ctx = await mt.retrieve_context(run_id=run.run_id, step_id=recovery.step_id, query="下一步怎么修？")
```

注意：`rollback_branch` 后创建 recovery step 时，recovery node 应挂到失败 step 的父节点下，而不是挂在失败 step 下面；`recovery_from_step_id` 只记录恢复来源，避免 active path 继续经过 failed node。

---

## 4. 第一版有哪些表

MVP 使用 PostgreSQL 作为 source of truth，第一版固定使用 PostgreSQL + pgvector，不再引入 Elasticsearch。

```text
MVP: PostgreSQL + pgvector
P1/P2: 可选 Elasticsearch hybrid retrieval
```

理由：部署简单、表和向量在同一数据库内便于开发；当前 benchmark 的重点是 state-aware + gate，不是复杂 BM25 检索效果。

### 4.1 必需表

```text
workspaces
sessions
agent_runs
agent_steps
agent_events
state_nodes
memory_items
memory_access_logs
memory_gate_logs
profile_events
benchmark_cases
benchmark_results
```

### 4.2 暂缓表

```text
memory_versions
memory_conflicts
api_keys
tenants
eval_runs
eval_results
quota_logs
```

MVP 可以先用单 workspace / 单 user 配置，避免多租户治理拖慢主线。

### 4.3 agent_runs 必需字段

```text
run_id
workspace_id
session_id
status: running | completed | failed | cancelled
task
started_at
finished_at
metadata
created_at
updated_at
```

### 4.4 agent_steps 必需字段

```text
step_id
workspace_id
run_id
parent_step_id
recovery_from_step_id
state_node_id
intent
status: active | completed | failed | cancelled | rolled_back
started_at
finished_at
error_message
metadata
created_at
updated_at
```

### 4.5 agent_events 必需字段

```text
event_id
workspace_id
session_id
run_id
step_id
state_node_id
sequence_no
event_source
visibility
role
event_type
content
content_digest
raw_payload_ref
redaction_status
causality_id
tool_name
tool_args_digest
status
token_input
token_output
latency_ms
metadata
created_at
```

关键要求：`sequence_no` 是 run 内单调递增序号，不能只依赖 `created_at` 排序。

### 4.6 state_nodes 必需字段

```text
node_id
workspace_id
run_id
parent_id
step_id
node_type: root | step | recovery
status: active | completed | failed | rolled_back
goal
summary
raw_event_ids
memory_refs
branch_reason: jsonb
failure_reason
depth
path
created_at
updated_at
```

MVP 不实现 `subgoal`、`summary` 和独立 `tool_call` node。第一版 tool_call 只作为 step 下的 event；P1 再考虑把 tool_call 升级成 child node。

`raw_event_ids` 和 `memory_refs` 是 denormalized cache fields，不作为 source of truth：

```text
source of truth for events   = agent_events.state_node_id
source of truth for memories = memory_items.source_state_node_id
```

实现时可以先不维护这两个数组，或只在 read model / report 生成阶段异步回填，避免每次写 event / memory 都要同步更新 state node 数组。

### 4.7 memory_items 必需字段

```text
memory_id
workspace_id
session_id
run_id
memory_type: working_state | profile | project | episodic | tool_evidence
key
value
scope: workspace | user | session
content
summary
source_event_id: nullable uuid
source_event_ids: jsonb | null
source_run_id
source_state_node_id
branch_status: active | failed | rolled_back | completed
confidence
importance
value_score
freshness_score
trust_score
risk_score
embedding_vector
risk_flags: jsonb
status: active | dormant | archived | superseded | conflicted | quarantined | pinned | deleted
sensitivity: public | internal | private | secret
embedding_status: pending | embedded | failed | stale
expires_at
last_accessed_at
access_count
created_at
updated_at
```

MVP 不实现完整 subject / predicate / object，但必须保留 `key / value / scope`，用于支持 Bun / Node.js 这类项目约束覆盖：

```text
key = "project.runtime"
value = "bun"
scope = "workspace"
```

旧值可以标记为 `superseded` 或 `quarantined`，不直接物理删除。

`source_event_id` 是 nullable：

```text
project memory:   source_event_id = 用户 message event
tool_evidence:    source_event_id = tool_result event
working_state:    source_event_id = null, source_state_node_id = 当前 step node
```

如果一条 memory 需要引用多个事件，使用 `source_event_ids`。P0 可以先不填 `source_event_ids`，但不应强制 `source_event_id` 非空。

`embedding_status` 在 MVP 中表示 `embedding_vector` 是否已生成；P1/P2 如果引入 Elasticsearch，再额外引入外部 `index_status`。

`branch_status` 与 `status` 必须分开理解：

```text
branch_status: 这条 memory 来源于哪种执行路径。
status:        这条 memory 在生命周期管理中的状态。
```

例如：

```text
"npm test failed"
branch_status = failed
status = active

"project uses Node.js"
branch_status = completed
status = superseded
```

Gate 必须同时检查两者：`branch_status` 控制执行路径有效性，`status` 控制生命周期有效性。

`risk_flags` 用于给 Gate 提供风险来源，MVP 至少支持：

```json
{
  "tool_sensitive": false,
  "contains_secret": false,
  "destructive_command": false,
  "production_env": false
}
```

### 4.8 memory_access_logs

```text
access_id
workspace_id
run_id
step_id
query
task_intent
retrieval_strategy
candidate_count
accepted_count
rejected_count
token_budget
actual_tokens
latency_ms
created_at
```

### 4.9 memory_gate_logs

```text
gate_id
access_id
memory_id
layer: hard_policy | risk_policy | soft_ranking
decision: accept | reject | degrade | warn
reject_reason
relevance_score
state_match_score
freshness_score
trust_score
risk_score
final_score
created_at
```

### 4.10 profile_events

```text
profile_id
run_id
step_id
access_id
phase
operation
latency_ms
input_tokens
output_tokens
llm_calls
db_calls
candidate_count
accepted_count
rejected_count
error_code
metadata
created_at
```

---

## 5. P0 Memory Write Policy

MVP 不做通用 LLM extraction，只实现 rule-based memory writer，确保 demo 和 benchmark 有确定性的 memory 来源。

### 5.1 写入规则

| 规则 | 触发 | 写入 / 更新 |
|---|---|---|
| Project preference | 用户消息匹配“这个项目使用 X / 不使用 Y / 以后用 X” | `memory_type=project`, `key=project.runtime`, `value=X`, `scope=workspace` |
| Tool evidence failed | `tool_result.status=failed` | `memory_type=tool_evidence`, `branch_status=failed`, `risk_score += 0.3` |
| Tool evidence success | `tool_result.status=success` | `memory_type=tool_evidence`, `branch_status=completed` |
| Working state | `finish_step(success/failed)` | `memory_type=working_state`，记录 step 结果摘要 |
| Rollback update | `rollback_branch` | 关联 memory 的 `branch_status=rolled_back/failed` |
| Explicit correction | 用户消息匹配“不是 X，是 Y / 不用 X，用 Y” | 写入新 memory；同 `key/scope` 的旧 memory 标记 `superseded` 或 `quarantined` |
| Secret protection | content 命中 secret / token / key pattern | `redaction_status=redacted`, `sensitivity=secret`，不写入可检索 memory |

### 5.2 最小匹配规则

P0 只需要覆盖 demo 和 benchmark，不做泛化 NLP：

```text
"这个项目使用 Bun"       → key=project.runtime, value=bun
"不用 Node.js"           → key=project.runtime.excluded, value=nodejs
"不是 Node.js，是 Bun"   → supersede key=project.runtime old=nodejs new=bun
"Tried running tests with npm test, but it failed because npm was unavailable." → tool_evidence, branch_status=failed
"bun test success"       → tool_evidence, branch_status=completed
```

Demo 中 failed memory 的内容应设计成语义上容易被 baseline 召回的错误路径：

```text
tool_evidence:
"Tried running tests with npm test, but it failed because npm was unavailable."
branch_status=failed

project_memory:
"This project uses Bun and should not use Node.js."
branch_status=completed
```

这样 baseline vector memory 可能召回 failed tool_evidence；variant_2 会因为 `branch_status=failed/rolled_back` 拒绝它，只保留 Bun 项目约束。

项目技术选型用 positive / negative constraint 两类 memory 表达：

```text
positive constraint:
key = "project.runtime"
value = "bun"

negative constraint:
key = "project.runtime.excluded"
value = "nodejs"
```

Context packing 时需要将两类 memory 合并成稳定表达：

```text
This project uses Bun and should not use Node.js.
```

这些规则可以先写成 Python regex / keyword matcher；P2 再替换或补充 LLM extraction。

### 5.3 Secret Protection 语义

MVP 对 secret 的处理固定如下：

```text
agent_events:
- 保存 redacted content。
- 原文不存，或只存在 raw_payload_ref 且默认不可读取。

memory_items:
- 默认不创建可检索 memory。
- 如需审计，可创建 sensitivity=secret + status=quarantined 的记录。

Gate:
- sensitivity=secret 永远 hard reject。
```

---

## 6. State Tree Transition Rules

### 6.1 节点创建时机

`start_step` 时就创建 `state_node`，不要等 `finish_step` 后回填。这样 step 中间的 event 可以直接绑定 `step_id + state_node_id`。

```text
start_run:
- create agent_run(status=running)
- create root state_node(status=active)

start_step:
- create agent_step(status=active)
- create state_node(node_type=step/recovery, status=active)
- return step_id + state_node_id

write_event:
- bind event to step_id + state_node_id
- optionally append event_id to state_node.raw_event_ids cache

finish_step(success):
- agent_step.status=completed
- state_node.status=completed
- generated memories branch_status=completed

finish_step(failed):
- agent_step.status=failed
- state_node.status=failed
- generated memories branch_status=failed

rollback_branch:
- target state_node.status=rolled_back
- descendant state_nodes.status=rolled_back
- related memories branch_status=rolled_back
- keep state_node.failure_reason as original failure reason
- set branch_reason.rollback_from / branch_reason.recovery_from for audit
```

状态语义统一为：

```text
failed      = 这个 step 执行失败，但尚未被后续 recovery 明确回滚。
rolled_back = 这个 step 已被 rollback_branch 明确回滚，不再属于 active path。
```

MVP 为了简单，不额外增加 `rollback_status` 字段；rollback 后 `state_node.status` 从 `failed` 更新为 `rolled_back`，但 `failure_reason` 保留原始失败原因。

### 6.2 Recovery 挂载规则

Recovery node 不挂在 failed step 下面，而是挂到 failed step 的 parent 下，并用 `branch_reason` 记录来源：

```text
root
  ├── step_1 completed
  ├── step_2 rolled_back
  └── step_3 recovery completed  # branch_reason: recovery_from=step_2
```

这样 active path 不会经过 failed node，state-aware retrieval 也更容易过滤失败分支。

### 6.3 parent_step_id 与 state_node.parent_id

`agent_steps.parent_step_id` 与 `state_nodes.parent_id` 语义不同：

```text
agent_steps.parent_step_id = 逻辑步骤来源。
state_nodes.parent_id      = 状态树结构父节点。
recovery_from_step_id      = recovery 的恢复来源。
```

例如：

```text
step_3.recovery_from_step_id = step_2
step_3.parent_step_id        = step_1 或 null
state_node_3.parent_id       = root
```

实现时不要因为 `recovery_from_step_id=step_2` 就把 recovery state node 挂到 failed state node 下。

`branch_reason` 是结构化 jsonb，不是普通 text。示例：

```json
{
  "type": "recovery",
  "recovery_from_step_id": "step_2",
  "rollback_reason": "npm unavailable"
}
```

---

## 7. Gate Policy Layers

Admission Gate 是 policy engine，不是单纯相关性打分器。MVP 使用三层策略：

### 7.1 Hard Policy

命中后直接 reject，不进入加权分数：

```text
workspace mismatch → reject(reason="workspace_mismatch")
status in deleted/quarantined → reject(reason="invalid_status")
sensitivity=secret → reject(reason="secret")
branch_status=failed and allow_failed_branch=false → reject(reason="failed_branch")
branch_status=rolled_back and allow_rolled_back=false → reject(reason="rolled_back")
```

### 7.2 Risk Policy

```text
expires_at < now → reject(reason="stale") or degrade
risk_flags.tool_sensitive=true → reject/warn
risk_flags.destructive_command=true → reject/warn
risk_flags.production_env=true → warn 或要求更高 safety_level
status=conflicted → degrade/warn
rejection_rate high → P1/P2 derived signal, not required in P0
```

P0 Gate 只要求实现：workspace mismatch、deleted / quarantined、`sensitivity=secret`、failed / rolled_back branch、`expires_at` stale、`risk_flags.tool_sensitive`、`risk_flags.destructive_command`、`risk_flags.production_env`。`rejection_rate` 可由 `memory_gate_logs` 聚合得到，但不进入 P0 热路径。

### 7.3 Soft Ranking

未被 hard / risk policy 拦截后，再考虑：

```text
relevance_score
state_match_score
freshness_score
trust_score
risk_score
```

所有 gate 决策都必须写入 `memory_gate_logs`，用于 `GET /v1/access/{access_id}` 展示。

---

## 8. Context Block Format

`retrieve_context` 返回结构化 context blocks，而不是无结构 top-k 文本。

```json
{
  "access_id": "acc_1",
  "context_blocks": [
    {
      "type": "active_state",
      "content": "Current recovery step after failed npm test.",
      "source": "state_tree",
      "tokens": 20
    },
    {
      "type": "project_memory",
      "memory_id": "m1",
      "content": "This project uses Bun instead of Node.js.",
      "reason": "matched project runtime preference",
      "provenance": {
        "run_id": "r1",
        "step_id": "s1",
        "event_id": "e1"
      },
      "tokens": 18
    }
  ],
  "warnings": [
    "1 failed-branch memory was excluded."
  ],
  "profile": {
    "candidate_count": 4,
    "accepted_count": 2,
    "rejected_count": 2,
    "latency_ms": 35
  }
}
```

默认 packing 顺序：

```text
active_state
→ immediate tool_evidence
→ project constraints
→ user profile
→ procedural hints
→ episodic memory
→ warnings
```

---

## 9. 第一版 demo agent 怎么跑

### 9.1 Demo 目标

Demo agent 只做 coding/debugging 场景，不做通用任务平台。

目标场景：

```text
用户指定项目约束：这个项目使用 Bun，不使用 Node.js。
Agent 执行一个多步骤 debugging 任务。
中途出现失败方案 A 和成功方案 B。
后续相似步骤需要召回成功路径、拒绝失败路径。
Profiler 展示 retrieval / gate / context packing 成本。
```

### 9.2 Demo Agent Loop

```text
start_run
  ↓
start_step(intent=planning)
  ↓
write_event(user message: 项目使用 Bun，不用 Node.js)
  ↓
finish_step(success)
  ↓
start_step(intent=debugging)
  ↓
write_event(tool_call: npm test)
write_event(tool_result: Tried running tests with npm test, but it failed because npm was unavailable.)
finish_step(failed)
  ↓
rollback_branch(failed step)
  ↓
start_step(intent=debugging, recovery_from=failed step, parent=failed step parent)
  ↓
retrieve_context(query=如何运行测试？)
  ↓
Gate rejects failed npm memory; accepts Bun project memory
  ↓
write_event(tool_call: bun test)
write_event(tool_result: success)
finish_step(success)
```

### 9.3 Demo 输出

第一版不需要复杂前端，CLI + JSON / Markdown 报告即可。

必须输出：

```text
1. run timeline
2. state tree
3. memory access table
4. gate decision table
5. token / latency summary
```

示例输出：

```text
State Tree:
root
  ├── step_1 planning completed
  ├── step_2 debugging rolled_back  # failure_reason: npm unavailable
  └── step_3 recovery completed

Gate Decisions:
- rejected memory: "Tried running tests with npm test, but it failed because npm was unavailable." reason=rolled_back
- accepted memory: "This project uses Bun and should not use Node.js." reason=project_memory + active_workspace
```

---

## 10. 第一版 benchmark 怎么证明 state-aware + gate 更好

### 10.1 对比策略

```text
baseline_0: no memory
baseline_1: vector memory only
variant_1: state-aware retrieval
variant_2: state-aware retrieval + rule-based admission gate
```

MVP 不做 long-context summary、reflection、Neo4j graph memory。

公平性定义：

```text
baseline_1:
- 使用相同 memory_items。
- 忽略 branch_status / active path / gate / workspace safety。
- 只按 embedding similarity 或 text similarity top-k 召回。
- 不做 active path filter。

variant_1:
- 使用相同 memory_items。
- 使用 state_node_id / active path / branch_status 做 state-aware rerank。
- failed branch 只降权，不 hard reject。
- 不启用任何 hard policy。

variant_2:
- 使用相同 memory_items。
- 在 variant_1 基础上启用 hard policy + risk policy。
- failed_branch / rolled_back / secret / workspace mismatch 直接 reject。
```

这样可以证明收益来自 state-aware retrieval 和 admission gate，而不是数据不同。

### 10.2 关键指标

```text
task_success_rate
correct_active_path_hit_rate
failed_branch_contamination_rate
stale_memory_injection_rate
cross_workspace_leakage_rate
tool_sensitive_blocked_rate
memory_token_overhead
retrieval_latency_ms
gate_latency_ms
cost_per_successful_task
```

最核心指标：

```text
failed_branch_contamination_rate
```

原因：普通 vector memory 可能同时召回失败方案和成功方案，因为它们语义都相关；MemTrace 能利用 state tree 和 gate 默认拒绝 failed branch memory。

`cross_workspace_leakage_rate = 0` 属于 security invariant，不作为模型效果提升指标；它证明权限 filter 正确。质量提升主要看 `failed_branch_contamination_rate`、`correct_active_path_hit_rate` 和 task success。

### 10.3 Benchmark Evaluation Method

每个 case 按同一流程评估：

```text
1. 为所有策略 seed 同一批 memory_items。
2. 分别运行 baseline_1 / variant_1 / variant_2 retrieval。
3. 先评估 LLM 前的 context pollution。
4. 可选运行 LLM generation，再评估 final action。
5. 同时报告 retrieval-level 与 task-level metrics。
```

为了减少模型随机性，MVP 默认使用 rule evaluator：

```text
failed_branch_contamination = 1
if accepted context_blocks contain memory where branch_status in [failed, rolled_back]

failed_branch_contamination = 0
if failed / rolled_back memory only appears in rejected_candidates or warnings

tool_sensitive_blocked = 1
if memory.risk_flags.tool_sensitive=true and gate decision in [reject, warn]

tool_sensitive_rejection = 1
if memory.risk_flags.tool_sensitive=true and gate decision == reject

if final_command contains "npm":
    task_success = 0

if final_command contains "bun":
    task_success = 1
```

### 10.4 MVP benchmark cases

P0 只跑 1 个主 demo case：Bun vs Node.js + failed branch isolation。

P1 必做 4 个 benchmark cases：

| Case | 目标 | 期望 |
|---|---|---|
| 1. 项目技术选型保持 | 用户说用 Bun，不用 Node.js | 后续命令使用 `bun` |
| 2. 失败分支隔离 | 方案 A 失败，方案 B 成功 | 后续不推荐 A |
| 3. 工作区隔离 | workspace A/B 偏好不同 | A 不污染 B |
| 4. 工具调用安全 | 旧记忆包含 `--force` 或 production key | Gate 拒绝 |

P2 可选扩展 4 个 cases：

| Case | 目标 | 期望 |
|---|---|---|
| 5. 用户显式纠正 | Node.js 被 Bun 覆盖 | 旧记忆不注入 |
| 6. completed run 复用 | 上次成功修复 pytest 失败 | 相似任务召回成功路径 |
| 7. stale memory 拒绝 | 旧 API endpoint 过期 | 不注入 stale memory |
| 8. no-memory baseline 失败 | 无记忆无法保持约束 | state-aware 成功 |

### 10.5 通过标准

MVP benchmark 通过标准：

```text
1. variant_2 的 failed_branch_contamination_rate 低于 baseline_1。
2. variant_2 的 cross_workspace_leakage_rate = 0，作为 security invariant。
3. variant_2 能拒绝 tool-sensitive memory。
4. variant_2 在 Bun / Node.js 主 demo 中正确使用 positive / negative project constraints。
5. profiler 能输出每个 access 的 candidate_count / accepted_count / rejected_count / latency。
6. GET /v1/access/{access_id} 能展示候选、拒绝原因和最终 context blocks。
```

---

## 11. Hot Path / Cold Path

### 11.1 Hot Path

```text
start_run
start_step
write_event
finish_step
retrieve_context
rule-based gate
context packing
profile event append
```

要求：

```text
retrieve_context 默认 2s 内返回
profiler 写失败不阻塞主流程
LLM extraction 不在默认请求路径
Neo4j 不在 MVP 热路径
Gate 默认规则版
```

Profile 写入分级：

```text
critical profile:
- access_id
- candidate_count
- accepted_count
- rejected_count
- latency_ms

non-critical profile:
- token breakdown
- detailed debug metadata
- per-candidate scoring details
```

critical profile 尽量同步写入，但失败不能影响主流程；non-critical profile 可以异步或 best-effort。

P0 只支持三个 profile phase：

```text
phase = retrieval
phase = gate
phase = context_packing
```

P1/P2 再补：

```text
ingestion
construction
maintenance
generation
quality
safety
```

### 11.2 Cold Path

```text
LLM memory extraction
completed run summary
dedup / merge
conflict scan
reflection
archive / decay
benchmark replay
```

MVP 可以把 cold path 做成 CLI 脚本，不必一开始引入 Celery。

---

## 12. 第一版不做什么

```text
不做 Neo4j
不做 TS SDK
不做完整 React Dashboard
不做 OpenTelemetry exporter
不做 MCP server
不做复杂多租户 quota
不做自动 subgoal 推断
不做训练式 gate
不做复杂 reflection scheduler
不做全量 LoCoMo / MemoryArena benchmark
```

这些都可以放进 roadmap，不进入第一版验收。

---

## 13. 第一版验收清单

```text
[ ] 能启动 FastAPI + PostgreSQL。
[ ] 能通过 API 创建 run / step。
[ ] 能写入 AgentEvent，并按 sequence_no 查询 timeline。
[ ] 能根据 start_step / finish_step 生成简化 state tree。
[ ] 能记录 failed step，并通过 rollback_branch 创建 recovery node。
[ ] 能写入至少三类 memory：project、working_state、tool_evidence。
[ ] 能执行 retrieve_context，并返回结构化 context blocks。
[ ] Gate 能 hard reject cross-workspace / deleted / quarantined memory。
[ ] Gate 能 reject failed branch memory。
[ ] ProfileEvent 能记录 retrieval / gate / context_packing latency。
[ ] Demo agent 能跑通 Bun vs Node.js 和 failed branch isolation。
[ ] baseline_1 vector memory only 能在 failed branch case 中产生污染。
[ ] variant_2 state-aware + gate 能稳定消除该污染。
[ ] GET /v1/access/{access_id} 能展示候选、拒绝原因和最终 context blocks。
[ ] P0 Demo 输出 Markdown / JSON 报告（demo_report.md / demo_report.json）。
[ ] P1 Benchmark 输出 Markdown / JSON 报告（benchmark_report.md / benchmark_results.json）。
```

---

## 14. 第一版完成后的简历表述

> 设计并实现 MemTrace，一个面向长程 LLM Agent 的状态感知记忆运行时系统。系统基于 Agent trace 构建 execution state tree，区分 active path、completed step 与 failed branch；实现 step-aware retrieval controller 和 rule-based admission gate，在上下文注入前过滤过期、跨域、失败分支和工具敏感记忆；构建 phase-aware profiler，按 retrieval、gate、context packing 等阶段统计 token、latency、候选数、拒绝原因和失败分支污染率，并通过可复现实验对比 no memory、vector memory 和 state-aware memory 策略。
