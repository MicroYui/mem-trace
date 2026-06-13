# Failure-aware Negative Memory Injection — 实施计划

> **状态**：I1-I7 已完成。I7 compaction-negative retained facts 已完成 retained-negative DTO、dedicated compaction-log field、SQL JSONB migration/mapping、trace-bundle redaction、packer dropped-block metadata retention、replay/metrics/reports/bundle surfacing、benchmark `case_13_compaction_retains_negative_lesson`、acceptance `variant_2_retains_negative_lesson_under_compaction` 与 closeout verification。设计已纳入第二轮 review 修正（replay/observability 同步、sanitized DTO 边界、reject_reason 顺序陷阱、计数闭合、负向块排序/去重/query 稳定性）。
> **来源**：ROADMAP §9 Context Compaction 的反向补集 + §1 技术债（failed branch 一刀切拦截）。
> **关联文档**：`docs/design/ROADMAP.md`、`docs/design/CONTEXT_COMPACTION_PLAN.md`、`.ai/PROJECT_STATE.md`。
> **执行约定**：每完成一个 Issue 须同步更新 `.ai/PROJECT_STATE.md`，并在本文件勾掉对应 checkbox。TDD：先写失败测试看红，再实现看绿。

---

## 0. 背景与目标

当前 gate 对 `failed` / `rolled_back` 分支记忆一刀切 hard reject（`gate.py:109-112`），rejected 记忆完全不进 packer，模型彻底看不到「以前为什么错、哪个命令失败过、哪条路径不要再走」。这在 coding agent 场景下丢失了重要的学习信号。

**核心区分**：contamination prevention（防污染）与 failure learning（失败学习）不是一回事。

升级目标：

```
失败分支不作为「正向可用上下文」注入，
但失败原因可作为「负向经验 / 避坑提示 / anti-memory」受控注入。
```

### 约束
- baseline_0 / baseline_1 / variant_1 **不启用 failure learning、不产生 degrade / avoided_attempts 块**，且 **case_1..case_9 既有 benchmark acceptance 不回退**（review#7：用「策略语义 + acceptance 不回退」替代难以保证的「字节级不变」——新增字段/profile metadata/report 列可能使逐字节快照失真，避免 Codex 写脆弱 snapshot test）。仅 variant_2 启用降级通道。
- **无需改 writer**：失败原因文本已原样留存于 `MemoryItem.content`（`writer.py:187` 把失败 tool_result 的 content 原样写入，summary 取前 120 字符，branch_status=failed）；rollback 只翻转 `branch_status` + `updated_at`（`memory_runtime.py:355-370`），content/summary/key/value 全保留。

### 安全分级（已拍板，贯穿 gate + packer）
| 情况 | gate 行为 | packer 渲染 |
|---|---|---|
| `failed/rolled_back` 且**安全**（非 secret/`contains_secret`/`destructive_command`/`tool_sensitive`） | **degrade**（进负向通道） | `safe_text` 来自 `mem.content`：**安全失败证据文本**；若文本含命令则原样展示 + must-not-execute 框，否则只展示失败摘要 + must-not-repeat 框 |
| `failed/rolled_back` 且 **destructive / tool_sensitive / secret** | **原始 memory 仍 hard reject**（gate 不网开一面）；派生一个**不含原始内容**的 sanitized 提示对象 | 固定模板高层安全提示，不含原命令/参数/路径/flag |

> **边界红线**：gate 绝不对 destructive 网开一面。危险/secret 命令的**原始 `MemoryItem` 永远不向下传给 packer**（详见 D4）；只允许传一个派生的、`safe_text` 已在 gate/controller 层固定生成的脱敏对象。
>
> **措辞收敛（review 修正）**：writer 只从 `tool_result` 写 `tool_evidence`，不从 `tool_call` 写（`writer.py:187`）。因此「原始命令原文」只有在 `tool_result.content` 自身包含命令时才可得（如 demo 的 "Tried running tests with npm test..."）；若 content 仅为 "exit code 1" 则只能展示失败摘要。**首批不扩展到 writer/runtime 去关联同 step 的 tool_call**，稳定显示失败命令留作后续候选。

---

## 1. 核心架构决策

### D1. 通道分离：复用 `degrade` 枚举 + 修掉 `accepted` 的坑
`GateDecisionType.degrade` 已定义（`models.py:137`）但 `evaluate()` 从不产出。当前 `GateOutcome.accepted`（`gate.py:79-81`）把 `accept/degrade/warn` 都算 accepted —— 若直接用 degrade 表负向证据，它会顺着 `accepted_memories` 流进 packer **正向区**，反而制造污染。

**改法**：
- `GateOutcome.accepted` 改为 `decision in (accept, warn)`（warn 仍是正向：production_env / conflicted 警告，行为不变）。
- 新增 `GateOutcome.degraded` property = `decision == degrade`。
- 因 `degrade` 此前从不产出，对 baseline/variant_1 **零影响**，同时修复了这个潜在坑。
- 收敛进 `GateOutcome` 属性，避免在 controller 与 inspect_access 两条路径靠 reject_reason 反推（单点真相，防 replay drift）。

**⚠️ 必须同步的全部 `degrade` 使用点（review 修正，原计划遗漏）**：源码里 `_ACCEPTED_DECISIONS = {accept, degrade, warn}` 共有**三处独立定义**，全部把 degrade 当 accepted，必须一起改：
- `apps/api/app/retrieval/gate.py:79-81`（`GateOutcome.accepted`）。
- `apps/api/app/observability/metrics.py:21`（`build_observability_summary` 用 `gate_log.decision not in _ACCEPTED_DECISIONS` 在 `:92` 过滤）—— 不改则 dashboard/report 把负向经验**统计成正向注入**，指标语义错乱。
- `apps/api/app/observability/replay.py:38`（`:192` 用它重建 accepted memories 再 `pack_context`；`:433-436` 用它做 drift 判定）—— 不改则 replay 把 degrade 当正向块 pack，与主路径（负向块）**必然 drift**。
- `apps/api/app/runtime/memory_runtime.py:866`（inspect_access 三元判断）。

