# LCC WP1A Blank/Native Current-Commit Acceptance Design

**日期：** 2026-08-30

**状态：** 已批准设计，等待书面规格审阅

**目标平台：** Licensed PSCAD 4.6.2 Legacy Automation

## 1. 目标

在当前 clean commit 上重新执行 blank/native LCC 路径，证明现有
`BlankLccBuilderService` 能够从官方只读 CIGRE LCC 工程生成隔离 derived
project 与 companion library，完成真实编译、仿真、inverter AC disturbance 和
四项换相故障检查，并产生可由 WP0 evidence infrastructure 严格索引的 durable
report。

成功后只更新 program baseline 的 `lcc.blank_native` scope：

```text
capability_state = simulated
licensed_status  = PASS
builder_path     = lcc.blank_native
```

WP1A 不把该路径标记为 `accepted`。independent golden、fixed autonomous 和
parametric LCC 分别留给 WP6、WP1B/C 和 WP1D。

## 2. 当前基础

WP0 已提供：

- strict program baseline validator；
- `build_run_metadata()`；
- `index_explicit_reports()`；
- `apply_scope_report()`；
- static/licensed program preflight；
- source、Master、compiler 和 process immutability evidence。

当前 program baseline 将 `lcc.blank_native` 记录为历史上达到 `simulated`，但
`licensed_status=NOT_RUN_ON_CURRENT_COMMIT`，且 `evidence_run_id=null`。旧 journal
没有 report-owned commit，不能被提升为当前 PASS。

WP1A 使用的官方只读源固定为：

```text
D:/pscad-mcp-example-inspection-20260829/
  cigre_lcc_bidirectional/Cigre_LCC_Bidirectional.pscx
```

当前 blank/native production path 已具有：

- explicit template resolution；
- native template 与 retained Master reference audit；
- Master registry/hash 证据；
- isolated staging、plan hash、journal 和 build lease；
- derived project/companion materialization；
- compile、simulation、legacy numbered output discovery；
- commutation waveform evaluation；
- atomic publication 和 final compile。

WP1A 不重写上述 lifecycle，只为它增加 licensed acceptance orchestration、durable
report 和显式 baseline promotion。

## 3. 范围

### 3.1 包含

1. 当前 commit、branch 和 clean-worktree preflight；
2. 官方 LCC source、Master、registry、compiler hash；
3. 全新时间戳 acceptance workspace；
4. 使用 production `BlankLccBuilderService` plan/build/status API；
5. `published` journal 和完整状态链验证；
6. project、library、scenario source、output parts 的路径与 hash；
7. disturbance、failure indication、bounded DC response、recovery；
8. current-commit durable report；
9. 两阶段 report promotion；
10. `lcc.blank_native -> simulated/PASS` 的 scoped baseline 更新。

### 3.2 不包含

- fixed autonomous companion 物理化；
- fixed LCC dynamic acceptance；
- parametric ratings 或 operating-mode matrix；
- independent golden；
- `accepted` capability；
- `lcc.master_bindings` scope promotion；
- MMC 或 PSCAD 5.x；
- 修改官方 template、安装目录 Master 或既有用户工程。

## 4. 采用方案

采用独立 acceptance orchestration layer。现有 builder service 继续负责所有工程
lifecycle；新的 orchestration layer 只负责运行边界、证据收集、报告与 promotion。

未采用的方案：

- 不把 report/baseline mutation 嵌入 `BlankLccBuilderService`，避免普通构建隐式
  修改 repository truth；
- 不在 standalone test 中复制 build lifecycle，避免 production 与 acceptance
  runner 漂移；
- 不提前合并 fixed、parametric 或 golden 路径。

## 5. 组件边界

### 5.1 Native Acceptance Orchestrator

新增模块：

```text
pscad_mcp/hvdc/builders/lcc/native_acceptance.py
```

职责：

- 解析只读 acceptance request；
- 调用 WP0 static preflight；
- 创建 Legacy `PscadService` 与 `BlankLccBuilderService`；
- 生成 exact plan 并提交 build；
- poll build status 到 terminal state；
- 校验 journal、artifacts、waveform acceptance 和 source immutability；
- 无论成功或失败都清理自有 PSCAD session；
- 原子写入外部 durable report；
- 使用 status-aware strict validator 校验成功/失败报告的完整字段集；
- 通过 indexer 回读同一报告。

它不修改 `docs/acceptance/lcc-mmc-program-baseline.json`。

