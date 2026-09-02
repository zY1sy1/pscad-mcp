# LCC WP1C 原生动态闭环构建工作设计

**日期：** 2026-09-02

**状态：** 已于 2026-09-02 获用户批准；批准范围为编写实施计划，实施、licensed PSCAD 运行、基线提升、合并和推送仍按独立证据门执行

**范围：** `lcc.fixed_autonomous` 的 WP1C 原生动态闭环，以及同一候选提交上的 WP1B 无故障回归；WP1D 只定义交接门

**目标：** 将当前已经具备离线合同、动态资产和执行器骨架的 fixed LCC 构建器，收口为可在 licensed PSCAD 4.6.2 上从规划、构建、编译、扰动仿真、输出读取、物理判据到持久化报告完整运行的工程路径，同时继续把 independent golden 和最终 `accepted` 留给 WP6。

## 1. 当前证据基线

本文档以本地 `main` 的 `2554d015d42ed19c0dce1dd74af21fb752b96d92` 为调查基线。调查时工作区干净，本地分支领先 `origin/main` 140 个提交，尚无绑定该提交的 fixed LCC licensed report。

当前状态必须按证据层级解释：

| 层级 | 当前事实 | 允许的结论 |
| --- | --- | --- |
| WP1B fixed companion 和无故障 smoke | 报告 `fixed-lcc-20260901-080458-594` 在提交 `3a09c8f` 上记录六个 Definition fixture、完整拓扑、final 重编译、0.1 s/2,001 样本和零残留 PSCAD 进程 | 历史 `simulated/PASS`；不能作为 `2554d01` 的 current-commit PASS |
| WP1C 报告合同和 evaluator | `dynamic_acceptance.py`、CLI 和 PowerShell evaluator 已存在 | 已实现并可离线测试；不等于实机动态通过 |
| WP1C fault/event 资产 | fixed blueprint 已声明三条分相故障支路、`tfault`、fault-active 输出和动态事件 | packaged/offline capability；不等于 PSCAD 4.6.2 已编译或已运行 |
| WP1C planner/executor | `wp1c_dynamic` profile、live inventory gate 和动态事件注册逻辑已存在 | 内部路径已具备骨架；公开 MCP 工具和 licensed end-to-end runner 尚未闭环 |
| 测试 | LCC 定向测试 `181 passed, 2 skipped`；关闭许可开关后全仓 `2401 passed, 47 skipped`；fatal Ruff 与 `git diff --check` 通过 | 当前离线回归通过 |
| licensed current-commit evidence | 未找到 commit 为 `2554d01` 的 JSON report | `NOT_RUN_ON_CURRENT_COMMIT` 语义；不得沿用旧 PASS |
| 最终验收 | packaged golden 仍明确是 placeholder | 未 `accepted` |

启用机器上既有的 `PSCAD_MCP_ACCEPTANCE=1` 运行全仓测试时，另发现两个非 LCC licensed failure：HVDC 派生工程无输出通道，以及 Legacy repair 返回文案与旧断言不一致。它们不改变 LCC 定向结论，但若发布门要求所有 opt-in licensed tests 全绿，必须单独处置并重新验证。

## 2. 已确认的闭环缺口

### 2.1 公开入口没有暴露动态 profile

`LccBuilderService.plan_model()` 和 `build_model()` 已接受 `verification_profile`，但 `plan_lcc_model` 与 `build_lcc_model` 的 MCP 工具签名没有该参数。用户无法通过公开的 plan-hash/confirm 工作流选择 `wp1c_dynamic`。

### 2.2 当前 runner 只评价输入文件

`run_fixed_lcc_dynamic_acceptance.ps1` 当前要求调用者预先提供 `Samples`、`Golden`、`Contract` 和 `Report`。它没有创建隔离 workspace、调用 fixed builder、编译、运行 PSCAD、发现 OUT/INF、生成规范化 samples 或记录进程清理。因此它是 evaluator wrapper，不是 WP1C licensed end-to-end runner。

### 2.3 动态控制依赖尚未由 PSCAD 4.6.2 实证

当前 executor 要求 backend 同时报告：