四处统一口径：**accepted = accept/warn；degraded = degrade（独立通道）；rejected = reject**。这部分独立成 **I4「Inspect + Replay + Observability 接线」**，详见 §2/§4。

### D2. 开关字段保策略不变
`GateConfig` 新增 `enable_failure_learning: bool = False`。`for_strategy`（`gate.py:43-62`）仅 variant_2 默认分支置 `True`；baseline_1 / variant_1 显式 False。

### D3. stale 首批不降级
维持 hard reject（`gate.py:117-118`）。stale 是「值已过时」而非「失败教训」，语义不同；且 case_9 已有 `variant_2_excludes_stale_memory` acceptance，改动会破坏既有可复现性。记为后续候选（见 §7）。

### D4. NegativeEvidence DTO + hard/risk 顺序陷阱（review 修正）
**顺序陷阱**：当前 `evaluate()` 的 hard policy（`gate.py:109-112` 判 failed/rolled_back）在 risk policy（`gate.py:120-123` 判 destructive/tool_sensitive）**之前**。所以一个 destructive 的 failed memory 会先以 `failed_branch` 被 reject，**根本走不到** `destructive_command` 分支。
- ⇒ 不能在 hard policy 段「保留原 reason」期待 reason 会是 destructive；必须在 hard policy 的 failed/rolled_back 分支内**显式检查** `mem.sensitivity==secret or risk_flags.contains_secret or destructive_command or tool_sensitive` 来分流 safe vs unsafe。
- ⇒ 下游（controller/packer）识别 sanitized failure **必须看 memory 的 branch/risk 属性，而非靠 `reject_reason` 字符串反推**。

**NegativeEvidence DTO（替代直接传 `MemoryItem`）**：原计划把危险 memory 作为 `MemoryItem` 经 `sanitized_failures` 传给 packer，存在「packer 某分支误用 `mem.content`/`mem.summary` 泄漏原文」的风险。改为新增一个模型，**危险 memory 的原始对象绝不向下传**。**落在 `apps/api/app/runtime/models.py`，用 Pydantic `_Base`**（与 `RetainedFact`/`ContextBlock` 同风格，利于 replay/inspect/dashboard 序列化；不用 dataclass）：

```python
class NegativeEvidence(_Base):
    source_memory_id: Optional[str] = None
    source_state_node_id: Optional[str] = None   # 去重聚合键（三路径一致，review#1）
    memory_type: Optional[MemoryType] = None      # 去重优先级 tool_evidence > working_state（review#1）
    branch_status: BranchStatus
    mode: Literal["raw_failed_attempt", "sanitized_risk_notice"]
    risk_kind: Optional[Literal["secret", "destructive", "tool_sensitive", "unknown"]] = None  # sanitized 模板选择
    reason: str            # failed_branch_degraded / rolled_back_degraded / *_sanitized
    safe_text: str         # 已在 builder 层定型；raw 经二次 redaction，sanitized 为固定模板
    provenance: Optional[Provenance] = None
```
- safe failed → `mode="raw_failed_attempt"`，`safe_text` 来自 `secrets.redact(mem.content)`（二次防御，见 D6）。
- unsafe failed → `mode="sanitized_risk_notice"`，`safe_text` 为按 `risk_kind` 选择的固定模板（不含原命令/参数/路径/flag），**不传 `mem.content`/`mem.summary`**。
- packer 只消费 `NegativeEvidence.safe_text` 渲染，从不读原始 `MemoryItem`。
- **provenance 安全约束**：`sanitized_risk_notice` 的 `provenance` 只允许携带 id（run/state_node/step/event ids），**不得携带任何原始 content/summary 文本**，防止经 provenance 间接泄漏。

**负向块有两类来源（关键，review#3，实现者勿混淆）**：
```
safe failed   : gate decision = degrade → NegativeEvidence(mode=raw_failed_attempt)
unsafe failed : gate decision = reject(*_sanitized) → 派生 NegativeEvidence(mode=sanitized_risk_notice)
```
即 **并非所有 `negative_evidence` block 都来自 degrade**；sanitized notice 来自 reject。I4 指标中 `degraded_negative_evidence_count` / `sanitized_failure_notice_count` 是 gate 层事件计数；`negative_evidence_block_count` 表示观测路径重建出的负向块数量，因此不保证等于前两者之和。summary 侧按 shared builder 去重/`max_blocks` 截断后计数；replay 侧按 original reconstructed context 中实际 `avoided_attempts` 块计数（预算 drop 时可更小）。

### D5. 计数语义闭合（review 修正，采用方案 A，无需 migration）
源码 `accepted_outcomes = [o for o in outcomes if o.accepted]` / `rejected_outcomes = [o for o in outcomes if not o.accepted]`（`controller.py:257-258`），且 `candidate_count = accepted + rejected`（`controller.py:321-323`）。
- 把 `GateOutcome.accepted` 改为只含 accept/warn 后，**degrade 自动落入 `rejected_outcomes`**（`not o.accepted`），`candidate_count = accepted + rejected` **自动闭合，无需加 DB 字段**。
- 在 `rejected_outcomes` 内再筛 `o.degraded` 派生负向证据喂 packer；`profile.metadata` 记 `degraded_count` / `hard_rejected_count` 细分。
- 语义说明：`rejected_count` 从「hard reject」变为「not positively accepted」（含 degrade）；细分在 metadata。方案 B（新增 `degraded_count` DB 列 + ORM/migration/SQL/dashboard）改动面大，**首批不做**。

