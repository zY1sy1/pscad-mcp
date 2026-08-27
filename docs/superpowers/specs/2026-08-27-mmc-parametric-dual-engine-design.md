# MMC 参数化双引擎能力设计

## 状态

本设计于 2026-08-27 经用户确认。它定义 PSCAD 4.6.2 下 MMC 的读取、参数化建模、仿真建议和有界自动调整能力，同时支持详细 PWM 与平均值模型。实现和实机验收必须继续区分；未经许可版 PSCAD 完整验收的能力不得描述为已经接受。

## 背景与现有证据

主分支当前具备 MMC 通用只读 profile，可识别部分 MMC 名称并映射桥臂电流、等效子模块电容电压和环流测量，但没有 MMC 专用建模工具。独立分支 `codex/mmc-autonomous-builder` 在提交 `8872a96f72c039ebca1925b8e6a6cfa8763e7d19` 上实现了固定 640 kV、约 1000 MW 的 Stage A 平均值模型规划、构建、状态和验证基础，尚未并入主分支，也没有参数化设计、仿真建议或自动调整能力。

本机 PSCAD 4.6.2 安装包含一个可作为详细模型证据的官方示例：

- 工程：`C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\H_MMC_Mono_DC.pscx`
- 工程 SHA-256：`1900BE93877400FBA228B1808A5310980D801B0260D7DF998DF6C5A2F6A035DD`
- 依赖库：`C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\intermediate.pslx`
- 依赖库 SHA-256：`08466778704E547D7D9D80AF99A48C09292DD3A51056AC26216C3913D5CC3A1B`

该示例是 PSCAD 4.6.2 `ModelsInProgress` 中的两端半桥 PWM MMC。读取证据包括两个 `VSCConverter`、两个 `MMC_Hb_PWM`、显式半桥单元、电容、载波、触发、环流抑制和保护相关组件。名义参数包含 640 kV 直流电压、1000 MVA 容量和 1650 Hz 开关频率。

该示例不能直接作为可发布模板：

- `startup_filename` 指向作者机器上的 `E:\PSCADfiles\MMC\MMCMono2TCCSC.if9\runtime.snp`；
- 线路数据库指向 `C:\home\user\pscad\lineconstants\database\...`；
- 线路常数文件指向 `C:\Temp\my_constants_file.tlo`；
- 目录名称明确标注 `ModelsInProgress`，不能据此宣称模型已经通过工程验收；
- 官方工程和库的再分发权限不由本仓库授予，因此不得复制进包、测试夹具或仓库资产。

当前通用扫描器对该工程给出 `family=mmc`，但把 `Mono DC` 误判为 `bipolar`，且因未理解 PSCAD 顶点式 Wire 表示而报告零条连接。专用读取能力必须先解决这些证据缺口。

## 目标

1. 结构化读取 PSCAD 4.6.2 MMC PSCX/PSLX，识别模型精度、两端站、极性、桥臂、子模块、控制器、保护、线路、测点和参数绑定。
2. 用同一份带单位的参数请求分别派生详细 PWM 和平均值 MMC 设计。
3. 详细 PWM 引擎以已安装的官方示例为只读来源，在工作区派生副本中完成经过审核的参数修改和路径修复。
4. 平均值引擎使用仓库自有、可审计的组件和蓝图确定性构建工程。
5. 为正常运行、功率变化、交流故障、直流故障和保护动作生成可执行仿真场景及明确判据。
6. 在不改变用户额定目标和故障条件的前提下，对可恢复错误执行有界、可追溯的候选调整。
7. 只有独立通过结构、编译、仿真和物理判据的候选才发布为最终工程。
8. 保持现有 83 个工具、LCC 计划载荷和哈希、错误形状及安全边界兼容。

## 非目标

- PSCAD 5.x 实机建模或验收；5.x 只保留明确返回不支持的兼容接口。
- 保证任意有限额定参数一定可行。
- 从平均值模型推断器件开关应力、半导体热行为、开关谐波或单个子模块均压。
- 声称半桥 MMC 能依靠闭锁自阻断直流故障。
- 在第一版中支持全桥、混合桥、多端、构网、黑启动或海上孤岛频率控制。
- 修改 PSCAD 安装目录中的官方 example、用户源模型或源库。
- 把官方 PSCX/PSLX 内容复制到仓库、Python 包或默认测试夹具。
- 用降低故障强度、额定功率或验收阈值的方式制造通过结果。