- `native_schedule=true`；
- `simulation_clock=true`；
- `time_basis=EMTDC`；
- `schedule_timed_controls()` 对每条事件给出一一对应的 acknowledgement。

Legacy backend 只会在实际 PSCAD project 对象暴露相应方法时声明这些能力。当前安装的 Python 包中未检索到 `schedule_timed_controls` 或 `get_simulation_time` 实现，因此不能把 native Automation scheduler 当作已具备能力。最终判断仍必须来自 live capability readback；缺失时必须返回 `LCC_DYNAMIC_EVENT_UNAVAILABLE`。

### 2.4 工程内部 timer 尚未成为三相 breaker 的可验证控制源

fixed blueprint 中 `master:tfault` 的 `Y` 输出目前连接到 fault-active 测量链；三相 `master:breaker1` 由动态事件声明修改 `NAME`。必须证明以下两种机制之一在 PSCAD 4.6.2 中真实可编译、可运行、可回读：

1. `tfault.Y` 通过明确的工程内变量绑定，同时驱动三相 breaker 的 `NAME` variable；
2. PSCAD project 提供经过实证的 native EMTDC scheduler，在仿真前原子注册三相 apply/clear 事件。

未证明前不得宣称故障已施加。

### 2.5 默认仿真时长不足以覆盖完整恢复窗口

当前事件在 0.8 s 施加、0.9 s 清除，动态 evaluator 默认恢复窗口为 0.5 s，而 blueprint 默认仿真时长为 1.0 s。WP1C 默认运行必须覆盖至少 1.4 s；本文档固定推荐值为 1.5 s，并要求报告记录实际终止时间和有效恢复样本范围。

### 2.6 动态布尔结论尚未从原始波形独立推导

当前 evaluator 接受 samples 中预先计算的 `dynamic.disturbance`、`failure_indication`、`recovered` 和 DC current peak/limit。正式 licensed runner 必须从 commit-bound OUT/INF 原始通道和事件配置推导这些字段，记录算法、窗口、输入 selector、单位和样本数，不能接受调用者提供的无来源布尔量作为最终证据。

## 3. 方案比较

### 3.1 方案 A：工程内 EMTDC timer 驱动，推荐

在构建阶段将 `tfault.Y` 绑定到三相 breaker 的 variable control，事件时刻由 EMTDC 模型内部产生。executor 负责在编译前验证绑定和参数回读，不在仿真过程中依赖 Automation 参数写入。

优点：

- 时序天然属于 EMTDC simulation time；
- 适配 PSCAD 4.6.2 已有 `tfault` 定义；
- 不依赖尚未实证的 project runtime API；
- 保存、reload 和重编译后仍可审计控制拓扑。

代价：

- 必须准确建模 `breaker1.NAME` 的 variable-expression 语义；
- catalog、schema、planner、executor 和 topology validator 都需要相应合同；
- 需要独立 fixture 证明三相 breaker 同步动作。

### 3.2 方案 B：Automation native scheduler

保留当前事件注册设计，仅在 live capability probe 证明 PSCAD project 同时提供 native scheduler 和 simulation clock 后执行。

优点：事件 acknowledgement 和请求时间可直接写入 report，未来 PSCAD 版本可复用。

代价：当前 PSCAD 4.6.2 环境尚无实证；若 provider 缺失，该方案无法完成 WP1C，且不得退化为 wall-clock sleep 或运行中未验证的参数写入。

### 3.3 方案 C：继续手工导出 samples 后离线评价

保留现有 PowerShell evaluator，只由人工或其他流程提供 JSON。

优点：改动最小，便于调试 evaluator。

缺点：无法证明 samples 来自当前 builder、当前 commit 和当前 PSCAD run；缺少构建、输出发现、hash、cleanup 和 source-preservation 闭环。因此只能作为辅助诊断入口，不能作为 WP1C 完成路径。

### 3.4 决策

采用方案 A 作为 PSCAD 4.6.2 主路径；方案 B 仅作为 capability 明确存在时的受验证适配器；方案 C 保留为只读 evaluator 和复核工具，不承担 licensed orchestration。

## 4. 目标架构

目标数据流如下：