### D6. Shared negative-evidence builder（防三路径漂移，review#1/#2/#7/#9）
controller、inspect_access、replay 三条路径都要从 `GateOutcome` + `MemoryItem` 构造 `NegativeEvidence`。**禁止各自拼装**，否则去重顺序/sanitized 模板/redaction 任一处不一致都会制造非业务性 drift。新增**单点真相模块** `apps/api/app/retrieval/negative_evidence.py`，集中实现：

```python
def is_failedish(mem) -> bool                       # branch_status in {failed, rolled_back}
def is_unsafe_failed(mem) -> bool                   # secret/contains_secret/destructive/tool_sensitive/production_env
def risk_kind(mem) -> Literal["secret","destructive","tool_sensitive","unknown"]
SANITIZED_TEMPLATES: dict[risk_kind, str]           # 固定模板，集中定义（见 §4 渲染）
def build_negative_evidence(                        # 唯一入口：调用方不预筛，传全部 outcomes
    outcomes: list[GateOutcome],
    memories_by_id: dict[str, MemoryItem],
    *, max_blocks: int = 3,
) -> list[NegativeEvidence]
def dedupe_negative_evidence(items, max_blocks=3) -> list[NegativeEvidence]
```
- **唯一入口签名（review#4）**：`build_negative_evidence(outcomes, memories_by_id, *, max_blocks=3)`，**调用方（controller/inspect/replay）不预筛 degraded/sanitized**，由 builder 内部判定，彻底消除三路径漂移：
  - `o.degraded` → `raw_failed_attempt` 候选；
  - `o.decision == reject and o.reject_reason in {failed_branch_sanitized, rolled_back_sanitized}` → `sanitized_risk_notice` 候选；
  - 其余 → skip。
- **`risk_kind` 判定顺序写死（review#6，避免 `git push --force` 既 destructive 又 tool_sensitive 时丢失 destructive 语义）**：
  ```python
  if mem.sensitivity==secret or risk_flags.contains_secret: return "secret"
  if risk_flags.destructive_command: return "destructive"
  if risk_flags.tool_sensitive or risk_flags.production_env: return "tool_sensitive"
  return "unknown"
  ```
- **production_env 也算 unsafe（review#6）**：failed branch 的 production 操作即便非 destructive，也不原文注入；`is_unsafe_failed` 含 `production_env`，对应 gate I1 也把 `production_env` 纳入 sanitized 分流（见 I1）。
- **二次 redaction 防御（review#7）**：构造 `raw_failed_attempt` 时调用 `secrets.redact(mem.content)`（`app/memory/secrets.py` 已有 `contains_secret`/`redact`）；若 `contains_secret(mem.content)` 为真或 redact 后文本与原文不同 → **降级为 `sanitized_risk_notice`**（risk_kind=secret），不输出 raw。
- **去重（review#1）**：按 `source_state_node_id` 聚合，同 node 取一条（优先级 `tool_evidence > working_state > 其他`），再全局截断到 `max_blocks`（默认 3）。
- 三条路径只调用此模块；sanitized 模板集中在此，改一处即全一致。

---

## 2. Issue 拆分与依赖（review 修正后重排）

| Issue | 内容 | 批次 | 依赖 |
|---|---|---|---|
| I1 ✅ | Gate 三路输出 + `enable_failure_learning` + safe/unsafe 分流（显式 risk 检查） | 首批 | — |
| I2 ✅ | `NegativeEvidence` DTO（models.py）+ 共享 builder `negative_evidence.py`（D6：构造/redaction/去重/模板）+ packer `avoided_attempts` block 渲染 + 排序（project 在前） | 首批 | I1 |
| I3 ✅ | Controller 主路径接线（accepted=accept/warn、调用 D6 builder、计数闭合、warnings） | 首批 | I1,I2 |
| I4 ✅ | **Inspect + Replay + Observability 接线**（inspect_access / `replay.py` / `metrics.py` 三处 `_ACCEPTED_DECISIONS` 同步，调用 D6 builder，replay drift 严重度，防 drift / 指标错乱） | 首批 | I1,I2,I3 |
| I5 ✅ | Benchmark case_10（safe）+ case_11（sanitized destructive）+ evaluator 显式分区 + 指标 + acceptance | 首批 | I1-I4 |
| I6 ✅ | ROADMAP / CONTEXT_COMPACTION_PLAN / PROJECT_STATE 文档同步（实现与 benchmark 稳定后） | 首批收尾 | I1-I5 |
| I7 ✅ | Compaction 负向 retained（独立 negative-lesson 通道 + replay 快照） | 独立收尾 | I1-I6 |

依赖链：I1 → I2 → I3 → I4 → I5 → I6 → I7（已完成）。
（与原 review 建议一致：replay/observability 从「隐含项」提升为首批独立 I4；文档同步后移到 benchmark 稳定之后。）

---

## 3. I1 — Gate 三路输出 + safe/unsafe 分流 ✅

**文件**：`apps/api/app/retrieval/gate.py`