## 已确认的设计决策

- 首个真实目标是本机已安装的 PSCAD 4.6.2 Legacy Automation Library。
- 第一版同时支持 `detailed_pwm` 与 `average_value`，并允许一次请求选择 `both`。
- 第一版拓扑限定为两端、对称单极、半桥 MMC；两个换流站分别采用 P/Q 与 Vdc/Q 控制。
- 官方详细模型采用“只读审计来源 + 工作区派生副本”，平均值模型采用“仓库自有资产 + 从空工程构建”。
- 两种模型共享请求和生命周期契约，但保留独立的参数推导、执行器和验收引擎。
- 自动调整只作用于隔离候选，默认最多四个预先规划的候选。
- 直流故障验收检查保护和断路器行为，并明确半桥不能自阻断；它不把持续二极管续流误判为调参问题。
- 最终发布必须原子完成，失败候选不得占用最终工程名。

## 总体架构

新增或扩展以下职责边界：

```text
installed official example or repository-owned AVM assets
    -> MMC inspection and source audit
    -> normalized MmcParametricRequest
    -> common feasibility envelope
       -> detailed PWM derivation and binding plan
       -> AVM derivation and construction plan
    -> immutable parent plan and per-engine plan hashes
    -> confirmed staged candidate execution
    -> structural validation and compile
    -> recommended standard scenarios
    -> per-engine dynamic and physical acceptance
    -> bounded diagnosis-driven candidate adjustment
    -> atomic publication and evidence report
```

MMC 专用实现位于 `pscad_mcp.hvdc.builders.mmc`。建议按职责拆分：

- `inspection.py`：解析 PSCX/PSLX 层级、连线、角色、模型精度和来源证据；
- `template_audit.py`：审计官方详细模板、依赖库、绝对路径和可写参数绑定；
- `parametric_models.py`：公开请求、设计、候选、计划、场景、调整和报告记录；
- `derivation.py`：公共额定量、功率平衡、标幺基值和约束裕度；
- `engines/pwm.py`：官方详细模板派生、参数补丁和详细模型验收；
- `engines/avm.py`：平均值资产加载、蓝图扩展、构建和 AVM 验收；
- `scenarios.py`：标准正常/故障场景及模型能力标记；
- `diagnostics.py`：失败分类和可重试性判定；
- `adjustment.py`：有界候选生成、排序和停止规则；
- `service.py`：公开生命周期、租约、暂存、日志和原子发布。

通用 PSCX 解析、不可变记录、工作区租约、原子日志和正交布线只有在两个已验证消费者确实需要时才进入 `pscad_mcp.hvdc.builders.common`。MMC 电气规则、控制器、模板绑定和验收规则不得抽成假通用逻辑。

## 公开工具契约

新增七个工具；现有 83 个工具不改名，安装后的预期库存为 90：

1. `audit_mmc_template(template_path=None, library_path=None)`
   - 只读发现或审计 PSCAD 4.6.2 官方详细示例；
   - 返回哈希、工程版本、模型精度、依赖、绝对路径、角色绑定、可参数化字段和阻断项；
   - 未显式提供路径时只检查已知 PSCAD 4.6 example 位置，不做全盘搜索。
2. `derive_mmc_parameters(request)`
   - 纯计算，不启动 PSCAD，不写文件；
   - 返回公共设计和每个模型引擎的候选、裕度、警告及不可行建议。
3. `plan_parametric_mmc_model(request, project_name, folder, template_path=None, library_path=None)`
   - 只读绑定设计、源哈希、资产哈希、操作列表、场景和候选；
   - 返回父计划哈希及每个模型的子计划哈希。
4. `build_parametric_mmc_model(request, expected_plan_hash, project_name, folder, template_path=None, library_path=None, confirm=False)`
   - 要求精确计划哈希和 `confirm=true`；
   - 启动后台构建、仿真、调整和原子发布工作。
5. `get_parametric_mmc_build_status(build_id)`
   - 返回两个引擎的状态、候选历史、当前阶段、错误、调整差异、证据路径和能力级别。
