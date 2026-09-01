# LCC 与 MMC 完整实现工作纲领

**日期：** 2026-08-30

**状态：** 执行中；WP0、WP1A 与 WP1B 已完成，WP1C 已解锁

**主要读者：** 后续执行任务的 Codex 工程代理

**目标平台：** Licensed PSCAD 4.6.2 Legacy Automation

## 1. 文档目的

本文件是 LCC 与 MMC 从“已有代码和局部实机证据”推进到“自主构建、动态
仿真和故障验收均可正式发布”的总工作纲领。它不替代各工作包的详细
implementation plan，而是规定：

- 当前基线中哪些能力已经被真实证明；
- 哪些结果只来自官方模板适配、离线测试或旧提交；
- WP0-WP6 的执行顺序、输入、产物和解锁条件；
- 每个工作包必须满足的 TDD、回读、编译和 licensed acceptance 门；
- LCC 与 MMC 最终能够标记为 `accepted` 的唯一条件。

后续 Codex 不得把本文件一次性实现为一个大改动。每个工作包必须先形成
独立设计或边界确认，再生成逐步骤 implementation plan，并在独立分支或
工作树内执行。

## 2. 最终目标

项目完成时，PSCAD MCP 必须能够在 PSCAD 4.6.2 中完成以下两类交付，而且
每类交付都必须产生独立证据：

### 2.1 LCC 最终交付

1. 从空白目标工程构建固定 CIGRE 风格单极 12 脉动 LCC 系统；
2. 使用真实 Master Library 元件和真实可加载 companion library；
3. 完成稳态编译与仿真；
4. 施加逆变侧 AC 扰动；
5. 证明 disturbance、commutation-failure indication、bounded DC response
   和 recovery；
6. 固定、blank/native 和参数化路径分别完成验收，不相互替代；
7. 使用独立 reviewed reference run 生成 golden，而不是由被测 builder
   自己生成参考波形。

### 2.2 MMC 最终交付

1. 从空白目标工程构建两端对称单极 full-bridge MMC；
2. detailed PWM 和 average-value model 分别具有真实可运行实现；
3. 完成稳态、功率反转和 DC fault 场景；
4. 证明 fault applied、negative voltage insertion、blocking、bounded fault
   current 和 recovery；
5. full-bridge 与 half-bridge 能力严格分离；
6. full-bridge 可声明 `intrinsic_dc_fault_blocking=true` 的前提是完整动态
   证据通过；
7. half-bridge 始终声明 `intrinsic_dc_fault_blocking=false`，不得复用
   full-bridge verdict；
8. detailed PWM、AVM、blank/native 和参数化路径分别产生项目、输出和
   acceptance report 哈希。

## 3. 非目标

本执行计划不包含：

- PSCAD 5.x licensed acceptance；
- 未经审核的任意用户额定值生成；
- 修改安装目录中的 `master.pslx`；
- 修改官方模板或用户已有工程；
- 用 Python wall-clock 代替 EMTDC 仿真时间；
- 用 synthetic waveform、fake backend 或单元测试结果替代 licensed PASS；
- 把官方样例原有运行结果标记为自主构建结果；
- 在缺少 independent golden 时发布 accepted verdict。

## 4. 当前可信基线

### 4.1 仓库和测试基线

| 项目 | 当前证据 |
| --- | --- |
| 基线提交 | `dadd739e2abc14dcc7de73149da7fd7f0c0ca763` |
| 分支基线 | `main`，相对 `origin/main` 为本地 ahead，未推送 |
| 完整离线测试 | `2113 passed, 42 skipped` |
| 已知测试警告 | Pydantic unresolved forward reference 基线警告 |
| PSCAD 版本 | `4.6.2` |
| Master 源 | `C:\Program Files (x86)\PSCAD46\master.pslx` |
| Master SHA-256 | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |

任何后续工作包开始时都必须重新采集这些值。旧值只用于检测变化，不能自动
成为新提交的验收结论。

### 4.2 LCC 当前状态

| 路径 | 当前能力 | 实机状态 | 发布判断 |
| --- | --- | --- | --- |
| Master Binding Registry | 8 类逻辑 Master 元件完成 live audit、实例化、回读和 compile smoke | PASS | `compile_verified` |
| blank/native LCC | 官方模板只读审计、隔离复制、companion 提取、故障仿真、输出保存 | WP1A 历史 `simulated/PASS`；提交推进后为 `NOT_RUN_ON_CURRENT_COMMIT` | WP1A 完成；未 `accepted` |
| fixed LCC builder | 两组 `g6p200`、标量 AO 控制、初始化、信号接口、完整发布链 | current-commit WP1B `simulated/PASS` | 无故障 smoke 完成；未 `accepted` |
| parametric LCC | 参数推导、模板审计、规划、构建和模式验证存在 | 未发现 licensed PASS 报告 | 未 accepted |

LCC Master smoke 的当前报告位于：

`D:\PSCAD-Workspace\master-binding-acceptance\master-binding-acceptance-20260829-173320-618412\master-binding-acceptance-report.json`

该报告证明：

- 8 类 logical binding 全部 verified；
- 三相 filter 产生 3 个 `cfilter`、3 个 ground 和 3 条 neutral wire；
- component、port 和 converted parameter 完成回读；
- 工程编译成功；
- Master 文件前后 SHA-256 一致；
- PSCAD 退出后无残留进程。

blank/native LCC 的成功 journal 位于：

`D:\PSCAD-Workspace\blank-lcc-native-acceptance2-20260829\.pscad-mcp\lcc-builds\9b2fb1415a6b4f59a306b532c8b6f873\journal.json`