- [x] `GateConfig`：新增 `enable_failure_learning: bool = False`；`for_strategy` 仅 variant_2 分支置 True；baseline_0/baseline_1/variant_1 显式 False。
- [x] `GateOutcome`：`accepted` → `decision in (accept, warn)`；新增 `degraded` property = `decision == degrade`。
- [x] `evaluate()` hard policy 段（`gate.py:109-112`）改写 failed/rolled_back —— **注意顺序陷阱（D4）**：此段在 risk policy（`:120-123`）之前，故必须在分支内**显式检查 risk/sensitivity**，不能依赖后续 reason：
  - `not enable_failure_learning` → 维持 `_reject(..., "failed_branch"/"rolled_back")`（旧行为；baseline/variant_1 走 allow 分支不进此处）。
  - `enable_failure_learning`：
    - `mem.sensitivity==secret or risk_flags.contains_secret or destructive_command or tool_sensitive or production_env` → **`_reject`**，reason 用 `"failed_branch_sanitized"`/`"rolled_back_sanitized"`（明确这是被脱敏处理的失败项，便于下游识别，不与普通 failed_branch 混淆）。注意 `production_env` 也纳入（review#6：failed 的 production 操作即便非 destructive 也不原文注入）。
    - 否则 → `_degrade(...)` 工厂产出 `decision=degrade`，layer=hard_policy，reject_reason `"failed_branch_degraded"`/`"rolled_back_degraded"`；`final_score` 用 relevance（仅影响负向块丢弃排序）。
- [x] 新增 `_degrade(...)` 工厂（仿 `_reject` `gate.py:159-171`）。

**TDD**（`apps/api/tests/retrieval/test_gate.py` 扩展）：
- [x] safe failed-branch + `enable_failure_learning=True` → `decision==degrade, accepted is False, degraded is True`，reason=`failed_branch_degraded`。
- [x] 默认 config（False）→ 仍 reject（保旧 `failed_branch`）。
- [x] destructive failed + failure_learning → `_reject`，reason=`failed_branch_sanitized`（**不进 degrade**）。
- [x] secret failed + failure_learning → `_reject` sanitized。
- [x] `for_strategy(variant_1)` failed-branch 仍走 allow + 降权（`gate.py:138-141`）不变。

**I1 验证（2026-06-11）**：`uv run pytest apps/api/tests/retrieval/test_gate.py -q` -> 28 passed。I1 只完成 gate 输出语义；retrieval/controller/inspect/replay/metrics 对 `degrade` 的负向证据接线仍按 I2-I4 后续处理。

---

## 4. I2 — Packer 负向块（`NegativeEvidence` DTO + 渲染 + 排序 + 去重）

**文件**：`apps/api/app/retrieval/packer.py`（DTO 落在 `app/runtime/models.py`，见 D4；构造/去重/模板在 `retrieval/negative_evidence.py`，见 D6）
- [x] `NegativeEvidence` DTO 已在 `models.py` 定义（D4）。packer **只消费 `safe_text`**，从不读原始 `MemoryItem`。
- [x] `_TYPE_ORDER`（`packer.py:36-45`）插入 `"avoided_attempts"`，**位置在 project_memory 之后、tool_evidence 之前**（review 修正，见下「排序」）。
- [x] **不**加入 `_PROTECTED_ORDER` / `_is_protected` —— 负向块是 ordinary，可被预算丢弃（避坑提示优先级低于约束）。
- [x] `pack_context` 签名（`packer.py:324-332`）新增 `negative_evidence: Optional[list[NegativeEvidence]] = None`（默认 None，保既有调用与 baseline/variant_1 不变）。**不再传 `MemoryItem` 列表**。入参已是去重/截断后的列表（去重在 D6 builder 完成，packer 只渲染）。
- [x] 新增 `build_negative_evidence_block(ev: NegativeEvidence) -> ContextBlock`：
  - `type="avoided_attempts"`, `source="negative_evidence"`, `memory_id=ev.source_memory_id`, `provenance=ev.provenance`, `reason=ev.reason`。
  - `mode=="raw_failed_attempt"` → `"AVOIDED — a previous attempt failed; do NOT re-execute:\n{ev.safe_text}\n(Shown as negative evidence only — do not run this.)"`。
  - `mode=="sanitized_risk_notice"` → 直接用 `ev.safe_text`（已是 D6 按 `risk_kind` 选定的固定模板，不含原命令/参数/路径/flag）。
- [x] 在 `pack_context` 主体（`packer.py:401` 之后、排序 `:405` 之前）append；走 `_block_order` 排序与 ordinary drop（`:434-439`）。
- [x] `__all__` 导出新函数。

**sanitized 模板（三种，集中在 `negative_evidence.py` D6，不含任何原文）**：
```
secret:        "A previous failed attempt involved sensitive credentials or secrets and has been redacted. Do not repeat or expose secret-bearing operations."
destructive:   "A previous failed attempt involved a destructive operation and has been redacted. Do not repeat destructive operations of this kind."
tool_sensitive:"A previous failed attempt involved a sensitive tool operation and has been redacted. Do not repeat that sensitive operation pattern."
```

**block 顺序（review 修正 —— 正向约束先定方向，负向经验再限制）**：
```
active_state > active_path > history_summary
> project_memory / project_constraints > avoided_attempts > tool_evidence
> profile > procedural > episodic
```
理由：case_10 里最终选 `bun test` 的正向依据是 `project.runtime=bun`，应先于 npm 失败文本出现，避免 LLM 过度聚焦失败原文。负向块仍靠前但不压过 project 约束。

**TDD**（`tests/retrieval/test_packer_negative.py` 新增）：
- [x] `raw_failed_attempt` → 块含 `safe_text` + "do NOT re-execute"。
- [x] `sanitized_risk_notice` → 块为固定模板、不含任何原命令/参数 marker。
- [x] 排序：avoided_attempts 在 project_memory 之后、tool_evidence 之前。
- [x] 同一 source_state_node_id 多条 failed memory → 去重为 1 条；超过 `max_negative_blocks` 截断。
- [x] 极小预算 → 负向块进 dropped_blocks，protected 块保留。
- [x] `negative_evidence=None` → 输出与改动前逐块一致。