6. `recommend_mmc_simulation(request_or_project, objectives=None)`
   - 返回可直接交给 `run_hvdc_scenario` 的标准场景、步长、时长、事件、测点、单位、阈值和模型限制。
7. `validate_mmc_model(project_name, model_fidelity, output_files=None, acceptance_scope="full")`
   - 独立重读已保存工程和输出；
   - 区分结构、编译、正常动态、故障动态和完整接受结果。

现有 `inspect_hvdc_project` 增强 MMC 结构证据，`run_hvdc_scenario`、`analyze_hvdc_results` 和 `compare_hvdc_scenarios` 继续承担通用运行与结果接口。新增工具不直接暴露 Legacy vendor proxy。

## 参数请求

`MmcParametricRequest` 使用显式单位和版本化字段。核心载荷为：

```json
{
  "schema_version": 1,
  "model_fidelity": "both",
  "topology": "two_terminal_symmetrical_monopole",
  "converter": "half_bridge",
  "dc_voltage_kv": 640.0,
  "active_power_mw": 1000.0,
  "reactive_power_mvar": 0.0,
  "frequency_hz": 60.0,
  "station_p": {
    "ac_voltage_kv": 230.0,
    "short_circuit_ratio": 5.0,
    "x_over_r": 10.0
  },
  "station_vdc": {
    "ac_voltage_kv": 230.0,
    "short_circuit_ratio": 5.0,
    "x_over_r": 10.0
  },
  "dc_link": {
    "kind": "overhead_line",
    "length_km": 200.0
  },
  "power_reversal_time_s": 0.5,
  "engineering_overrides": {}
}
```

`model_fidelity` 只接受 `detailed_pwm`、`average_value` 或 `both`。第一版不接受其他拓扑或桥型。所有数值必须有限、为声明单位并处于资源上限内。

公共推导至少计算直流电流、交流基值、变压器容量和变比、网侧等值阻抗、线路压降、功率损耗预算、调制裕度和控制带宽边界。PWM 推导另计算子模块额定电压、子模块数量、单元电容、开关/采样关系和详细桥臂参数。AVM 推导另计算等效桥臂电容、储能、损耗模型和等效闭锁导通路径。

`engineering_overrides` 只能覆盖已登记、带单位且可验证的工程参数。覆盖不会绕过派生约束，也不会改变请求额定值。未被模板审计确认为可写的 PWM 字段必须拒绝，而不是按名称猜测。

## MMC 读取契约

读取器必须使用 XML 结构解析，不用文本替换推断拓扑。它需要理解：

- 项目、Definition、schematic 和嵌套 User 组件作用域；
- PSCAD 4.6 Wire 的 vertex 序列、端口坐标和节点合并；
- `using namespace`、本地定义、Master Library 和外部 PSLX 依赖；
- 电气端口与数据端口的隔离；
- 两个站、六相桥臂路径、上下桥臂、正负直流端和交流相中点；
- 子模块/等效子模块、桥臂电抗、电容、触发、载波、PLL、dq 控制、环流控制、闭锁和断路器；
- 输出通道的层级路径、call ID 和单位；
- 参数值、表达式、变量引用、定义位置和实例覆盖之间的来源链。

读取结果必须给出证据和置信度。单极/双极、两端数量、模型精度或连接关系证据不足时返回 `unknown`/`incomplete`，不回退到组件名称猜测。LCC 专用 return-path 提示不得出现在 MMC 报告中。

本机官方示例是读取验收目标，但默认 CI 只提交独立编写、结构同形而不复制官方表达的 XML 小型夹具。

## 官方 PWM 模板边界

官方示例和 `intermediate.pslx` 永远是只读源。规划记录源路径、文件哈希、版本、定义清单和绑定摘要。构建确认后：

1. 在 `PSCAD_MCP_WORKSPACE` 下创建唯一暂存目录；
2. 将用户本机已安装的工程和库复制到暂存目录；
3. 验证复制前后内容哈希；
4. 只在副本中移除失效启动快照、作者机器线路数据库路径和常数文件路径；
5. 用 PSCAD 公开服务边界加载派生副本和本地库；
6. 只修改模板审计确认的实例参数和设置；
7. 每次修改后读回并验证；
8. 保存、重读图、编译、仿真和验收；
9. 仅在通过后原子发布最终逻辑名。