同一模块公开 `validate_native_lcc_acceptance_report()`。validator 使用严格、
status-aware field sets：PASS 必须含完整 artifacts 与四项 physical evidence；FAIL
必须含 failure stage/error/cleanup，并用 `null` 明确尚未产生的 artifacts。

### 5.2 CLI

新增模块：

```text
pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py
```

CLI 提供两个显式动作：

```text
run      在 clean commit 上执行 licensed acceptance，写外部 report
promote  验证 report，并只更新 program baseline
```

`run` 与 `promote` 不在同一隐式事务中。operator 必须先看到 report path、hash、
commit 和 verdict，才能执行 promotion。

### 5.3 PowerShell Runner

新增脚本：

```text
scripts/run_blank_lcc_native_acceptance.ps1
```

脚本负责：

- 定位 worktree/shared Python runtime；
- 验证 named branch 与 clean worktree；
- 验证 official source、Master、compiler 和 baseline；
- 拒绝外部 PSCAD 进程；
- 创建 timestamped run directory；
- 调用 CLI `run`；
- 验证 report JSON、SHA-256、commit 和零 PSCAD 残留；
- 打印 promotion 所需的 exact report path。

脚本默认不调用 `promote`。

### 5.4 Generic Baseline Promotion Helper

新增模块：

```text
pscad_mcp/acceptance/promotion.py
```

该 helper 可被后续 WP1B-D 和 MMC work packages 复用，但 WP1A 只允许
`expected_scope=lcc.blank_native`。

promotion 必须在 report 对应的同一 checkout 上执行，并要求：

- `HEAD == report.commit`；
- branch 与 report repository metadata 一致；
- promotion 前 worktree clean；
- report 重新通过 `index_explicit_reports()`；
- report status 为 `PASS`；
- capability 为 `simulated`；
- kind 为 `licensed_simulation`；
- scope/builder 分别为 `lcc.blank_native`；
- report source/Master/registry hashes 与 baseline/current files 一致。

## 6. 数据流

### 6.1 Run Phase

```text
clean git commit
  -> program/static preflight
  -> Master registry + official template audit
  -> BlankLccBuilderService.plan_model
  -> BlankLccBuilderService.build_model
  -> get_build_status until terminal
  -> validate published journal/artifacts/waveforms
  -> cleanup PSCAD
  -> source/Master before-after verification
  -> durable report write
  -> report re-index
```

run phase 只写 `D:/PSCAD-Workspace/.../<timestamp>/`。任何 repository file 都保持
不变，因此报告 commit 对应真实 clean code state。

### 6.2 Promote Phase

```text
clean checkout at report.commit
  -> re-index report
  -> validate target scope and PASS contract
  -> advance candidate baseline repository.base_commit
  -> invalidate prior PASS from older commits
  -> apply lcc.blank_native report
  -> validate complete candidate baseline
  -> atomically replace checked-in baseline JSON
```

promotion 后 worktree 预期只包含 baseline 和必要状态文档变更，等待单独 commit。

## 7. Commit Advancement Semantics

program baseline 的 `repository.base_commit` 是当前证据目标 commit。promotion 到
新 commit 时：

1. 将 candidate baseline 的 commit/branch 更新为 report 对应值；
2. 检查每个 scope 当前 `evidence_run_id`；
3. 若对应 report commit 不是新 commit，则：
   - `licensed_status=NOT_RUN_ON_CURRENT_COMMIT`；
   - `evidence_run_id=null`；
   - 保留已证明的 capability state；
4. 再应用目标 `lcc.blank_native` report；
5. 其他 scope 不得获得新 evidence 或 PASS。

历史 reports/sources 可保留供审计，但不能继续支持 current scope PASS。

## 8. Durable Report Contract

报告根对象先合并 `build_run_metadata()` 返回的基础字段，再由 orchestrator 增加
`status` 和领域证据：

```text
scope            = lcc.blank_native
builder_path     = lcc.blank_native
kind             = licensed_simulation
capability_state = simulated
commit           = full 40-character git commit
generated_at_utc = UTC RFC3339
status           = PASS | FAIL  # orchestrator-owned
```

除此之外必须包含：

### 8.1 Repository and Environment

- branch、commit、worktree clean；
- PSCAD backend/version/x64/license；
- compiler configuration/executable hashes；
- static preflight snapshot/canonical hash；
- process inventory before/after。

### 8.2 Sources

- official template path、before hash、after hash；
- Master path、before hash、after hash；
- Master binding registry path/hash；
- packaged asset manifest/hash；
- source files 均为 regular、非 symlink/reparse。