**I2 验证（2026-06-11）**：先观察 RED：`uv run pytest apps/api/tests/retrieval/test_packer_negative.py -q` 因缺少 `app.retrieval.negative_evidence` 失败；实现后 `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py -q` -> 35 passed，`uv run python -m compileall -q apps/api/app` passed。Review hardening 补充了 drift/历史数据防御：即便输入 outcome 错误地将 unsafe memory 标为 `degrade`，builder 仍会按 memory 风险标记输出 sanitized notice，不把原文交给 packer。下游检索检查 `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> 59 passed / 3 expected failures（I3-I4 未接线）。I2 只完成 DTO/builder/packer 能力；controller/inspect/replay/metrics 热路径接线仍按 I3-I4 后续处理。

---

## 5. I3 — Controller 主路径接线 ✅

**文件**：`apps/api/app/retrieval/controller.py`
- [x] `controller.py:257-258`：`accepted_outcomes` 自动只含 accept/warn（`o.accepted` 已改）；degrade 自动落入 `rejected_outcomes`（D5，计数自动闭合）。
- [x] 调用 **D6 唯一入口** `build_negative_evidence(outcomes, memories_by_id, max_blocks=3)`（传**全部 outcomes**，不预筛 degraded/sanitized；构造/二次 redaction/去重/截断/模板全在 builder 内，controller **不自行拼装 DTO、不自写模板**）。
- [x] `pack_context(...)`（`:273-280`）传 builder 返回的 `negative_evidence=...`。
- [x] `profile.metadata` 记 `degraded_count` / `hard_rejected_count`（D5）。`accepted_count`/`rejected_count`/`candidate_count` 走自动闭合，无需改 access schema。I3 同步记录 `negative_evidence_count` / `sanitized_negative_evidence_count`，为 I4 指标扩展保留热路径元数据。
- [x] `_build_warnings`（`controller.py:486-511`）**分两类文案（review#8）**：
  - `"N failed-branch memories injected as negative evidence."`（safe degraded）
  - `"M unsafe failed-branch memories were redacted into sanitized safety notices."`（unsafe sanitized）
  baseline/variant_1 无 degrade/sanitized，仍走旧 reject 文案。

**注意**（PITFALLS §1）：degraded 通道在 gate 之后从既有 candidate 派生，不新增检索入口，不绕过 `_RETRIEVABLE_STATUSES` 生命周期过滤。

**TDD**（`tests/retrieval/test_retrieval_flow.py`）：
- [x] variant_2 failed npm + completed bun → context_blocks 含 `avoided_attempts` 块、不含把 npm 当正向块；accepted_count 不含该 failed mem；`candidate_count == accepted_count + rejected_count`。
- [x] variant_1 / baseline_1 → 无 avoided_attempts 块（行为不变）。
- [x] destructive failed → 负向块是 sanitized 模板、不含原命令；`degraded_count` 不含它。

**I3 验证（2026-06-11）**：先观察 RED：新增 controller 热路径测试时 `avoided_attempts` 缺失（2 failed）；实现后 `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_injects_safe_failed_branch_as_negative_evidence apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_sanitizes_unsafe_failed_branch_negative_evidence -q` -> 2 passed。相关回归 `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py -q` -> 66 passed / 1 xfailed（I4 inspect_access 接线预期 xfail）。完整回归 `uv run pytest -q` -> 238 passed / 1 xfailed；`uv run python -m compileall -q apps/api/app` passed；deterministic benchmark `uv run python -m app.benchmark.runner --output-dir reports` -> `acceptance.passed=true`，case_1..case_9 acceptance 未回退。I3 review 修复了两个问题：replay `_ACCEPTED_DECISIONS` 不再把 `degrade` 视作正向 accepted；controller warnings/profile 改按实际 retained `avoided_attempts` 数量统计，预算 drop 时不误报 injected。复审未发现 P0/P1/P2 缺陷。I3 期间为保持现有 demo/benchmark 语义，evaluator/demo 的 contamination/action 判断已排除 `source="negative_evidence"` / `type="avoided_attempts"` 的负向块；metrics/replay 的 legacy `failed_branch_rejected` 计数已把 `*_degraded` / `*_sanitized` 失败原因纳入统计，完整 I4 仍负责 inspect/replay original-view negative evidence 重建和新增负向指标。

---

## 6. I4 — Inspect + Replay + Observability 接线（防 drift / 指标错乱）

> review 修正：从「隐含项」提升为首批独立 Issue。三处独立 `_ACCEPTED_DECISIONS` 必须与 gate 同口径。

**文件 1**：`apps/api/app/runtime/memory_runtime.py`（inspect_access `:866-883`）
- [x] `g.decision in (accept, degrade, warn)`（`:866`）拆成 `accepted_mems`(accept/warn) 与 degraded；调用 **D6 builder** 构造 `NegativeEvidence`（与 controller 同一函数，保证 byte-一致）。
- [x] `pack_context(...)` 传 `negative_evidence=...`，与主路径一致（防 replay drift）。

**文件 2**：`apps/api/app/observability/replay.py`
- [x] `_ACCEPTED_DECISIONS`（`:38`）：移除 `degrade`（accepted 只含 accept/warn）。
- [x] 原始视图重建（`:186-205`）：degrade 的 gate_log 不再进 `accepted_memories`；改为调用 **D6 builder** 重建 `NegativeEvidence` 传 `pack_context`（与主路径同序）。**需 join 当前 memory snapshot**（gate_log 只有 decision/reason/score，缺 branch_status/risk_flags/sensitivity/content/source_state_node_id/memory_type）；若 memory 已不存在，则只产 `source_memory_id` 级 replay warning，**不尝试恢复 `raw_failed_attempt` 文本**（review#10）。
- [x] drift 严重度规则（`:433-436` 扩展，review#3）：
  - `reject(sanitized)` → replay accept/degrade：**critical**（可能泄漏危险文本）。
  - `reject(sanitized)` → replay reject 但 reason 变：warning。
  - `degrade` → replay accept：**critical**（失败经验被当正向事实）。
  - `degrade` → replay reject：warning（负向经验丢失，非安全事故）。
  - `accept` → replay degrade/reject：warning。

**文件 3**：`apps/api/app/observability/metrics.py`
- [x] `_ACCEPTED_DECISIONS`（`:21`，`:92` 使用）：移除 `degrade`，否则 dashboard/report 把负向经验统计成正向注入。
- [x] 新增显式指标（review#3/#4，读 gate_log decision/reason 或 block source/type，无需 DB 字段）：`degraded_negative_evidence_count`（degrade gate 数）、`sanitized_failure_notice_count`（`*_sanitized` reject 数）、`negative_evidence_block_count`（经 shared builder 去重/截断后的负向块数；replay 侧按 original reconstructed context 中实际负向块统计），纳入 observability summary + report/dashboard，使该特性在报告里可见。

**TDD**：
- [x] `tests/retrieval/test_retrieval_flow.py`：inspect_access 负向块与主路径一致（移除 I4 xfail）。
- [x] `tests/observability/test_replay.py`：含 degrade 的 access replay 无虚假 drift；degrade memory 不出现在正向块；`reject(sanitized)→accept` 判 critical；source memory 缺失时只产 warning 不报错。
- [x] `tests/observability/test_metrics.py`：degrade 不计入 accepted/injection 指标；`degraded_negative_evidence_count` / `sanitized_failure_notice_count` / `negative_evidence_block_count`（builder 去重后 block 数）正确。

**I4 验证（2026-06-11）**：先观察 RED：inspect_access 仍把 degraded memory pack 成正向 `tool_evidence`，replay original view 缺少 `avoided_attempts` 且 source memory 缺失时无 warning，metrics 缺少显式 negative-evidence counters。实现后补充审查修复了 inspect/replay candidate view 对 sanitized unsafe failed memory 的原文泄漏风险、inspect 缺失 source memory 无 warning、`reject(sanitized)->degrade` critical 覆盖、replay 正向污染断言、metrics builder 去重语义测试和文档过期定义。最终 targeted I4 `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_inspect_access_unchanged_after_pack_result_refactor apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_sanitizes_unsafe_failed_branch_negative_evidence apps/api/tests/retrieval/test_retrieval_flow.py::test_inspect_access_warns_without_raw_negative_evidence_when_source_memory_missing apps/api/tests/observability/test_replay.py::test_replay_reconstructs_negative_evidence_without_false_context_drift apps/api/tests/observability/test_replay.py::test_replay_sanitizes_original_and_replayed_candidate_views_for_sanitized_failure apps/api/tests/observability/test_replay.py::test_replay_marks_sanitized_reject_to_accept_as_critical apps/api/tests/observability/test_replay.py::test_replay_marks_sanitized_reject_to_degrade_as_critical apps/api/tests/observability/test_replay.py::test_replay_warns_without_raw_negative_evidence_when_source_memory_missing apps/api/tests/observability/test_metrics.py::test_negative_evidence_metrics_are_explicit_and_not_positive_injection apps/api/tests/observability/test_metrics.py::test_negative_evidence_block_count_uses_builder_dedupe_not_gate_count -q` -> 10 passed；相关回归 `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py -q` -> 90 passed；`uv run pytest -q` -> 248 passed；`uv run python -m compileall -q apps/api/app` passed；deterministic benchmark `uv run python -m app.benchmark.runner --output-dir reports` -> `acceptance.passed=true`（existing 8/8 checks true）。

---

## 7. I5 — Benchmark case_10 + case_11 + evaluator 修复

### 关键回归修复（必须同批）
`evaluator.contaminated()`（`evaluator.py:31-36`）只要任何 block 含 "npm"+"failed" 即判污染，且 `decide_action`（`evaluator.py:21-28`）先调它 → 负向块会让 variant_2 **误报污染 + 误选 npm**。
- [x] **evaluator 显式分区（review#5，比只改 `contaminated()` 更稳）**：在 `evaluate_case` 入口计算
  `positive_blocks = [b for b in ctx.context_blocks if b.type!="avoided_attempts" and b.source!="negative_evidence"]`、`negative_blocks = 其余`。
  - `contaminated()` / 正向 action 判断**只看 `positive_blocks`**（不再扫全部 block 文本）。
  - `negative_lesson_retained` **只看 `negative_blocks`**。
  - `unsafe_negative_leakage` 只看 `negative_blocks`。
  - `decide_action`（`:21-28`）改为接收 `positive_blocks` 而非全 ctx，避免负向区 npm 文本影响动作判定。

### 改动文件
- [x] `apps/api/app/benchmark/cases.py`：
  - **case_10（仅测 safe failure learning，不伪测 unsafe，review#11）** `_seed_avoid_repeating_failed_attempt`（仿 `_seed_failed_branch` `cases.py:91-110`）：确立 `project.runtime=bun` → 失败步 npm test（tool_result status=failed，content 如 "Tried npm test, failed: npm unavailable"）→ `rollback_branch` → query `"I previously tried npm test and it failed. How should I run tests now?"`（提升召回稳定性；`decide_action` 仍应选 `bun test`）。
    - `extra`：`{"negative_lesson_markers": ["npm"], "failure_learning_case": True}`（**删去 `unsafe_negative_markers`**——本 case 未 seed destructive，不假装测 sanitized）。
  - **case_11（专测 sanitized destructive，review#11）** `_seed_sanitized_failed_destructive_attempt`：seed 一条 rolled_back destructive tool_evidence（如 `git push --force` / `rm -rf`），**query 必须与该 memory content 有足够 token overlap 以稳定召回（review#5）**，例如 `"I previously tried a force push / destructive cleanup and it failed. What should I avoid?"`（含 force push / destructive / failed 等 token），否则候选池命不中、sanitized notice 不出现、测试不稳定。
    - `extra`：`{"unsafe_negative_markers": ["rm -rf","--force","git push --force"], "sanitized_failure_case": True}`。
  - 加入 `CASES`（`cases.py:376-404`）：`case_10_avoid_repeating_failed_attempt`、`case_11_sanitized_failed_destructive_attempt`。
- [x] `apps/api/app/benchmark/evaluator.py`：
  - 显式分区（见上）。
  - `CaseMetrics` 新增：`positive_contamination(+present)` / `negative_lesson_retained(+present)` / `correct_action` / `unsafe_negative_leakage(+present)` / `sanitized_notice_present`，复用 case_present gating。
  - `evaluate_case` 新增参数 `negative_lesson_markers` / `unsafe_negative_markers` / `failure_learning_case` / `sanitized_failure_case`：
    - case_10（failure_learning_case）：`negative_lesson_retained`=negative_blocks 含 "npm"；`positive_contamination`=npm 在 positive_blocks；`correct_action`=final_action=="bun test"。
    - case_11（sanitized_failure_case）：`unsafe_negative_leakage`=negative_blocks 含任一危险 marker 原文（应为 0）；断言负向块为 sanitized 模板。
- [x] `apps/api/app/benchmark/runner.py`：
  - `_METRIC_FIELDS`（`runner.py:22-37`）追加新指标。
  - `_run_case` 透传新 extra（仿 stale/compaction `runner.py:128-131`）。
  - `_summarize` 新增对应 *_rate（present gating）。
  - `_acceptance`（`runner.py:220-260`）新增 checks：
    - **`variant_2_learns_from_failure_without_repeating`**（case_10）= `v2.positive_contamination_rate==0 ∧ negative_lesson_retained_rate==1 ∧ correct_action_rate==1`；可选 `variant_1_does_not_retain_failure_lesson`（v1 negative_lesson_retained_rate==0）。
    - **`variant_2_sanitizes_destructive_failure_without_leakage`**（case_11）= `v2.unsafe_negative_leakage_rate==0 ∧ sanitized_notice present`。
  - `_write_markdown` 新增列（不破坏既有列）。
- [x] `apps/api/app/runtime/memory_runtime.py` `_benchmark_summary_from_records`（`:917-950`）：若驱动 observability，补同名 rate 字段。

### 计数变化
cases 9→**11**；strategies 4 不变；runs `9×4=36`→**`11×4=44`**。

**TDD**（`tests/benchmark/test_runner.py` + `tests/api/test_dashboard.py` 计数）：
- [x] CASES 含 case_10、case_11，results=44。
- [x] case_10 variant_2: positive_contamination=0, negative_lesson_retained=1, correct_action=1。
- [x] case_10 variant_1: negative_lesson_retained=0。
- [x] case_11 variant_2: unsafe_negative_leakage=0，负向块为 sanitized 模板（不含原命令）。
- [x] acceptance 含两个新 check 且为 True。
- [x] case_1..case_9 既有指标不变（尤其 case_2 contamination、case_9 compaction acceptance）。

**I5 验证（2026-06-12）**：TDD RED 先观察到 benchmark 仍为 9 cases/36 results、`evaluate_case` 不支持 negative lesson 参数、acceptance 缺少两个新 check；实现后 targeted `uv run pytest apps/api/tests/benchmark/test_runner.py::test_evaluator_keeps_negative_evidence_out_of_positive_contamination_and_action apps/api/tests/benchmark/test_runner.py::test_evaluator_scores_sanitized_negative_notice_without_raw_marker_leakage apps/api/tests/benchmark/test_runner.py::test_run_benchmark_writes_markdown_and_json_reports apps/api/tests/benchmark/test_runner.py::test_run_benchmark_meets_mvp_acceptance apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_cases_and_results apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows -q` -> 6 passed；相关回归 `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> 98 passed；full regression `uv run pytest -q` -> 249 passed；benchmark `uv run python -m app.benchmark.runner --output-dir reports` -> 11 cases / 44 results，`acceptance.passed=true` 且 10/10 checks true。Review hardening 发现 `_acceptance` 对 present-gated zero-rate 指标存在空样本误通过风险，已补充具体 case row + `*_present` flag 守卫，并新增 `test_acceptance_requires_present_rows_for_failure_learning_checks` / `test_acceptance_requires_present_rows_for_zero_leakage_checks`。Post-review verification：`uv run pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> 14 passed；相关回归 -> 100 passed；`uv run pytest -q` -> 251 passed；`uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (10/10 checks true)`。

---

## 8. I6 — 文档同步（首批收尾，benchmark 稳定后，仅编辑既有文件） ✅

- [x] `docs/design/ROADMAP.md`：§9.1 已标注首批 I1-I6 完成；后续主线 Phase 3.5、6-strategy benchmark、§13 hardening、§10/§11 provider/key ontology 均已完成；I7 compaction negative retained 已启动并完成 I7.1-I7.4。
- [x] `docs/design/CONTEXT_COMPACTION_PLAN.md`：新增 "C6: Failure-aware negative retained facts" 章节作为 I7 设计草案占位；当前该交叉项已进入 I7 实现，I7.1-I7.4 已完成，并保持不改变 prompt 注入语义。
- [x] `.ai/PROJECT_STATE.md`：按 AGENTS.md 约定更新 current state / changed files / next action；当前 I7.1-I7.6 complete，benchmark 已扩展到 case 13 与 acceptance `variant_2_retains_negative_lesson_under_compaction`。历史 benchmark 计数 36→44、新 acceptance check 名（`variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`）保留为 I5 记录。

**I6 验证（2026-06-12）**：本 Issue 仅做文档/项目记忆同步，不改变运行时代码。同步范围包括 `docs/design/ROADMAP.md`、`docs/design/CONTEXT_COMPACTION_PLAN.md`、本计划、`AGENTS.md`、`.ai/PROJECT_STATE.md`、`.ai/REQUIREMENTS.md`、`.ai/IMPLEMENTATION_PLAN.md`、`.ai/DECISIONS.md`。Post-I6 验证：stale-reference grep 未发现旧的 I6-pending / I1-I5-only 状态表述；targeted benchmark/dashboard regression `uv run pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> 14 passed；full regression `uv run pytest -q` -> 251 passed；deterministic benchmark + reproducibility `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (10/10 checks true)`。

