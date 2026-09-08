# 工作 B：MMC 故障证据链补齐 Implementation Plan

> **For agentic workers:** 使用 `executing-plans` 按任务清单执行；开始修改前使用 `using-git-worktrees`，行为变更使用 `test-driven-development`，失败诊断使用 `systematic-debugging`，交付前使用 `verification-before-completion`。本任务交付真实通道与物理判据，不止于离线缺口清单。

**Goal:** 在官方 full-bridge MMC 派生工程中补齐 DC fault 所需的真实测量与输出，使故障施加、负插入电压、闭锁、有界故障电流和清故障后的恢复均可由可追溯波形判定。

**Architecture:** 复用官方模板审计、blank/native 构建路径、现有输出发现/读取和验收结构；仅在任务拥有的副本中增加必要的仪表化。按明确的实例、owner、单位、时间域和输出分片选择信号，严格区分控制命令与物理响应。先用现有模板事件独立验证，再消费工作 A 的正式事件合同完成集成。

**Tech Stack:** Python 3.10+、ElementTree、pytest、PowerShell、PSCAD Automation Library、OUT/INF/INFX 数据。

## 1. 执行依据与当前状态

- 首先读取 [验收与失败处理规则](D:/pscad-mcp/docs/acceptance-criteria.md)，再规划、执行或解释任何验收。
- 阅读 [总路线图 WP4](D:/pscad-mcp/docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md:720) 及 [并发验收记录](D:/pscad-mcp/docs/acceptance/concurrent-acceptance-20260908.md)。按用户最新规则使用独立实例并发，不沿用旧文件的全局单实例假设。
- 配套任务为 [工作 A：严格 EMTDC 定时控制](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-emt-timed-control-work.md)。正在进行的元件映射离线预审不属于本任务。
- 编写时主分支包含 `db65d74`、`a759a46`。执行者必须记录自己的基线和最终 SHA，并确认新建工作树含并发 runner 支持。
- 当前 [template_native.py](D:/pscad-mcp/pscad_mcp/hvdc/builders/mmc/template_native.py) 按通道文本匹配四类信号，并从闭锁信号复位推断恢复。这些行为需要对照 WP4 的通道身份、极性、时间窗和电气恢复要求做回归验证，不能直接继承为充分证据。
- [profiles.py](D:/pscad-mcp/pscad_mcp/hvdc/profiles.py) 的语义角色、[scenarios.py](D:/pscad-mcp/pscad_mcp/hvdc/builders/mmc/scenarios.py) 的场景指标和官方模板实际输出需逐项对应。profile 名称和拓扑声明不能替代真实信号。

## 2. 隔离与文件分工

推荐分支：`codex/mmc-fault-evidence`。推荐工作树：`D:/pscad-mcp/.worktrees/mmc-fault-evidence`。实机证据根目录：`D:/PSCAD-Workspace/mmc-fault-evidence`，每次运行创建唯一子目录。

从含并发修复的当前主分支创建独立工作树；若已存在则检查所属任务后续做。保留用户修改和既有失败证据。

| 文件范围，以本任务工作树为根 | 本任务职责 |
| --- | --- |
| `pscad_mcp/hvdc/builders/mmc/template_audit.py` | 实例与信号来源审计，增加可回读的通道合同 |
| `pscad_mcp/hvdc/builders/mmc/fault_channels.py`，新增 | 故障测量映射与派生工程的输出仪表化，复用已有 XML/元数据 API |
| `pscad_mcp/hvdc/builders/mmc/template_native.py` | 样本身份校验和 `evaluate_template_native_dc_fault` 的严格证据判定 |
| `pscad_mcp/hvdc/builders/mmc/acceptance.py` | 物理判据及可追溯的逐项结果 |
| `pscad_mcp/hvdc/builders/mmc/blank_service.py` | 仪表化接入、完整输出读取、调用验收与失败报告保留 |
| `pscad_mcp/hvdc/builders/mmc/diagnostics.py` | 缺通道、极性不明、时间域错误等诊断 |
| `pscad_mcp/hvdc/profiles.py` | MMC 测量角色与语义校正；定时命令绑定的变化与 A 协调 |
| `tests/test_mmc_template_native.py`、`test_mmc_template_audit.py`、`test_blank_mmc_service.py`、`test_mmc_acceptance.py`、`test_mmc_diagnostics.py`、`test_hvdc_vsc_mmc_profiles.py` | 对应生产行为回归 |
| `tests/test_mmc_fault_channels.py`、`tests/test_mmc_fault_evidence_real.py`，新增 | 仪表化合同与专用 licensed gate |
| `docs/acceptance/mmc-fault-evidence/`，新增 | 设计决定、通道矩阵、检查报告和小型交接文件 |