### 8.3 Build

- project name、workspace 和 build ID；
- plan hash；
- journal path/hash；
- exact history；
- terminal state；
- structured error（失败时）。

成功状态链必须等于：

```text
validated
  -> staging_created
  -> compiled
  -> simulated
  -> acceptance_passed
  -> published
```

### 8.4 Artifacts

- published project path/hash；
- companion library path/hash；
- scenario source path/hash；
- selected output file path/hash；
- every numbered output part path/hash；
- output metadata `.inf`/`.infx` path/hash（存在时）。

### 8.5 Physical Acceptance

四项 check 必须全部为 true：

```text
disturbance
failure_indication
bounded_dc_response
recovered
```

数值 evidence 至少包含 fault time/duration、current limit、observed DC current
peak、failure indicator channel 和 recovery window。channel path、units、domain 和
sample count 必须来自真实 output read-back。

### 8.6 Exclusions

PASS report 必须显式列出：

```text
fixed_autonomous
parametric_lcc
independent_golden
final_accepted
```

## 9. Failure Semantics

任何阶段失败都写 durable FAIL report，但不能执行 baseline promotion。

失败报告使用 `kind=licensed_simulation`、`capability_state=failed`、
`status=FAIL`，并记录：

- failure stage；
- structured error code/message/details；
- 已完成的 journal history；
- 已知 artifact/source hashes；
- quit/cleanup error；
- remaining processes。

关键 fail-closed 条件：

- dirty/wrong commit；
- official template 或 Master/registry hash 变化；
- plan hash stale；
- Master reference missing/ambiguous；
- project settings/read-back 不匹配；
- compile/simulation failure 或 timeout；
- output missing/escaping/symlinked；
- 四项 acceptance 任一 false；
- final publication/compile mismatch；
- source changed during run；
- owned PSCAD 无法退出；
- report index/TOCTOU failure；
- cross-scope/cross-builder/cross-commit promotion。

runner 不得通配终止用户进程。若自有进程清理失败，报告 FAIL 并要求人工关闭。

## 10. Testing Strategy

### 10.1 Offline Unit Tests

- request/report strict schema；
- exact metadata、UTC time、commit、scope、builder 和 kind/state；
- artifact/hash completeness；
- success history exact order；
- missing/extra field rejection；
- failure report serialization；
- atomic report write 与 TOCTOU/reparse rejection；
- promotion scope ownership；
- commit advancement 与旧 PASS invalidation；
- only `lcc.blank_native` changes on successful promotion；
- FAIL/INCOMPLETE report promotion rejection。

### 10.2 Fake-Service Tests

- production plan/build/status methods are invoked rather than duplicated；
- terminal `published` produces `simulated/PASS` report；
- stale plan、source/Master changes、output escape、missing channel、failed check、
  final compile failure 和 cleanup failure 均产生 FAIL；
- report is written after cleanup evidence；
- baseline remains byte-identical during run phase。

### 10.3 Licensed PSCAD 4.6.2 Gate

1. clean named branch and exact commit；
2. no external PSCAD process；
3. fresh timestamped workspace；
4. official template and Master registry audit；
5. materialize project and companion；
6. compile and simulation；
7. inverter AC disturbance；
8. real output discovery/read-back；
9. four physical checks PASS；
10. publication and final compile；
11. all source hashes unchanged；
12. report re-index PASS；
13. PSCAD remaining processes = 0。

licensed report 完成后再执行 explicit promotion，并运行 baseline tests、targeted lint
和 full repository suite。

## 11. Exit Criteria

WP1A 只有在以下条件全部成立时完成：

- licensed report terminal status 为 PASS；
- report commit 等于运行时 clean HEAD；
- build state 为 `published`；
- journal history 精确完整；
- project、library、scenario、output artifacts 均有 hash；
- disturbance、failure indication、bounded DC response、recovery 全部 true；
- official template、Master、registry、compiler 前后不变；
- report 通过 explicit index；
- PSCAD 清理完成且无残留；
- promotion 只更新 `lcc.blank_native`；
- baseline 显示 `simulated/PASS`；
- `accepted` 仍未声明；
- focused/full tests、lint 和 code review 无 unresolved Critical/Important finding。

## 12. WP1B Handoff

WP1A 合并后允许开始 WP1B companion physicalization。WP1B 不得把 native
template PASS 当作 fixed autonomous evidence；它必须使用自己的 builder path、
report 和 scope transition。