---

## 9. I7 — Compaction 负向 retained（独立 Issue） ✅

**后置理由**：触及 `ContextCompactionLog` 持久化快照 + replay（改安全规则=改持久化语义，可能引入 `compaction_drift`，需 replay 回归/快照迁移）；且失败 memory 无 key/value，`RetainedFact` 白名单（project./endpoint./profile./procedure.）不适配；现有 summarizer 校验（`summarizer_provider.py:318` `_validate_result`）会禁止发明 facts、要求 source ids 完全一致，贸然塞 failed lesson 会冲突。首批 I1-I5 已能在检索/打包路径端到端证明价值。

**实际落地（2026-06-13/14）**：
- [x] 采用 dedicated metadata channel：新增 `RetainedNegativeEvidence` 与 `ContextCompactionLog.retained_negative_evidence` / `PendingCompactionLog.retained_negative_evidence`，不复用 positive `retained_facts`，不进入 summarizer 正向事实白名单。
- [x] Packer 仅在预算压缩丢弃标准负向 prompt block（`type="avoided_attempts"` 且 `source="negative_evidence"`）时，从 safe `NegativeEvidence` DTO 恢复 metadata；不会把 `avoided_attempts` 变成 protected block，也不会强制注入 prompt。
- [x] replay / metrics / reports / trace bundle 直接读取 compaction log retained-negative metadata，并做防御性脱敏；`negative_evidence_block_count` 保持表示实际 prompt blocks，retained metadata 使用独立计数。
- [x] Benchmark 新增 `case_13_compaction_retains_negative_lesson` 与 acceptance `variant_2_retains_negative_lesson_under_compaction`，验证 metadata retention、正向污染为 0、不泄漏 unsafe markers、且 task success 仍来自既有 positive/project context。