该记录的状态链为：

`validated -> staging_created -> compiled -> simulated -> acceptance_passed -> published`

其动态检查包括：

- disturbance：PASS；
- failure indication：PASS；
- bounded DC response：PASS；
- recovery：PASS；
- observed peak DC current：约 `2.5924 pu`；
- configured current limit：`3.0 pu`。

但是该结果属于官方模板适配路径，且没有证明当前提交上的 fixed builder 和
parametric builder 已通过。固定资产中的
`pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/golden.json` 仍声明 licensed
reference required，不能作为正式 golden。

### 4.3 MMC 当前状态

| 路径 | 当前能力 | 实机状态 | 发布判断 |
| --- | --- | --- | --- |
| blank/native MMC | 官方项目/库审计、拓扑识别、隔离复制、编译、仿真、输出保存 | `compiled -> simulated -> acceptance_incomplete` | 未 accepted |
| parametric detailed PWM | 参数推导、candidate plan、官方模板复制和部分编译产物 | `HVDC_TIMED_CONTROL_UNAVAILABLE` | 仅 planned |
| parametric AVM | planner、candidate loop、repo-authored AVM 契约 | `master:dc_bus` 映射失败 | 仅 planned |
| fixed packaged AVM | 结构、方程、接口、限制和生命周期代码存在 | golden channels 为空 | 未 accepted |

blank/native MMC 的关键 journal 位于：

`D:\PSCAD-Workspace\blank-mmc-native-acceptance-20260829\.pscad-mcp\mmc-builds\b260eaf5c5004b5dab39c9368ed1023c\journal.json`

它证明工程已经真实编译并仿真，产生了多个输出分片，但 acceptance 为
`INCOMPLETE_ANALYSIS`：

- `bounded_fault_current=true`；
- fault current peak 约 `4.8064 kA`；
- 缺少 `negative_voltage_inserted` 通道；
- `fault_applied=false`；
- fault time 无法从证据中确定；
- blocking 和 recovery 无法建立完整证据链。

参数化 MMC 的最新汇总报告位于：

`D:\PSCAD-Workspace\mmc-parametric-acceptance\mmc-parametric-acceptance-20260828T080837223737Z\mmc-parametric-acceptance-report.json`

三组 feasible request 均为 `INCOMPLETE_ANALYSIS`：

- detailed PWM：`HVDC_TIMED_CONTROL_UNAVAILABLE`；
- AVM：`LCC_DEFINITION_MISSING`，缺失 logical `master:dc_bus`；
- capability level 保持 `planned`；
- 没有最终 project hash、output hash 或 scenario verdict。

固定 MMC 的
`pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/golden.json` 没有 reviewed
waveform channels，因此当前 acceptance 只能返回 missing 或
`INCOMPLETE_ANALYSIS`。

## 5. 状态词典和真值规则

后续报告只能使用下列状态：

| 状态 | 含义 |
| --- | --- |
| `inspected` | 源文件和元数据已只读审计 |
| `planned` | immutable plan 和 hash 已生成，未 mutation |
| `built` | 工程和 companion 已创建并通过结构回读 |
| `compiled` | 当前提交的时间戳副本完成 PSCAD compile |
| `simulated` | 当前提交产生可读取的真实 EMTDC 输出 |
| `accepted` | 所有 required physical checks 和 independent golden checks 通过 |
| `INCOMPLETE_ANALYSIS` | 必需证据缺失，不能判定 PASS/FAIL |
| `failed` | 已有证据明确违反契约或运行失败 |

真值规则：

1. 后一状态不能反推前一状态之外的能力；
2. compile PASS 不等于 simulation PASS；
3. simulation PASS 不等于 acceptance PASS；
4. 官方模板 PASS 不等于 autonomous blank build PASS；
5. detailed PWM PASS 不等于 AVM PASS；
6. half-bridge 结果不能支持 full-bridge blocking 声明；
7. 旧提交的 PASS 在源 hash 或代码提交变化后只保留为历史记录；
8. fake-backend、synthetic fixture 和 builder-generated golden 永远不能形成
   licensed PASS。

## 6. 总体技术路线

采用证据门驱动的顺序路线：

`WP0 -> WP1 -> WP2 -> WP3 -> WP4 -> WP5 -> WP6`

其中：

- WP0 固定公共基线；
- WP1 先把 LCC 工程路径收口到 physical acceptance readiness；
- WP2 解决 MMC Master 物理映射；
- WP3 提供严格 EMTDC 定时能力；
- WP4 建立 MMC 故障证据通道；
- WP5 分别收口 detailed PWM 和 AVM；
- WP6 生成 independent golden 并执行完整发布门。

不得并行执行会同时启动 PSCAD 或修改 Legacy backend 的工作包。纯离线文档、
fixture 和数据审计可以并行，但最终集成必须按依赖顺序进行。

## 7. 所有工作包的统一执行契约

### 7.1 Git 与隔离

- 每个 WP 使用独立 `codex/` 分支和 worktree；
- 开始前记录 base SHA；
- 工作树必须干净；
- 不回滚用户已有修改；
- 每个逻辑任务使用小提交；
- 合并前运行全量测试和 code review；
- licensed failure 的证据目录不得删除或覆盖。

### 7.2 TDD

每个行为变更必须遵循：

1. 写最小失败测试；
2. 运行并确认失败原因正确；
3. 写最小生产实现；
4. 运行 focused test；
5. 运行相关跨模块回归；
6. 重构后保持 GREEN；
7. 提交。