共享场景执行器、`timing.py`、`mmc/scenarios.py`、`engines/pwm.py` 和 backend 定时接口由 A 修改。B 只读这些文件；如输出 backend 存在可复现缺陷，把最小失败回归和接口要求写入自己的交接记录，由 A 汇总共享 backend 修改。B 可继续通道、判据、派生工程等独立工作。

本任务不重做 Master 映射、不实现 full-bridge AVM companion、不修改 LCC 模型；官方安装文件和用户现有工程只读。模型侧必要修正落实在本任务的派生逻辑与派生副本中。

## 3. 通道与证据合同

以运行前冻结的通道矩阵为准。以下角色是必需项；具体 owner、端口和 selector 必须从审计结果填写，不能猜测。

| 角色 | 来源与判定要求 |
| --- | --- |
| `fault_active` | 来自实际故障作用链，证明计划窗口内投入及切除；区分命令与实际状态 |
| `v_inserted` | 明确桥臂/子模块、方向、参考点与单位；证明故障窗口内真实负插入，不以负命令代替实际电压 |
| `blocking_state` | 明确 0/1 语义、站端及控制来源；`De-blocking` 不能按名称当作 active-high blocking |
| `i_dc_fault` | 实际故障支路电流及方向，单位可追溯到 kA；区别于任意站端 DC 电流 |
| `v_dc` | 明确极对极或极对地、站端和单位，覆盖故障前后窗口 |
| `i_arm` | 明确站端、相别、上下桥臂及维度，覆盖需要检验的桥臂集合 |
| `v_cap` | 区分单电容、子模块与等效桥臂电容电压，不能直接混用尺度 |
| `recovery_enable` 或等价恢复状态 | 证明恢复动作；还必须用 DC 电压、功率、桥臂电流证明实际恢复 |
| `p_active` | 为恢复检查提供有功功率，或使用有明确单位、方向和时间对齐的可审计推导 |
| simulation time | 来自真实输出的 EMTDC 时间列，单位秒、有限、严格递增、覆盖合同窗口 |

每条通道至少记录：`role`、`model_scope`、`instance_path`、`owner_id`、`definition`、`signal_source`、`selector`、`units`、`dimension`、`polarity`、`output_part`、`metadata_file`、`sample_count`、`time_bounds_s` 和相关哈希。静态审计时未知的运行字段必须标为尚未观测，不能填假值。

同一 Definition 被多次实例化时，Definition owner ID 不等于全局唯一运行实例。通道身份必须包含完整层级/实例信息，并与实际 INF/INFX 和输出分片对应。合法的多桥臂向量和来源不明的重复名称分别处理。

B 独占写入 `docs/acceptance/mmc-fault-evidence/channels-handoff.json`，包含 `schema_version=1`、`producer_revision`、原始 `source_hashes`、`channels`、`required_checks`、`instrumented_project_sha256` 和真实运行证据索引。

A 的 `docs/acceptance/emt-timed-control/schedule-handoff.json` 是唯一正式事件交接来源，字段定义见 A 文档第 3 节。消费后记录其文件哈希和 `schedule_sha256`。两任务对原始 Master/project/library 哈希做一致性检查；保留仪表化和事件派生造成的工程哈希变化，不要求不同派生阶段的工程哈希相同。

## 4. 实施清单

### B1. 建立基线并固定通道需求

- [ ] 阅读验收规则、适用 AGENTS.md、A 的文件所有权表，在独立工作树记录基线。
- [ ] 运行第 6 节现有离线回归，保存结果与实际执行命令。
- [ ] 使用 [audit_mmc_template](D:/pscad-mcp/pscad_mcp/hvdc/builders/mmc/template_audit.py:486) 审计官方 project/library，记录原始文件哈希和从 Main 可达的实例链。
- [ ] 对第 3 节每一角色明确：已输出、内部信号可仪表化、缺少物理来源、语义不明确。后两类记录准确缺口，继续查源与实现，不能停在清单交付。
- [ ] 固定物理阈值、恢复窗口、方向、单位和依据。沿用有效的已有合同；合同存在矛盾时定位来源并按授权处理，不能通过更宽阈值制造 PASS。