```text
clean named worktree + current commit
    -> environment/source/asset preflight
    -> live PSCAD 4.6.2 definition inventory
    -> wp1c_dynamic deterministic plan + exact plan hash
    -> isolated staging project and repository-authored companion
    -> component placement, net binding, output declaration
    -> embedded EMTDC event binding verification
    -> save/reload, topology readback, compile
    -> 1.5 s no-fault + inverter AC disturbance simulation
    -> discover and hash OUT/INF parts
    -> normalize channels and derive event/recovery evidence
    -> physical checks + golden declaration
    -> durable current-commit report
    -> cleanup and zero-process verification
```

### 4.1 公共工具边界

在 `plan_lcc_model` 和 `build_lcc_model` 的参数末尾新增可选 `verification_profile`，默认值保持 `full_acceptance`，从而不改变现有调用的行为或位置参数语义。

允许值继续限定为：

- `full_acceptance`；
- `wp1b_smoke`；
- `wp1c_dynamic`。

动态 build 必须使用同一 profile 重新生成 plan，并以 constant-time plan-hash comparison 拒绝 profile、资产、inventory 或时长漂移。

### 4.2 动态能力门

`wp1c_dynamic` 在创建任何文件前必须同时验证：

- live inventory 明确来自 PSCAD 4.6.2；
- exactly one fault timer；
- exactly three single-phase grounded shunt branches，且 A/B/C 相互独立；
- canonical `inverter_ac_bus` 电气连接；
- apply/clear 时刻有限、递增且三相一致；
- fault-active 输出唯一且单位为 `state`；
- 工程内 variable binding 或经过实证的 native scheduler 二者恰有一个被选择；
- 动态时长满足 `event_time + event_duration + recovery_window`。

任一条件不满足时，返回结构化 `LCC_DYNAMIC_EVENT_UNAVAILABLE`，且不得创建或修改 PSCAD 工程。

### 4.3 工程内事件控制

为避免把运行时 Automation 能力当作前提，主路径采用 builder-owned 的显式 control binding：

- `tfault` 参数固定为 `TF=0.8 s`、`DF=0.1 s`、`REP=0`；
- `tfault.Y` 产生 canonical fault state；
- fault state 以一个唯一符号同时绑定三相 breaker 的 `NAME` variable；
- 同一 signal 经 integer-to-real adapter 输出为 `Fault/LCC Fault Active`；
- validator 从保存后的 PSCX/PSLX 证据验证 timer、symbol、三相 consumer 和 output producer；
- compile 后再次回读 Definition identity、物理参数和连接证据。

若 live probe 证明 `breaker1.NAME` 不能使用上述符号绑定，则停止该候选，记录实际 component contract，并单独设计兼容的 Master fault component；不得静默切换为 wall-clock 控制。

### 4.4 End-to-end licensed runner

新增专用 runner，保留现有 evaluator 子命令，并新增完整的 `run` 路径。runner 负责：

1. 验证 clean named checkout、HEAD、分支和 opt-in 环境变量；
2. 验证 workspace 与仓库、官方源和已安装 Master 路径互不包含；
3. 记录 source、asset、Master、compiler 的 before hash；
4. 调用 `wp1c_dynamic` plan/build，不复制受保护 Definition body；
5. 等待 terminal build state，失败时保留 journal 和 quarantine candidate；
6. 发现唯一 OUT/INF 数据集并记录所有 part hash；
7. 从原始通道生成规范化 samples 和派生 dynamic evidence；
8. 调用既有 evaluator 生成 `FAIL` 或 `INCOMPLETE_ANALYSIS`；
9. 记录 after hash、project/companion hash 和 cleanup evidence；
10. 只终止 runner 自己启动并持有的 PSCAD PID；外部 PSCAD 进程存在时在 preflight 阶段停止。

runner 的退出码语义：

- `0`：报告 schema 有效，工程与物理动态门通过；在 WP6 前最终 status 仍可为 `INCOMPLETE_ANALYSIS`；
- `1`：工程、波形、物理检查、报告或 cleanup 失败；
- `2`：preflight/capability 不满足，且没有开始工程写入。