配置、manifest 和 acceptance schema 也必须由契约测试保护。

### 7.3 文件不变性

下列文件只允许读取：

- 安装目录中的 `master.pslx`；
- PSCAD 官方 project/library；
- 用户已有 PSCX/PSLX；
- independent golden source。

所有运行只能使用：

- 时间戳副本；
- `PSCAD_MCP_WORKSPACE` 内 staging；
- builder 拥有的 derived project；
- builder 拥有的 companion publication target。

### 7.4 统一验证层

每个 WP 需要依次通过：

1. **离线门**：schema、unit、hash、mapping、error、rollback；
2. **fake-backend 门**：mutation、read-back、stale-plan、containment；
3. **compile 门**：live definition、实例化、save、compile；
4. **simulation 门**：真实 output file 和 EMTDC time；
5. **acceptance 门**：physical checks + independent golden；
6. **publication 门**：final compile smoke、hash、immutable sources。

## 8. WP0：验收基线与证据清单

**完成记录：**
[`2026-08-30-lcc-mmc-wp0-baseline-design.md`](2026-08-30-lcc-mmc-wp0-baseline-design.md)

### 8.1 目标

为后续所有工作包建立唯一、机器可读的 current-truth baseline，使任何 Codex
任务能够判断某项证据是否属于当前提交和当前 PSCAD 安装。

### 8.2 输入

- 当前 `main` SHA；
- `master.pslx`；
- GFortran/Intel compiler inventory；
- 官方 LCC/MMC project/library；
- fixed LCC/MMC packaged assets；
- 当前 acceptance journals/reports；
- `docs/acceptance-status.json` 中已有但作用域不同的 topology 证据。

### 8.3 任务

#### WP0.1 建立 program baseline schema

创建独立于 topology truth manifest 的 LCC/MMC program baseline。建议文件：

- `docs/acceptance/lcc-mmc-program-baseline.json`
- `tests/test_lcc_mmc_program_baseline.py`

字段必须包括：

- schema version；
- git commit；
- backend/version/x64；
- compiler identity；
- Master path/hash；
- official source paths/hashes；
- packaged asset hashes；
- report paths/hashes；
- capability state；
- last-run status；
- accepted scope；
- explicit exclusions。

#### WP0.2 建立报告索引

扫描已知 acceptance workspace，只登记文件，不复制用户工程。报告索引必须区分：

- current commit；
- historical commit；
- commit unknown；
- official template run；
- autonomous build run；
- fixed/parametric/detailed/AVM engine。

#### WP0.3 建立环境 preflight

新增只读 preflight，验证：

- PSCAD 4.6.2 可发现；
- license 可用；
- compiler 可用；
- `mhrc.automation` 可导入；
- Master Library 可读；
- 无外部 PSCAD 进程冲突；
- workspace 可写且不包含源文件；
- output discovery 能处理 legacy numbered parts。

#### WP0.4 固定状态定义

所有 service/report 使用第 5 节词典。删除任何把 `compiled`、`simulated` 和
`accepted` 混用的文案或测试期望。

### 8.4 主要代码区域

- `docs/acceptance-status.json`
- `pscad_mcp/core/capabilities.py`
- `pscad_mcp/hvdc/builders/lcc/journal.py`
- `pscad_mcp/hvdc/builders/mmc/journal.py`
- `tests/test_acceptance_status_manifest.py`
- 新增 program baseline validator

### 8.5 离线验收

- 缺 commit/hash/scope 的 baseline 被拒绝；
- historical report 不会更新 current status；
- LCC PASS 不会更新 MMC；
- native PASS 不会更新 autonomous；
- 相同 run ID 不能重复登记不同 hash；
- JSON 可重复序列化且 hash 稳定。

### 8.6 licensed 验收

运行 preflight 并生成只读环境快照。不得创建 LCC/MMC 项目。

### 8.7 交付物

- program baseline schema 和 validator；
- current evidence inventory；
- 环境 preflight report；
- WP1-WP6 共享的 run metadata helper。

### 8.8 解锁条件

只有 current commit、Master、官方模板、compiler 和现有报告都完成 hash
登记后，WP1 才能开始。

本分支已满足上述条件。最终只读 licensed preflight 在 commit
`5cbe907dfe08820cbf4f511162de0f98a369052f` 上 PASS，报告 SHA-256 为
`fe77de2364573d6d2bd6e701a038fe12191b2d5961fdaa1dde80e2bf48274d7f`；
合并 WP0 分支后允许开始 WP1，不能提前继承任何 LCC historical PASS。

## 9. WP1：LCC 工程路径收口

### 9.1 目标

使 LCC 的 native、fixed autonomous 和 parametric 三条路径在当前提交上分别
完成真实构建、仿真和 physical acceptance readiness。independent golden 的
建立、正式 golden comparison 和最终 `accepted` 状态统一由 WP6 完成。

### 9.2 WP1A：当前提交的 blank/native LCC 重验

**完成状态：** 已完成。完成记录见
[`2026-08-30-lcc-wp1a-native-acceptance-completion.md`](2026-08-30-lcc-wp1a-native-acceptance-completion.md)。

任务：

1. 使用当前提交重新审计官方 LCC 模板；
2. 通过 `MasterBindingRegistry` 审计保留的所有 Master 引用；
3. 创建全新时间戳 workspace；
4. materialize derived project 和 extracted companion；
5. 编译、仿真、执行 inverter AC disturbance；
6. 校验 fault-active、DC current、gamma 或 DC voltage、recovery；
7. 记录 source-before/source-after；
8. 生成 current-commit acceptance report；
9. 更新 program baseline，仅更新 `lcc.blank_native` scope。