路径修复不能静默替换电气数据。线路数据库或常数不可从 PSCAD 公开定义重新生成时，候选返回明确阻断项。构建结束后再次核对官方源哈希。

## 平均值模型引擎

平均值引擎从 `codex/mmc-autonomous-builder` 的原创资产和模块出发，但合并前必须逐项重新审计其许可证、manifest、公式、组件端口、Master Library 定义和当前主分支兼容性。分支存在不等于资产已通过许可版 PSCAD。

AVM 工程从空 PSCX 构建，主画布显式保留两个站和十二个桥臂。每个桥臂保留上下桥臂电流、等效储能、等效电容电压、插入电压、调制请求、裁剪值、裕度和累计饱和时间。闭锁状态需要显式表示半桥二极管等效导通路径，使系统级直流故障响应不被错误截断。

AVM 不得输出单个子模块均压、器件热应力、开关谐波或详细开关损耗的通过判定。这些字段在报告中标记为 `not_modeled`。

## 双模型生命周期

当 `model_fidelity="both"` 时，一个父计划包含两个互不覆盖的子计划。默认最终逻辑名分别追加 `_pwm` 和 `_avm`。两个模型具有独立候选、工程、输出、验收状态和哈希；一个模型通过不能替另一个模型通过。

生命周期级别为：

- `inspected`：源和结构证据可读；
- `designed`：至少一个分析候选通过静态约束；
- `planned`：不可变操作、候选和场景已绑定哈希；
- `built`：保存工程与计划在结构和参数上匹配；
- `simulated`：所有要求场景完成并有完整输出；
- `accepted`：结构、动态、物理和模型特定判据全部通过。

构建在后台执行。失败候选可保留有限日志和证据，但不得出现在最终工程路径。最终发布使用原子目录/文件替换，并在发布后再次编译冒烟和重读验证。

## 仿真建议

`recommend_mmc_simulation` 生成结构化、可执行场景。建议由模型精度、开关频率、控制采样、线路传播时间、预充电和用户目标决定，不使用固定自然语言模板。

标准场景集包括：

1. 初始化、预充电、交流断路器合闸和解锁；
2. 正向额定稳态；
3. 有功阶跃；
4. 无功阶跃；
5. 正向到反向的功率反转；
6. 反向额定稳态；
7. 三相交流故障与清除；
8. 单相接地交流故障与清除；
9. 极间直流故障、闭锁、断路器动作与清除；
10. 极对地直流故障、闭锁、断路器动作与清除；
11. 故障后恢复或明确的不可恢复终态。

每个场景声明仿真步长、输出步长、总时长、事件时刻、前置状态、命令绑定、结果选择器、单位和阈值。详细 PWM 步长必须由开关周期与最快控制动态共同约束；AVM 可使用较大步长，但必须满足控制和线路动态采样要求。

核心测量至少覆盖两端 P/Q、交流电压电流、直流极间电压、直流电流、六相桥臂电流、桥臂/子模块等效电容电压、环流、调制裕度、闭锁命令、断路器命令和状态。详细 PWM 额外检查单元级聚合范围与载波/触发一致性；AVM 只检查其声明可表示的聚合量。

对半桥直流故障，成功意味着故障被正确施加、闭锁和断路器按顺序动作、二极管续流被模型保留、故障电流和能量证据完整，并在清除后达到声明终态。报告必须写明 `intrinsic_dc_fault_blocking=false`。

## 诊断和有界自动调整

调整候选必须在规划阶段完整生成并参与计划哈希。运行中不得发明未规划参数。默认最多四个候选，可配置范围为 1 至 8；提高上限会产生新的计划哈希。

允许的调整类别为：

- `binding_repair`：移除副本中的失效快照、重新绑定本地官方库、修复已确认输出通道；
- `numerical_stability`：减小仿真步长、减小输出步长、延长预充电或斜坡；
- `control_stability`：在声明带宽、限幅和稳定裕度内选择另一组 PI 参数；
- `modulation_margin`：在保持额定值的前提下选择通过电压与调制约束的子模块/变压器候选；
- `energy_balance`：调整可派生的单元电容、等效电容或桥臂电抗候选；
- `initialization`：改变预充电、复位、解锁的允许时序，不跳过安全状态。