不得使用“只有最终 status 为 PASS 才退出 0”的旧约定，因为 WP1C 在没有 independent golden 时预期且正确的终态是 `INCOMPLETE_ANALYSIS`。报告必须分别记录 `engineering_verdict`、`golden_verdict` 和 `status`，避免掩盖物理失败。

### 4.5 原始波形到动态证据

派生器只接受 runner 直接读取并完成 hash 的当前运行输出。至少使用：

- `Fault/LCC Fault Active`；
- `Main/IDC`；
- `Main/VDC_RECT`；
- `Main/VDC_INV`；
- `Main/GAMMA_INV`；
- acceptance contract 中其余 required channels。

派生规则：

- disturbance：fault-active 在事件窗口内从 0 转为 1，并在清除后返回 0；
- failure indication：事件窗口内存在合同定义的 gamma collapse、DC voltage response 或等价显式指示；不得仅因 fault-active 为 1 就判定换相失败；
- bounded DC response：在事件开始至恢复窗口结束之间计算 `IDC` 有限峰值，并与有来源的合同上限比较；
- recovery：清除后，在 0.5 s 窗口内，required recovery channels 连续满足恢复带宽和最小保持时间；
- domain：所有参与通道必须覆盖相同的事件前、事件中和恢复后时间域，且单位完全匹配。

每个结论都必须记录 selector、单位、窗口、样本数、数值指标和 outcome。缺失通道返回 `FAIL`；时间域不足或独立参考缺失返回 `INCOMPLETE_ANALYSIS`；越界返回 `FAIL`。

## 5. 状态和证据语义

WP1C 报告使用分层结果：

| 字段 | 可用值 | 含义 |
| --- | --- | --- |
| `capability_state` | `built`、`compiled`、`simulated` | 实际完成的生命周期层级 |
| `engineering_verdict` | `PASS`、`FAIL`、`INCOMPLETE_ANALYSIS` | disturbance、failure indication、bounded response、recovery 和 physical checks 的联合结果 |
| `golden_verdict` | `PASS`、`FAIL`、`INCOMPLETE_ANALYSIS` | 仅评价 independent reviewed golden |
| `status` | `PASS`、`FAIL`、`INCOMPLETE_ANALYSIS` | 严格总结果；任一 required failure 为 `FAIL`，缺 golden 为 `INCOMPLETE_ANALYSIS` |

在 WP6 前，预期成功结果为：

```text
capability_state = simulated
engineering_verdict = PASS
golden_verdict = INCOMPLETE_ANALYSIS
status = INCOMPLETE_ANALYSIS
```

这表示“当前提交的工程动态能力和物理门已通过，但最终参考验收尚未完成”，不得简写为 dynamic PASS 或 `accepted`。

## 6. 工作包

### WP1C-0：冻结合同和兼容边界

目标：把公开 profile、时长、报告字段、退出码和 fail-closed 行为写成测试。

主要文件：

- `pscad_mcp/tools/lcc_tools.py`
- `pscad_mcp/hvdc/builders/lcc/service.py`
- `pscad_mcp/hvdc/builders/lcc/models.py`
- `tests/test_lcc_tools.py`
- `tests/test_lcc_builder_service.py`
- `tests/test_lcc_schema.py`

退出条件：旧调用 hash/operations 不变；动态 profile 可通过公开工具规划；不满足 capability 时零文件写入。

### WP1C-1：工程内 EMTDC fault binding

目标：使一个 timer signal 在保存后的工程中可验证地同时驱动三相故障支路，并产生唯一 fault-active 输出。

主要文件：

- `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json`
- `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`
- `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`
- `pscad_mcp/hvdc/builders/lcc/schema.py`
- `pscad_mcp/hvdc/builders/lcc/fault_event.py`
- `pscad_mcp/hvdc/builders/lcc/planner.py`
- `pscad_mcp/hvdc/builders/lcc/executor.py`
- `tests/test_lcc_fault_event.py`
- `tests/test_lcc_fault_shunt_assets.py`
- `tests/test_lcc_planner.py`
- `tests/test_lcc_executor.py`

退出条件：三相控制源唯一、相位独立、事件同步；save/reload/compile fixture 回读一致；未验证 scheduler 不再是 PSCAD 4.6.2 主路径的必需条件。

### WP1C-2：原始输出派生和 end-to-end runner