### B2. 实现派生工程仪表化

- [ ] 为缺通道、重复实例身份、条件端口、源哈希漂移和保存后回读漂移先写失败回归。
- [ ] 在 `fault_channels.py` 实现只作用于派生工程的通道绑定/输出插入，使用结构化 XML 和真实 Master 参数合同。
- [ ] 插入实际 output/PGB 或可审计等价测量链；不能写常数波形、复制控制命令冒充物理信号，或复制受限官方 Definition body 到仓库资产。
- [ ] 保存后重新解析工程和伴随库，核对 owner、信号来源、参数、单位、维度与派生哈希；随后加载、保存并重新审计运行时对应关系。
- [ ] 在 `blank_service.py` 接入仪表化后再编译运行；仅引用已完成写入的输出。

### B3. 实现严格判据与完整数据读取

- [ ] 对下表编写失败回归，再修复对应逻辑。保持已有报告结构的兼容性，不能继续保留会产生虚假 PASS 的旧测试假设。
- [ ] 使用既有输出发现与读取接口收集所有相关 numbered OUT、INF 和 INFX；保留分片来源，校验读取前后文件集合与哈希。
- [ ] 在 `evaluate_template_native_dc_fault` 及相关验收函数中以明确通道合同选择样本，不以第一项匹配或最大活动幅值决定信号身份。
- [ ] 对每个 physical check 输出预期值、观测值、窗口、来源及状态。缺证据保持 `INCOMPLETE_ANALYSIS`，物理不满足为失败，API 边界使用已有兼容错误语义。
- [ ] 保留失败尝试的逐项结果与数据身份；输入、分片集合或元数据漂移时，不把不一致结果作为有效物理证据发布。

| 回归场景 | 必须观察的行为 |
| --- | --- |
| 缺负插入电压；只有 full-bridge 名称 | 不完整，不推断负插入能力 |
| 同名信号来自两个不同站端/实例 | 依合同唯一选择，无法消歧则不完整 |
| `De-blocking` 为低有效；极性未知 | 按有证据的极性转换；未知则拒绝判定 |
| 电流实际为 A，合同为 kA | 仅按明确单位规则转换并记录，不能直接比较数值 |
| 时间域不一致、非有限、重复/倒退、缺恢复窗口 | 不完整或无效证据；不补零、不外推 |
| 负电压只出现在故障窗口之外 | 负插入检查不通过 |
| 闭锁已解除但 DC 电压、功率或桥臂电流未恢复 | 恢复检查不通过 |
| 元数据被改写、新增/缺失分片、陈旧 OUT | 拒绝关联这一组数据，不混入当前运行 |
| half-bridge 数据传入 full-bridge 判据 | 不得产生 intrinsic blocking PASS；保留其适用能力边界 |
| 完整且来源一致的正例 | 相关物理检查均可判定，并与人工独立计算一致 |

### B4. 独立实机闭合

- [ ] 新增专用 licensed test，复用 [进程所有权策略](D:/pscad-mcp/pscad_mcp/acceptance/process_scope.py) 和现有连接/清理生命周期。
- [ ] A 尚未交付时，用 `materialize_template_native_scenario` 的已有模板内嵌事件在自己的副本上开展验证；保存事件绑定与实际 fault-active 波形。该阶段如不具备 A 的通用调度能力，只声明已验证的模板原生场景范围。
- [ ] 顺序完成无故障稳态、DC fault、清故障后的恢复，确保输出时长覆盖所有预先固定的窗口。
- [ ] 从真实 OUT/INF/INFX 验证故障、负插入、闭锁、故障电流上界和恢复；独立重算关键指标，与报告对照。
- [ ] 对可复现的通道、模型派生、控制、单位和报告缺陷持续修复，并复跑受影响的验收。工程编译成功或单次失败报告不是终点。
- [ ] 保存最终提交、原始/派生工程与输出哈希、报告、命令和 owned PID 清理证据，形成 B 的独立交付。

### B5. 与 A 集成