主要文件：

- `pscad_mcp/hvdc/builders/lcc/native_template.py`
- `pscad_mcp/hvdc/builders/lcc/blank_service.py`
- `tests/test_blank_lcc_service.py`
- 新增 current-commit licensed runner/report contract

退出条件：

- state 为 `published`；
- 四项 commutation checks 为 true；
- source hash 不变；
- current commit 与 report 一致；
- 无 PSCAD 残留进程。

### 9.3 WP1B：fixed autonomous companion 物理化

**完成状态：** 已在提交 `3a09c8f` 上完成。授权报告
`fixed-lcc-20260901-080458-594` 验证六个独立 Definition fixture、空白工程完整
拓扑、final 重编译和 0.1 s 无故障 smoke；基线能力为 `simulated/PASS`。
该证据不替代 WP1C disturbance/commutation/recovery 或 WP6 independent golden。

当前 `library/cigre_lcc_v1.pslx` 是 repository-authored 结构契约，包含桥、阀
和控制的描述，但不能仅凭结构标签宣称是完整 PSCAD 物理模型。

任务：

1. 审计 companion 的 PSCAD 4.6.2 可加载性；
2. 明确每个 converter-specific definition 的物理方程和内部拓扑；
3. 为 12-pulse bridge 实现真实 thyristor、snubber、两组六脉动桥和 DC series
   path；
4. 实现 rectifier current control 与 inverter extinction-angle control；
5. 定义真实 page ports、parameters、conditional ports 和 output signals；
6. 生成 repository-authored、可加载、可实例化的 PSCAD library；
7. 不复制受限官方 Definition body；
8. 通过独立 component compile fixtures；
9. 在 fixed builder 中替换结构型 companion；
10. 完成从空白工程的全拓扑 compile smoke。

主要文件：

- `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx`
- `pscad_mcp/hvdc/builders/lcc/validator.py`
- `pscad_mcp/hvdc/builders/lcc/executor.py`
- `pscad_mcp/hvdc/builders/lcc/project_graph.py`
- `tests/test_lcc_asset_audit.py`
- `tests/test_lcc_executor.py`
- 新增 companion component licensed smoke

强制验证：

- library 可由 PSCAD 加载；
- 每个 definition 可独立实例化；
- bridge 含 12 个可验证 valve 实例；
- 两个 `g6p200` 采用 FP=0/View=1 标量 AO，合计 12 个有效阀；
- ACY/ACD 相端和 DC polarity 完成回读；
- control 输出真实连接到 gate 输入；
- save/reload 后 definition identity 不漂移。

### 9.4 WP1C：fixed LCC 动态验收

任务：

1. 连接所有 Master 和 companion 元件；
2. 验证 source neutral、transformer grounding、filter neutral 和 DC return；
3. 建立稳态初始化；
4. 运行无故障稳态；
5. 运行 inverter AC disturbance；
6. 读取 required output channels；
7. 执行 physical checks；
8. 在 WP6 golden 可用前保持 `INCOMPLETE_ANALYSIS`；
9. WP6 后重新运行并允许 accepted。

### 9.5 WP1D：parametric LCC licensed 工程门

任务：

1. 选择经审计的可参数化 template；
2. 验证每个 engineering parameter 到物理 component parameter 的映射；
3. 对额定电压、功率、变压器、平波电抗和线路参数执行 unit-aware derivation；
4. 验证 feasible/infeasible request 分类；
5. 运行至少三组 feasible ratings；
6. 对每组生成独立 scenario source、project hash 和 output hash；
7. 验证 operating-mode schedule；
8. 禁止使用 fixed-case golden 评价不同额定值，除非 contract 明确允许归一化。

主要文件：