目标：把 builder 输出直接转换为可审计 dynamic evidence 和 durable report。

主要文件：

- `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py`
- `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py`
- `scripts/run_fixed_lcc_dynamic_acceptance.ps1`
- `tests/test_lcc_dynamic_acceptance.py`
- `tests/test_lcc_dynamic_acceptance_cli.py`
- 新增 `tests/test_lcc_dynamic_evidence.py`

退出条件：runner 不需要人工编造 samples；每个动态布尔量均可追溯到 OUT/INF hash、selector、窗口和指标；任何阶段失败都持久化非 PASS 报告。

### WP1C-3：同一候选提交的离线验证

目标：在 licensed run 前证明兼容性、错误语义和失败持久化。

必跑门：

1. LCC dynamic/fault/planner/executor focused tests；
2. LCC tools/service compatibility tests；
3. WP1B smoke contract tests；
4. fatal Ruff；
5. `git diff --check`；
6. 清除所有 opt-in acceptance 环境变量后的完整 pytest；
7. 确认 source、assets 和既有 licensed report 未被测试修改。

退出条件：全部必跑门实际通过并记录精确计数；不得用历史测试结果替代。

### WP1C-4：同一候选提交的 licensed 双运行

目标：在一个 clean named worktree 和同一 HEAD 上先证明 no-fault 回归，再证明 dynamic engineering evidence。

顺序固定为：

1. environment/live inventory preflight；
2. WP1B 0.1 s no-fault smoke；
3. WP1C 1.5 s inverter AC disturbance；
4. report schema validation 和 SHA-256；
5. source/asset before-after comparison；
6. zero remaining PSCAD process；
7. 独立证据审阅。

WP1B 失败时不得继续 WP1C。WP1C engineering failure 时不得生成 golden 或提升 baseline。

### WP1C-5：证据登记和 WP1D 交接

目标：只登记实际产生并通过 schema/hash/identity 审核的证据。

规则：

- current-commit WP1B report 可恢复 `lcc.fixed_autonomous` 的 `simulated/PASS`，但 explicit exclusions 仍包含 disturbance、independent golden 和 final accepted，直到对应证据存在；
- WP1C 工程门通过且 golden 缺失时，登记 `engineering_verdict=PASS`、总状态 `INCOMPLETE_ANALYSIS`；
- `reports` 必须同时保留 current-commit WP1B 和 WP1C 两条记录；应用 WP1C 后，scope 的 current status 不得继续显示一个可能被误读为动态通过的无条件 `PASS`；
- 如果 program baseline schema 不能同时表达“no-fault PASS”和“dynamic engineering PASS / golden INCOMPLETE”，不得强行覆盖或扩张既有字段语义。保留两份已验证报告，记录 `baseline_scope_granularity_insufficient`，先以独立 schema 变更解决分层状态；
- 基线更新与 licensed run 分离，必须显式执行并审查 diff；
- 不自动 merge、push、发布或安装；
- WP1D 只有在 fixed shared backend、输出读取和 cleanup 不再阻塞时解锁。

## 7. 测试矩阵

| 层级 | 必须证明 | 禁止替代物 |
| --- | --- | --- |
| Schema/unit | profile、event、duration、report、status、退出码严格验证 | 只断言函数被调用 |
| Planner | live inventory gate、零副作用失败、确定性 hash、旧 profile 兼容 | packaged catalog 冒充 live inventory |
| Executor fake | embedded binding、输出发现、失败持久化、cleanup ownership | fake PASS 冒充 licensed run |
| Component fixture | timer、breaker、adapter、output 独立实例化和 compile | XML 标签存在即视为物理可用 |
| Full offline | 全仓无回归，许可用例明确 skip | 继承机器 opt-in 环境后把 licensed failure 混入普通回归 |
| Licensed WP1B | 当前 HEAD 无故障构建/重编译/输出/退出 | 历史 `3a09c8f` 报告 |
| Licensed WP1C | 当前 HEAD disturbance、failure indication、bounded response、recovery | synthetic/manual booleans |
| WP6 | independent reviewed golden 和最终矩阵 | packaged placeholder golden |

## 8. 失败语义和停止规则