以下情况不可自动调整：

- 许可证、编译器安装或 PSCAD 连接故障；
- 官方源哈希、资产哈希或计划哈希变化；
- 未确认或冲突的模板参数绑定；
- 用户请求的额定值或故障条件本身不可行；
- 需要降低故障强度、额定功率或验收阈值；
- 半桥直流故障自阻断等不具备的物理能力；
- 发生无法证明已隔离的部分修改或工作区租约冲突。

每个候选记录父候选、触发错误、证据、参数差异、公式版本、尝试序号、结果和输出哈希。同一失败签名在同一参数状态重复出现时立即停止。候选耗尽返回失败约束、最小缺口和排序后的最近可行建议；建议只有在用户重新规划并确认新哈希后才能执行。

## 错误契约

所有错误沿用稳定 `BackendError` 形状：`code`、`message`、`backend`、`operation`、`details`、`retryable` 和 `suggested_action`。`details` 必须 JSON-safe，并携带源、计划、候选和阶段证据。

MMC 关键错误码包括：

- `MMC_TEMPLATE_NOT_FOUND`
- `MMC_TEMPLATE_INVALID`
- `MMC_TEMPLATE_SOURCE_CHANGED`
- `MMC_LIBRARY_MISSING`
- `MMC_ABSOLUTE_PATH_UNRESOLVED`
- `MMC_BINDING_MISSING`
- `MMC_BINDING_AMBIGUOUS`
- `MMC_MODEL_UNSUPPORTED`
- `MMC_REQUEST_INVALID`
- `MMC_DESIGN_INFEASIBLE`
- `MMC_PLAN_STALE`
- `MMC_BUILD_CONFLICT`
- `MMC_POSTCONDITION_FAILED`
- `MMC_STRUCTURE_INVALID`
- `MMC_COMPILE_FAILED`
- `MMC_OUTPUT_INCOMPLETE`
- `MMC_NUMERICAL_UNSTABLE`
- `MMC_CONTROL_UNSTABLE`
- `MMC_PROTECTION_INADEQUATE`
- `MMC_CANDIDATES_EXHAUSTED`
- `MMC_ACCEPTANCE_FAILED`
- `MMC_BUILD_TIMED_OUT`

连接/执行器超时沿用核心恢复流程；需要先调用 `repair_connection` 的错误不得被 MMC 参数调整吞掉。

## 安全和并发

- 所有写入限定在已配置 `PSCAD_MCP_WORKSPACE`；
- 官方 example 和用户源路径只读，并在前后核对 SHA-256；
- 构建要求 `confirm=true` 和精确计划哈希；
- LCC 与 MMC 构建共享一个工作区级跨进程租约，避免同时操纵 PSCAD 会话；
- 详细 PWM 与 AVM 子构建在同一父作业内串行执行；
- 每个组件创建、参数写入、连线、保存、编译和输出读取都执行读回后置条件；
- 超时或进程中断把候选标记为 `interrupted`，不静默续跑；
- 清理只针对已解析且位于本次暂存目录的路径；
- 不终止外部 PSCAD 进程，不覆盖现有最终工程。

## 默认测试策略

实现使用测试先行。默认测试不启动 PSCAD，并覆盖：

### 读取和审计

- PSCAD 4.6 Definition 层级、User 引用、using namespace 和外部库；
- vertex Wire 到组件端口的连通图；
- 两端对称单极与双极证据，不再按 `pole` 名称数量误判；
- PWM、AVM、未知模型精度；
- 缺失/冲突站、桥臂、控制、保护、测点和单位；
- 绝对路径、源哈希和库哈希变化；
- 合成同形夹具，不提交官方表达内容。

### 参数与计划

- 单位、有限值、极端值和资源上限；
- 电流、功率、能量、调制、纹波、线路压降和带宽公式；
- 参数缩放的 metamorphic 测试；
- PWM 与 AVM 的确定性设计和计划哈希；
- `both` 的父子计划关联和独立目标名；
- 覆盖值不能绕过约束；
- 不可行请求在 PSCAD 写入前停止并返回最近建议。