**I7 验证（2026-06-14）**：I7.5 RED `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "compaction_retains_negative" -q` 先观察到 2 failed（缺 case 13 与 acceptance key）；实现后 targeted -> 2 passed，review hardening 后 benchmark suite `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q` -> 27 passed。I7 closeout：affected regression `uv run --extra dev pytest apps/api/tests/retrieval apps/api/tests/observability apps/api/tests/benchmark/test_runner.py apps/api/tests/storage/test_migrations.py -q` -> 221 passed, 1 skipped；compile `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed；full regression `uv run --extra dev pytest -q` -> 477 passed, 1 skipped；benchmark + reproduce `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`；generated report unsafe-marker scan（`rm -rf`, `/prod`, `sk-`, `password`, `Authorization`）-> passed。

---

## 10. 端到端验证

每个 Issue「先写测试看红，再实现看绿」。

```bash
# 聚焦子集（迭代中）
uv run pytest -q apps/api/tests/retrieval/test_gate.py
uv run pytest -q apps/api/tests/retrieval/test_negative_evidence.py
uv run pytest -q apps/api/tests/retrieval/test_packer_negative.py
uv run pytest -q apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py
uv run pytest -q apps/api/tests/runtime/test_memory_runtime_trace.py
uv run pytest -q apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py
uv run pytest -q apps/api/tests/benchmark/test_runner.py