- `pscad_mcp/hvdc/builders/lcc/derivation.py`
- `pscad_mcp/hvdc/builders/lcc/template_audit.py`
- `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- `pscad_mcp/hvdc/builders/lcc/parametric_executor.py`
- `tests/test_lcc_derivation.py`
- `tests/test_lcc_parametric_service.py`
- 新增 parametric licensed acceptance runner

### 9.6 WP1 解锁 WP2 的条件

- blank/native current-commit PASS；
- fixed companion 可加载和 compile；
- fixed autonomous 至少达到 `simulated`；
- parametric LCC 至少完成一个 current-commit compiled/simulated run；
- LCC 的 shared backend 改动已稳定，不再阻塞 MMC registry 工作。

LCC 最终 `accepted` 可以等待 WP6 independent golden，但上述工程能力必须先完成。

## 10. WP2：MMC Master Binding Registry

### 10.1 目标

像 LCC 一样，为 fixed AVM、blank/native 和 parametric MMC 使用的每个逻辑
Master 引用建立真实、版本化、fail-closed 的物理绑定。

### 10.2 已知首要问题

最新 AVM 实机报告因 logical `master:dc_bus` 在 `master.pslx` 中不存在而失败。
该名称不能通过相似字符串或 catalog metadata 自动推断。必须确定其物理意义：

- 单一 DC node；
- 两端导体；
- bus/short/nodelabel 组合；
- 需要 shape adapter 的复合结构；
- 或应由 companion definition 提供。

只有实物语义审计后才能选择。

### 10.3 任务

#### WP2.1 生成逻辑引用全集

扫描：

- fixed MMC blueprint/catalog；
- blank MMC recipe；
- detailed PWM adapter；
- AVM engine；
- scenario/control insertion；
- companion definitions 的内部 Master 引用。

输出去重的 logical reference inventory，记录消费者和所需端口/参数。

#### WP2.2 审计安装的 Master Library

对每个候选 physical definition 记录：

- description；
- exact definition count；
- conditional port occurrences；
- electrical/data kind；
- dimension；
- parameter type/unit/range/choices/default；
- PSCAD version；
- Master SHA-256。

#### WP2.3 建立 MMC registry

建议新增：

- `pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/master-bindings-pscad-4.6.2.json`
- `tests/test_mmc_master_binding_registry.py`
- `tests/test_mmc_master_binding_real_acceptance.py`

registry 必须复用 `pscad_mcp/core/master_bindings.py` 的 strict parser、audit、
transform、source gate、read-back 和 composite lifecycle，不得复制一套 MMC
专用实现。

#### WP2.4 修复 planner 与 runtime

- MMC plan 记录 registry file hash、canonical registry hash 和 live Master hash；
- 每个 Master operation 记录 physical definition、physical parameters 和 ports；
- compile 前、publish 前和 final compile 后重新检查 source；
- read-back drift 阻止 publication；
- composite adapter 支持 rollback、delete、disconnect 和 unload cleanup。

### 10.4 主要文件

- `pscad_mcp/core/master_bindings.py`
- `pscad_mcp/core/backend/legacy.py`
- `pscad_mcp/core/service.py`
- `pscad_mcp/hvdc/builders/mmc/planner.py`
- `pscad_mcp/hvdc/builders/mmc/executor.py`
- `pscad_mcp/hvdc/builders/mmc/engines/avm.py`
- `pscad_mcp/hvdc/builders/mmc/blank_service.py`
- MMC asset manifest/catalog

### 10.5 失败语义

继续使用：

- `MASTER_BINDING_MISSING`
- `MASTER_BINDING_AMBIGUOUS`
- `MASTER_PORT_MISMATCH`
- `MASTER_PARAMETER_MISMATCH`
- `MASTER_TRANSFORM_UNSUPPORTED`
- `MASTER_SOURCE_CHANGED`
- `MASTER_READBACK_FAILED`
- `MASTER_COMPILE_FAILED`

不得继续返回误导性的 LCC-specific operation 或 error details；MMC inventory
消费者需要使用中性的 Master audit boundary。

### 10.6 验收

离线：

- unknown fields、duplicate names、lookup ambiguity、unit/range、wrong port、
  stale source 和 rollback 测试；
- 所有 fixed/blank/parametric MMC logical references 必须被 registry 覆盖。

实机：

- audit 全集；
- 每个 direct binding 独立实例化；
- 每个 composite binding 展开并验证成员；
- physical definition/parameter/port 回读；
- 一个包含全部 MMC Master binding 的 compile smoke；
- Master 前后不变；
- 无残留 PSCAD 进程。

### 10.7 解锁条件

`master:dc_bus` 和所有其他 logical refs 不再产生 missing/ambiguous；AVM engine
必须能够越过 inventory/placement 阶段进入 compile 或后续明确失败阶段。

## 11. WP3：严格 EMTDC 定时控制

### 11.1 目标

提供可公开调用、可计划、可回读且基于 EMTDC time 的事件能力，解决
`HVDC_TIMED_CONTROL_UNAVAILABLE`。

### 11.2 可接受实现方式

按优先级选择：

1. PSCAD Automation Library 原生 simulation clock/schedule API；
2. 在 derived copy 中使用 PSCAD `time-sig`、`tfault`、`var_switch`、data
   labels 和控制逻辑形成嵌入式 EMTDC schedule；
3. 使用经审计 companion timing component；
4. 若三者均不可用，fail closed。

Python `sleep()`、提交命令的 wall-clock timestamp 和不确定 polling 不能定义
故障时刻。

### 11.3 公共契约

建议抽象：

- event name；
- EMTDC start time；
- duration/removal time；
- target component/parameter；
- before/active/after values；
- units；
- schedule source；
- read-back evidence；
- source hash；
- event channel selector。

计划必须在 mutation 前生成 exact schedule hash。

### 11.4 任务

1. 审计 Legacy 4.6.2 API 和官方模板内嵌控制；
2. 建立 capability probe；
3. 定义 vendor-neutral timed event protocol；
4. 为 native API 和 embedded EMTDC control 分别实现 adapter；
5. 在 derived copy 中插入/配置事件；
6. 保存并重新审计 owner ID 和 parameter；
7. 输出 fault-active/power-reversal-active channel；
8. 在 run 前验证 schedule；
9. 在输出中验证事件发生在允许时间误差内；
10. shutdown/cancel 时停止 simulation 并保留证据。

### 11.5 主要文件

- `pscad_mcp/hvdc/scenarios.py`
- `pscad_mcp/hvdc/builders/mmc/scenarios.py`
- `pscad_mcp/hvdc/builders/mmc/template_native.py`
- `pscad_mcp/core/backend/legacy.py`
- `pscad_mcp/core/backend/run_control.py`
- `tests/test_hvdc_scenario_strict.py`
- `tests/test_mmc_scenarios.py`
- `tests/test_mmc_template_native.py`
- 新增 licensed timed-control acceptance

### 11.6 TDD 重点

- 缺 time basis 时计划失败；
- wall-clock capability 不能冒充 EMTDC；
- event time/duration 非有限值被拒绝；
- duplicate owner/parameter 被拒绝；
- plan hash 变化使 build stale；
- embedded schedule source 变化使 build stale；
- event channel 缺失返回 `INCOMPLETE_ANALYSIS`；
- cancellation 必须调用 stop 并释放 workspace lease。

### 11.7 licensed gate

使用最小时间事件 fixture：

- 在指定 EMTDC time 从 0 切到 1，再恢复 0；
- 输出 event-active 通道；
- measured event time 在明确容差内；
- source/project 前后 hash 符合 contract；
- current commit report PASS。

### 11.8 解锁条件

detailed PWM candidate 不再因 `HVDC_TIMED_CONTROL_UNAVAILABLE` 停止，并能
生成至少一个具有 event-active evidence 的真实输出。

## 12. WP4：MMC 故障测量与证据链

### 12.1 目标

使 full-bridge MMC DC fault acceptance 所需的每项事实都来自真实输出，而不是
拓扑名称或能力声明。

### 12.2 Required channels

至少包括：

- `fault_active`；
- `v_inserted` 或每臂可证明的 inserted-voltage channel；
- `blocking_state`；
- `i_dc_fault`；
- `v_dc`；
- `i_arm`；
- `v_cap`；
- `recovery_enable` 或可证明恢复状态的 channel；
- simulation time domain。

每个 channel 记录：

- path；
- units；
- dimension；
- owner ID；
- component definition；
- signal source；
- output part；
- `.inf` metadata；
- sample count；
- time bounds；
- source hash。

### 12.3 任务

1. 审计官方 full-bridge 模板可用内部信号；
2. 建立 signal-to-output mapping；
3. 在 derived copy 中添加真实 output/graph/PGB 元件；
4. 验证 output owner ID 唯一；
5. 保存、reload 并重新审计；
6. 运行故障场景；
7. 发现所有 numbered output parts 和 `.inf`；
8. 合并/选择通道时保留 source part；
9. 验证 fault window 内负插入电压；
10. 验证 blocking state；
11. 验证 fault current 上界；
12. 验证清故障后的恢复；
13. 缺任一 required channel 时返回 `MMC_ACCEPTANCE_INCOMPLETE`。

### 12.4 主要文件

- `pscad_mcp/hvdc/builders/mmc/template_audit.py`
- `pscad_mcp/hvdc/builders/mmc/template_native.py`
- `pscad_mcp/hvdc/builders/mmc/blank_service.py`
- `pscad_mcp/hvdc/builders/mmc/acceptance.py`
- `pscad_mcp/hvdc/builders/mmc/diagnostics.py`
- output discovery/readback backend
- `tests/test_blank_mmc_service.py`
- `tests/test_mmc_acceptance.py`
- `tests/test_output_discovery.py`

### 12.5 验收判断

full-bridge PASS 必须同时满足：

- fault-active 在计划窗口内出现；
- `v_inserted` 在故障窗口达到 contract 规定的负值；
- blocking state 被真实观测；
- fault current peak 不超过上界；
- fault removal 后 blocking 解除；
- DC voltage/power/arm current 恢复到 contract 窗口；
- 所有 required channels 有正确 units/time domain。

### 12.6 解锁条件

blank/native full-bridge MMC 在 current commit 上完成 `compiled`、`simulated`
并得到无 missing channels 的 physical acceptance result。golden 可以在 WP6
加入，但 physical checks 必须先全部可判定。

## 13. WP5：MMC 双引擎和自主构建收口

### 13.1 目标

分别完成 detailed PWM、full-bridge AVM 和 half-bridge AVM 的物理实现与构建
生命周期。任何一个引擎失败都必须保留独立状态，不污染其他引擎。

### 13.2 WP5A：detailed PWM

1. 使用官方 template/library 的只读 hash；
2. 在 candidate workspace 中生成隔离副本；
3. 绑定 WP3 schedule；
4. 绑定 WP4 output channels；
5. compile；
6. steady-state run；
7. power reversal run；
8. DC fault run；
9. physical acceptance；
10. publication 和 final compile smoke；
11. current commit report。

### 13.3 WP5B：full-bridge AVM

当前 packaged AVM 描述的是 half-bridge diode-equivalent blocked path，不能直接
承担 full-bridge intrinsic blocking 目标。

任务：

1. 新增明确的 full-bridge arm/submodule physical definition；
2. 定义正、零、负 inserted-voltage 能力；
3. 定义 blocked state；
4. 实现 energy state 和 losses；
5. 实现 six-arm station 和 controls；
6. 使用 WP2 Master bindings；
7. 生成真实 PSCAD 4.6.2 companion library；
8. component-level compile；
9. station-level compile；
10. two-terminal build；
11. steady/reversal/fault simulation；
12. 与 detailed PWM 在适用的低频/平均量通道比较。

### 13.4 WP5C：half-bridge AVM

保留当前 diode-equivalent 限制并使其物理可运行。验收必须证明：

- `intrinsic_dc_fault_blocking=false`；
- 不会产生 full-bridge negative insertion verdict；
- fault current path 与声明一致；
- steady-state 和 power reversal 可以独立评价；
- 缺 blocking 能力是 expected limitation，不是伪 PASS。

### 13.5 WP5D：candidate loop 和失败分类

candidate loop 只允许对明确可调整参数进行 bounded adjustment。以下错误禁止
自动调参继续：

- source/registry hash drift；
- missing definition；
- missing required channel；
- timed-control capability missing；
- containment failure；
- compiler unavailable；
- unknown failure signature。

### 13.6 主要文件

- `pscad_mcp/hvdc/builders/mmc/engines/pwm.py`
- `pscad_mcp/hvdc/builders/mmc/engines/avm.py`
- `pscad_mcp/hvdc/builders/mmc/parametric_planner.py`
- `pscad_mcp/hvdc/builders/mmc/parametric_service.py`
- `pscad_mcp/hvdc/builders/mmc/executor.py`
- `pscad_mcp/hvdc/builders/mmc/adjustment.py`
- fixed MMC assets and companion library
- `tests/test_mmc_pwm_engine.py`
- `tests/test_mmc_avm_engine.py`
- `tests/test_mmc_parametric_service.py`
- `tests/test_mmc_parametric_real_acceptance.py`

### 13.7 解锁条件

- detailed PWM 至少一个 full-bridge case 完成 physical PASS；
- full-bridge AVM 至少一个 case 完成 physical PASS；
- half-bridge AVM 完成适用 physical checks 并明确不支持 intrinsic blocking；
- 三个路径分别有 project/output/source hash；
- 不再出现 `master:dc_bus` 和 timed-control blockers。

## 14. WP6：Independent Golden、完整验收和发布

### 14.1 目标

在工程能力已经通过 physical checks 后，建立独立 reviewed golden，并执行最终
release acceptance。

### 14.2 Golden 来源规则

golden 必须满足：

- 不是被测 builder 在同一运行中生成；
- 来源工程、版本、编译器和参数可追溯；
- source project/library hash 固定；
- output file/hash 固定；
- channel selector 和 units 固定；
- review ID、reviewer、日期和范围固定；
- 任何重新生成都会产生新 identity/hash；
- 不允许手工复制常数数组冒充波形。

可接受来源：

1. 独立手工/官方 reference project 的 licensed run；
2. 经过独立审阅的外部参考输出；
3. 与被测 builder 不共享实现路径的 reference assembly。

### 14.3 LCC 最终矩阵

| 路径 | Steady | Fault | Physical | Golden | Publish |
| --- | --- | --- | --- | --- | --- |
| blank/native | required | required | required | required | required |
| fixed autonomous | required | required | required | required | required |
| parametric case A | required | required | required | rating-specific | required |
| parametric case B | required | required | required | rating-specific | required |
| parametric case C | required | required | required | rating-specific | required |

### 14.4 MMC 最终矩阵

| 路径 | Steady | Reversal | DC Fault | Physical | Golden | Publish |
| --- | --- | --- | --- | --- | --- | --- |
| blank/native full bridge | required | required | required | required | required | required |
| detailed PWM full bridge | required | required | required | required | required | required |
| AVM full bridge | required | required | required | required | required | required |
| AVM half bridge | required | required | limitation check | required | required | required |

### 14.5 Acceptance report 必需字段

- schema version；
- commit；
- branch/base；
- backend/version/x64；
- compiler identity；
- request；
- plan hash；
- source paths/hashes before/after；
- asset hashes before/after；
- project path/hash；
- companion path/hash；
- scenario source path/hash；
- output files/hashes；
- channel evidence；
- physical checks；
- golden checks；
- limitations；
- terminal state；
- cleanup/process evidence；
- verdict。

### 14.6 Publication 规则

只有同时满足以下条件才能写入 accepted status：

1. 所有 required cases 为 PASS；
2. physical checks 为 PASS；
3. golden checks 为 PASS；
4. final project compile smoke 为 PASS；
5. sources 和 pre-existing workspace 不变；
6. report 与当前 commit 一致；
7. report schema validator PASS；
8. 无 PSCAD 残留进程；
9. code review 无 Critical/Important 未解决项；
10. 完整测试套件 PASS。

### 14.7 状态更新

WP6 结束时才允许：

- 更新 README 中的 acceptance 声明；
- 更新 program baseline current status；
- 将 fixed LCC/MMC golden source 标记为 accepted reviewed reference；
- 发布 release note；
- 对外描述 autonomous LCC/MMC builder 为 accepted。

## 15. 错误和停止规则

### 15.1 通用停止条件

Codex 遇到以下情况必须停止当前工作包并保留证据：

- 连续三次相同 licensed blocker 且无新的可验证进展；
- source hash 改变；
- 用户已有文件或外部进程产生冲突；
- 定义/端口/参数无法确定；
- compiler/license 不可用；
- required channel 无法从真实工程获得；
- acceptance contract 内部矛盾；
- candidate adjustment 超出批准范围。

### 15.2 禁止静默降级

禁止：

- 删除无法映射的参数后继续；
- 将 unsupported component 替换为同名近似元件；
- 将 missing channel 记为 0；
- 将 unavailable capability 记为 false 后继续 PASS；
- 用 fixed value 代替未读回的 parameter；
- 把 compile-only 报告标记为 accepted；
- 把 half-bridge fault verdict 用于 full-bridge。

## 16. 测试矩阵

| 层级 | LCC | MMC | 每个 WP 是否必需 |
| --- | --- | --- | --- |
| Schema/parser | catalog、registry、plan、report | catalog、registry、plan、report | 是 |
| Transform/unit | transformer、filter、reactor、line | DC bus、line、transformer、measurements | 是 |
| Fake backend | placement、wire、rollback、publish | candidate、schedule、output、rollback | 是 |
| Static XML audit | Master、companion、project | Master、template、library、project | 是 |
| Component compile | Master+LCC companion | Master+PWM/AVM companion | 相关 WP 必需 |
| Full compile | fixed/native/parametric | blank/PWM/AVM | 是 |
| Simulation | steady + fault | steady + reversal + fault | WP1/WP5/WP6 |
| Physical acceptance | commutation/recovery | blocking/current/recovery | 是 |
| Golden acceptance | independent LCC | independent PWM/AVM | WP6 |
| Source immutability | before/after hashes | before/after hashes | 是 |
| Cleanup | process/workspace | process/workspace | 是 |

## 17. Codex 工作包执行协议

每个 WP 的 Codex 任务必须执行以下流程：

1. 阅读本文件和该 WP 依赖的既有 spec；
2. 读取适用 skill；
3. 创建独立 worktree；
4. 运行并记录 baseline tests；
5. 对该 WP 进行独立 brainstorming/spec review；
6. 保存 `docs/superpowers/specs/` 子规范；
7. 用户批准子规范；
8. 用 writing-plans 生成 `docs/superpowers/plans/` 实施计划；
9. 按 TDD 执行；
10. 每个自然任务提交；
11. focused tests；
12. full tests；
13. targeted lint 和 `git diff --check`；
14. code review；
15. licensed gate；
16. 复核 report；
17. 合并或保留分支由用户决定；
18. 更新 program baseline，但只更新该 WP 拥有的 scope。

Codex 不得在一个 turn 中同时实现两个 licensed 工作包，也不得在未获得用户
批准时扩大 scope。

## 18. 推荐子规范与计划文件

后续建议依次创建：

1. `docs/superpowers/specs/2026-08-30-lcc-mmc-wp0-baseline-design.md`
2. `docs/superpowers/specs/2026-08-30-lcc-wp1-completion-design.md`
3. `docs/superpowers/specs/2026-08-30-mmc-master-binding-design.md`
4. `docs/superpowers/specs/2026-08-30-emt-time-control-design.md`
5. `docs/superpowers/specs/2026-08-30-mmc-fault-evidence-design.md`
6. `docs/superpowers/specs/2026-08-30-mmc-dual-engine-completion-design.md`
7. `docs/superpowers/specs/2026-08-30-lcc-mmc-golden-release-design.md`

日期可按实际开始日调整；topic identity 和执行顺序保持不变。

## 19. 风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| PSCAD 4.6 API 无原生 timed schedule | detailed PWM 场景阻塞 | 使用 derived copy 内嵌 EMTDC controls，仍需事件通道证明 |
| 官方 MMC 模板无直接 `V_inserted` output | blocking 无法判定 | 审计内部信号并在副本中添加 output component |
| `master:dc_bus` 无同名物理定义 | AVM placement 阻塞 | 语义审计后 direct/composite/companion 三选一，禁止猜测 |
| LCC/MMC companion 目前偏结构契约 | autonomous build 不能运行 | 逐 definition 实现真实 PSCAD 物理模型并做 component compile |
| independent golden 不可获得 | 最终 acceptance 阻塞 | 提前确定 reference assembly 和 review owner，physical checks 先行 |
| detailed PWM 仿真成本高 | licensed 迭代慢 | 使用最小 canonical submodule count 做 gate，保留额定配置 |
| output parts 多且通道分散 | 误选波形 | 保存 `.inf`、owner、part 和 selector evidence |
| Legacy PSCAD 单实例限制 | 并行冲突 | licensed WP 串行执行，启动前检测外部进程 |
| 旧 PASS 被误认为当前 PASS | 错误发布 | report 强制 commit/source hash，program baseline 区分历史状态 |

## 20. 里程碑

| 里程碑 | 达成条件 |
| --- | --- |
| M0 Baseline Ready | WP0 全部完成 |
| M1 LCC Engineering Ready | native current PASS，fixed/parametric 至少 simulated，companion 可加载 |
| M2 MMC Components Ready | WP2 compile smoke PASS |
| M3 MMC Scenario Ready | WP3 timed event PASS |
| M4 MMC Evidence Ready | WP4 无 missing physical channels |
| M5 MMC Engineering Ready | PWM/full-bridge AVM/half-bridge AVM 分别完成适用 physical PASS |
| M6 Release Accepted | WP6 全矩阵 PASS，状态清单更新 |

## 21. 整体完成定义

本工作纲领只有在以下所有条件同时满足时才完成：

- WP0-WP6 均满足退出条件；
- LCC blank/native、fixed autonomous、parametric 分别有 current-commit
  licensed PASS；
- MMC blank/native full bridge、detailed PWM、full-bridge AVM 分别有
  current-commit licensed PASS；
- half-bridge AVM 有独立适用 verdict，且不声明 intrinsic blocking；
- 所有 Master/companion references 有 live definition evidence；
- strict EMTDC schedule 被真实输出证明；
- required fault channels 无缺失；
- independent golden 已审核；
- full test suite、lint、code review 和 final compile smoke 通过；
- 所有源文件和既有 workspace hash 不变；
- acceptance reports 与 current commit 对应；
- 最终发布状态只覆盖实际通过的 scope。

## 22. 下一步

下一步执行 WP1C fixed LCC 动态验收：先用真实 PSCAD 导出样本运行
`run_fixed_lcc_dynamic_acceptance.ps1`，验证 inverter AC disturbance、换相失败指示、
有界 DC 响应和恢复窗口。当前 fixed companion 尚未声明 fault/event 输入时，
runner 必须持久化 `INCOMPLETE_ANALYSIS` 或 `FAIL`，不得把 WP1B 无故障 smoke
提升为动态 PASS。独立 golden 和最终 `accepted` 仍由 WP6 负责；WP1C 完成后再进入
WP1D 参数化 LCC。