以下情况必须 fail closed：

- live definition inventory 缺失、版本不是 4.6.2 或 binding 不唯一；
- timer、三相 shunt、ground、bus、fault-active 输出任一缺失；
- event time、duration、recovery window 或 simulation duration 不一致；
- 工程内 variable binding 不能从保存工程回读；
- native scheduler/provider 未实证却被选为执行模式；
- OUT/INF 缺失、越界、重复、时间戳早于运行或 hash 失败；
- required channel 缺失、单位不符、时间域不足或 selector 歧义；
- source、Master、compiler 或 asset identity 漂移；
- checkout dirty/detached；
- 外部 PSCAD 进程已存在；
- runner 结束后仍存在自己启动的 PSCAD 进程；
- report commit 与 HEAD 不一致；
- packaged placeholder 被标记为 reviewed golden。

所有开始写入后的失败都必须保留：

- stage；
- stable error code；
- sanitized message；
- plan/build/run identity；
- 已完成 operations；
- candidate/quarantine path；
- cleanup attempt 和 remaining process inventory；
- 不含伪造 PASS 字段的 durable report。

## 9. WP1C 完成定义

只有同时满足以下条件，才能称“WP1C 原生动态工程闭环完成”：

1. 公开 MCP 工具可显式、兼容地选择 `wp1c_dynamic`；
2. current live PSCAD inventory capability gate 通过；
3. timer、三相 shunt、bus、ground 和 fault-active output 在保存工程中回读一致；
4. 同一候选提交的 WP1B no-fault smoke 通过；
5. 同一候选提交的 WP1C 工程编译和 1.5 s 仿真完成；
6. 原始输出覆盖事件前、事件中和完整恢复窗口；
7. disturbance、failure indication、bounded DC response、recovery 和 physical checks 均有数值证据并通过；
8. report、project、companion、scenario 和 OUT/INF 均记录 SHA-256；
9. source 和 pre-existing assets 的 before/after hash 不变；
10. report commit、branch、plan hash 和 HEAD 一致；
11. report schema validator 通过；
12. runner 自有 PSCAD 进程清零；
13. 离线完整测试和 static checks 通过；
14. 独立 reviewer 未留下 Critical/Important 未解决项。

在这些条件满足但 WP6 golden 尚未完成时，正确声明只能是：

> fixed LCC WP1C current-commit dynamic engineering evidence completed; final status remains `INCOMPLETE_ANALYSIS` pending independent reviewed golden.

不得声明 `accepted`。

## 10. WP1D 和 WP6 交接

WP1C 完成后，WP1D 可复用已经稳定的：

- live inventory 和 Master binding gate；
- isolated workspace、journal、quarantine 和 cleanup；
- OUT/INF discovery、hash 和 channel normalization；
- event/recovery evidence derivation；
- current-commit report identity。

WP1D 仍必须为至少三组 feasible ratings 生成 rating-specific scenario、project/output hash 和 acceptance result，不得直接复用 fixed-case golden。

WP6 负责：

- 从不共享被测 builder 实现路径的 licensed reference assembly 生成 golden；
- 固定 source/version/compiler/parameter/output/reviewer identity；
- 重新运行 fixed 和 parametric LCC final matrix；
- 只有 physical 与 golden required checks 全部 PASS 后才更新 `accepted`、README 和 release state。

## 11. 交付物

WP1C 完成时应交付：

- approved design 和逐步 implementation plan；
- current-commit source changes 和 focused regression tests；
- 完整离线验证记录；
- current-commit WP1B licensed smoke report；
- current-commit WP1C dynamic report；
- project、companion、scenario、OUT/INF 和 report hashes；
- source-preservation 和 zero-process cleanup evidence；
- independent review 结论；
- 明确的 WP1D handoff；
- 明确保留 WP6 independent golden/final accepted exclusion。

## 12. 执行边界

本文档获批后，下一步才是编写 `docs/superpowers/plans/2026-09-02-lcc-wp1c-native-closure.md`。实施时必须在隔离的 `codex/` worktree 中采用 TDD，逐个 root cause 提交；licensed run、baseline promotion、merge、push 和发布分别保留独立授权与证据门。