# 全量回归
uv run pytest -q

# benchmark（确认 44 runs + 两个新 acceptance check 通过）
uv run python -m app.benchmark.runner --output-dir reports

# 全链路可复现（最终验收门：acceptance.passed 必须含 variant_2_learns_from_failure_without_repeating
# 与 variant_2_sanitizes_destructive_failure_without_leakage 均为 True）
bash scripts/reproduce.sh
```

---

## 11. 关键文件清单
- `apps/api/app/retrieval/gate.py` — 三路输出 + safe/unsafe 显式分流（I1）
- `apps/api/app/runtime/models.py` — `NegativeEvidence` DTO（I2）
- `apps/api/app/retrieval/negative_evidence.py` — **新增**：共享 builder（构造/二次 redaction/去重/sanitized 模板，D6，三路径单点真相）（I2）
- `apps/api/app/retrieval/packer.py` — `avoided_attempts` block 渲染 + 排序（I2）
- `apps/api/app/retrieval/controller.py` — degraded 通道接线 + 计数闭合 + warnings（I3）
- `apps/api/app/runtime/memory_runtime.py` — inspect_access 三态接线（I4）+ benchmark summary（I5）+ I7 compaction（后置）
- `apps/api/app/observability/replay.py` / `metrics.py` — `_ACCEPTED_DECISIONS` 同步，防 drift / 指标错乱（I4）
- `apps/api/app/benchmark/evaluator.py` — `contaminated()` 修复（关键）+ case_10 指标（I5）
- `apps/api/app/benchmark/cases.py` / `runner.py` — case_10 + acceptance（I5）
- `docs/design/ROADMAP.md` / `CONTEXT_COMPACTION_PLAN.md` / `.ai/PROJECT_STATE.md` — 文档同步（I6）