- [ ] 完成 `channels-handoff.json`，将实际可用 selector 和信号极性提供给 A。
- [ ] 读取 A 的最终 `schedule-handoff.json`，检查原始输入身份，绑定 `event_id`、事件窗口、时间容差和调度哈希。
- [ ] 在 A 负责的独立集成分支上复核完整 MMC 场景，B 负责通道身份、物理判据及派生模型修正，A 负责定时/PWM/共享调用层修正。
- [ ] 任一相关代码、模型或合同修改后，重跑受影响的集成验收并保留旧失败与新结果的对应关系。
- [ ] 只记录本次实际通过的 scope；独立 golden 与 WP6 最终 accepted/release 状态保持按其真实证据门管理。

## 5. 并发执行规则

B 与 A 各用自己的 Python 进程、PSCAD 实例、连接、executor 和 workspace；单实例自动化调用串行。新 runner 复用 `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1` 的进程级 opt-in，并保留 `PSCAD_MCP_MMC_ACCEPTANCE` 等原有许可条件。

不能接管、附加到或清理其他任务实例，也不能用全局 PID 差推断实例所有者。运行前确认工作树含并发支持。对他人已完成并冻结的数据可以静态评价，无需整台机器没有 PSCAD；正在写入的报告或 OUT 文件不能作为输入。

代码按第 2 节的唯一文件所有者分工。双方早期可用人工构造的 fixture 验证软件合同，但 fixture 必须明确标记为 synthetic，不能列入 licensed/physical PASS 证据。独立实机阶段不互相等待；正式合同与最终集成按第 3、4 节交接。

## 6. 验证命令

以下命令从 B 工作树运行。

```powershell
git rev-parse HEAD
git status --short --branch
git merge-base --is-ancestor db65d74 HEAD
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_mmc_template_native.py tests/test_mmc_template_audit.py tests/test_blank_mmc_service.py tests/test_mmc_acceptance.py tests/test_output_discovery.py tests/test_hvdc_vsc_mmc_profiles.py -q
```

期望：祖先检查退出 0；现有离线测试通过。记录实际基线失败，后续修改不能掩盖已知缺陷。

实现完成后，保留已有许可 opt-in 再运行专用实机测试：

```powershell
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_mmc_fault_channels.py tests/test_mmc_diagnostics.py -q
git diff --check
$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT = '1'
$env:PSCAD_MCP_WORKSPACE = 'D:/PSCAD-Workspace/mmc-fault-evidence'
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_mmc_fault_evidence_real.py -q -s
```

新增实机测试使用 `PSCAD_MCP_MMC_ACCEPTANCE=1` 作为明确 opt-in，并保留所复用 runner 的其他已有前提。运行前创建 workspace，每次测试写入独立子目录。缺许可条件导致 skip 不算验收完成。交付与集成时执行适用的全仓检查、lint 和代码审查，保存结果。

## 7. 完成条件与失败处理

独立交付要求：所有必需通道有来源与身份；实际工程可重新加载、编译、运行；真实 DC fault 场景的全部适用物理检查通过；单位、窗口、输出分片和哈希一致；本任务实例已清理；报告可由最终代码与保存数据复核。

最终集成交付另要求消费 A 的实际事件合同并复跑受影响场景。若独立交付已通过而集成仍待 A，报告两个状态及确切依赖，不能把待完成集成写成全部完成。

单次 `FAIL` 是诊断输入。分别识别环境争用、实现缺陷、模型/电气失败和不支持的外部能力，保留失败证据，修复可复现的问题并复跑。不得降低阈值、跳过失败检查、用陈旧输出或常数波形换取 PASS。真实外部阻塞必须说明证据、已尝试工作、已完成的独立部分和继续所需的最小前提。

## 8. 可直接发送给执行任务的指令

> 执行 `D:/pscad-mcp/docs/superpowers/plans/2026-09-08-mmc-fault-evidence-work.md`。这是 MMC 故障测量、严格物理判据与实机验收的实际实现，元件映射离线预审由另一个任务负责。读取验收规则，在独立工作树和 PSCAD 实例中先闭合自己的模板原生场景，再与严格 EMTDC 定时任务交接。遵守文件所有权，持续修复本范围内的可复现问题并复跑验收，最终交付代码版本、可追溯通道、真实波形与逐项判据报告。