### 执行和隔离

- 在每个复制、加载、组件、参数、连线、保存、编译、运行、输出、验收和发布步骤注入失败；
- 失败后没有最终项目，源哈希不变，后续操作未执行；
- 候选数、顺序和差异与计划完全一致；
- 相同失败签名停止循环；
- LCC/MMC 共享租约互斥；
- 中断记录、日志原子性和安装包资源加载。

### 场景和验收

- 正常启动、P/Q 阶跃、反转和稳态合成波形；
- 交流故障穿越、闭锁和恢复；
- 直流故障电流、闭锁、二极管续流、断路器和清除；
- 不完整通道、错误单位、非有限样本和时间窗不足；
- PWM/AVM 能力矩阵，防止 AVM 生成器件级通过结论；
- 每个模型独立接受，跨模型比较不替代任一模型验收。

### 回归和包装

- 现有全部测试继续通过；
- 现有 83 个工具名称和默认返回形状不变；
- LCC canonical 计划载荷和哈希不变；
- wheel 安装后七个 MMC 工具存在，总库存为 90；
- 官方 example 和 library 不进入 wheel、源码包或测试夹具。

## PSCAD 4.6.2 实机验收

实机验收是显式 opt-in 测试，只在隔离时间戳工作区运行。它必须：

1. 记录 PSCAD、Automation Library、编译器和提交版本；
2. 发现并只读审计官方 example 与 `intermediate.pslx`；
3. 记录源前置哈希；
4. 对每个请求执行派生、规划、确认、构建、完整场景和独立重验；
5. 记录工程、库、计划、输出和报告哈希；
6. 发布后重新加载并编译冒烟；
7. 核对官方源后置哈希和预存工作区文件不变；
8. 输出有界 JSON 报告并更新 `docs/acceptance-status.json`。

最低矩阵为：

- `detailed_pwm` 三个明显不同且分析可行的额定请求；
- `average_value` 三个明显不同且分析可行的额定请求；
- 六个覆盖电压/调制、能量/纹波、线路压降、短路比、控制带宽和资源上限的不可行请求。

六个可行请求都必须通过其完整标准场景；不能用一个名义工程替其他额定值背书。不可行请求必须在任何工程修改前停止。该矩阵证明流程覆盖多个请求，不构成任意输入均可行的数学证明。

如果许可证、编译器、Automation Library、官方 example 本身或模板绑定阻止完整运行，验收记录为 `INCOMPLETE_ANALYSIS` 并保留失败阶段。默认单元测试、mock 输出、源工程可解析或单次编译成功都不能升级为实机 `PASS`。

## 交付顺序

1. 完成读取器和官方模板审计，使官方 MMC 示例得到正确、可解释的结构报告。
2. 完成统一请求、单位、派生、可行性和不可变父子计划。
3. 完成详细 PWM 工作区派生、参数绑定、结构验证和标准正常场景。
4. 重新审计并整合平均值资产，完成 AVM 从空工程构建和正常场景。
5. 完成交流/直流故障场景、模型能力矩阵和物理限制报告。
6. 完成诊断、预规划候选、有界自动调整和最近可行建议。
7. 执行默认回归、包装测试和 PSCAD 4.6.2 实机矩阵。
8. 只有相应 scope 取得真实证据后，更新中英文文档和能力声明。

## 完成标准

本设计完成需同时满足：

- 官方详细 MMC 示例可被正确识别为两端对称单极半桥 PWM 模型，连通图和关键角色有结构证据；
- 同一参数请求可生成 PWM、AVM 或两者的确定性设计与计划；
- 官方源文件和库在成功、失败和中断后哈希不变；
- 两个引擎只发布独立通过完整验收的最终工程；
- 仿真建议可直接执行并覆盖正常、反转、交流故障、直流故障和保护动作；
- 半桥直流故障限制及 AVM 精度限制在机器可读报告中明确；
- 自动调整有界、可追溯、不改变用户额定值、故障条件或阈值；
- 不可恢复和物理不可行错误停止安全，并给出具体下一步；
- 现有 LCC、HVDC 和 83 工具行为不回归；
- PSCAD 4.6.2 实机状态按 scope 和提交如实记录，不继承其他模型或历史提交的 PASS。
