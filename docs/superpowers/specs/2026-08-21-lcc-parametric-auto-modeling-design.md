# LCC 参数化自动建模设计

## 目标

在现有固定 CIGRE LCC 构建器之上，增加参数化自动建模能力。用户提供额定参数、可选工程参数覆盖和运行方式要求后，系统生成可审查、可构建、可仿真和可验收的 PSCAD LCC 工程。

首版目标同时覆盖单极和双极 LCC，并为后续用户组件模板替换保留稳定边界。第一阶段仍以 PSCAD 4.6.2 为主要实机目标；PSCAD 5.x 不纳入本设计的真实验收承诺。

## 已确定范围

- 拓扑：单极、双端、12 脉波 LCC，以及双极、双端、12 脉波 LCC；
- 输入：混合模式，额定参数必填，工程师可覆盖自动推导参数；
- 输出：结构正确的 Blueprint、独立运行方式副本、稳态仿真验收和运行方式验收；
- 运行方式：双极运行、单极大地回线、金属回线、正极/负极退出和恢复；
- 时序切换：在后端能力明确提供仿真时钟、写入和读回后，支持仿真期间切换；
- 模板：第一阶段使用仓库内审计组件目录，第二阶段接入用户工程或 companion library；
- 安全：原始用户模板只读，所有构建写入独立目标工程，并要求确认和精确 plan hash；
- 兼容：现有四个固定 CIGRE LCC 工具及原有 77 工具契约保持不变。

## 非目标

- 不在本设计中支持任意 PSCAD 版本的通用兼容；
- 不从名称猜测用户组件的端口或参数；
- 不修改用户提供的原始工程或库文件；
- 不把编译成功、仿真结束或部分指标通过当作自动建模成功；
- 不在首版同时实现所有交流/直流故障注入、换相失败控制策略优化或 MMC 建模。

## 方案选择

方案一是在固定 CIGRE 构建器上继续堆叠功能，初期改动小，但单极/双极、参数推导和模板替换会形成高耦合。

方案二是一次重做为完全通用的 LCC 建模器，扩展性强，但需要同时解决参数推导、任意组件兼容、版本差异和实机验收，风险过高。

采用方案三：分层参数化建模框架。固定构建器继续作为已验证的底层能力；新能力增加参数推导层、单极/双极 Blueprint 层、模板适配层和运行方式层。单极与双极共享通用规划、执行、图解析、日志和验收设施，但使用独立 Blueprint、拓扑约束和验收契约。

```text
用户规格/模板
    -> 参数推导与可行性检查
    -> 单极/双极 Blueprint
    -> 组件目录或模板适配器
    -> PSCAD 构建、编译和仿真
    -> 结构、稳态、运行方式验收
```

## 输入模型

自动建模请求分为四层：

```text
topology
  - monopole | bipolar
  - terminals
  - return_mode

ratings
  - rated_power
  - dc_voltage
  - dc_current
  - ac_voltage
  - frequency
  - SCR / ESCR

engineering_overrides
  - converter_transformer
  - smoothing_reactor
  - ac_filters
  - firing/extinction limits
  - controls
  - protection

operation_modes
  - bipolar_run
  - monopolar_earth_return
  - metallic_return
  - pole_outage
  - scheduled_switching
```

额定参数是必填的；工程覆盖参数是可选的。覆盖项必须通过严格 schema、单位、类型和范围检查，不能绕过组件目录契约。

参数推导器只生成中间结果，不直接访问 PSCAD 或写文件。每个最终参数生成一条 `DerivedParameterReport`，至少包括：

- `value`：最终值；
- `source`：`user`、`derived` 或 `default`；
- `formula`：推导规则或依据；
- `constraints`：允许范围和单位；
- `warnings`：接近运行边界或使用默认值时的提示。

生成 Blueprint 前必须检查：

- 功率、电压、电流的额定关系一致；
- 单极/双极的功率和电流关系一致；
- SCR、换流变漏抗和平波电抗器在允许范围内；
- 触发角、灭角和换相重叠角存在可行运行区间；
- 双极模型的中性点和回流方式完整；
- 所有运行方式引用的开关、控制信号和测点均已绑定。

检查失败时返回结构化诊断，不创建工程、不创建 staging 目录。

## Blueprint 与组件适配

首版至少注册两个独立 Blueprint：

- `lcc_monopole_parametric_v1`；
- `lcc_bipole_parametric_v1`。

双极 Blueprint 不通过把单极的 `poles` 改成 2 来伪装生成，而是显式声明正极、负极、中性点、接地极/金属回线、极间测点和运行方式约束。

### 固定目录模式

第一阶段使用仓库内审计过的组件目录。每个组件记录精确 definition、端口方向/类型、参数类型、单位、允许范围、PSCAD 版本和资产哈希。参数化构建只能实例化目录中已验证的组件。

### 用户模板模式

第二阶段提供只读 `audit_lcc_template` 流程，检查：

1. PSCAD 版本和文件身份；
2. definition、端口方向和端口类型；
3. 参数名、类型、单位和读写能力；
4. 标准角色映射，例如 `rectifier_valve_group`、`inverter_valve_group`、`rectifier_control`、`inverter_control`、`smoothing_reactor` 和 `earth_electrode`。

只有全部必需端口和参数满足标准契约，且不存在歧义候选，才允许用户确认后生成派生 Blueprint。原始模板永不被修改；构建始终写入独立目标工程。

## 运行方式与时序切换

运行方式采用“独立副本优先、仿真内切换可选”。系统可以从一个基础 Blueprint 派生多个目标工程：

- `bipolar_run`；
- `monopolar_earth_return`；
- `monopolar_metallic_return`；
- `positive_pole_outage`；
- `negative_pole_outage`。

每个副本独立保存参数、开关状态、控制初值、输出和验收报告，便于审计和横向比较。

仿真期间切换只有在后端明确提供以下能力时才可用：

- EMTDC 仿真时间调度；
- 精确的开关/控制参数绑定；
- 写入后的读回确认；
- 输出通道就绪检查；
- 仿真时钟停滞检测；
- 取消、超时和恢复机制。

切换事件的 `time_s` 始终表示仿真时间，不使用墙钟时间。事件必须有稳定 ID，并在仿真启动前拒绝重复 ID、无序事件、未绑定控制量或不具备后端能力的计划。

运行方式验收至少检查：

- 回流路径是否与目标模式一致；
- 极电流、电压和中性点关系；
- 接地极或金属回线电流；
- 极退出后的电流闭合；
- 切换前后功率连续性；
- 切换后的恢复时间；
- 未声明的保护动作或拓扑冲突。

所有运行方式写入都要求显式确认，并保存事件、读回值和结果证据。

## 公共工具边界

现有 `plan_lcc_model`、`build_lcc_model`、`get_lcc_build_status` 和 `validate_lcc_model` 保持原有语义和参数契约。新增工具建议为：

- `derive_lcc_parameters`：只读生成参数和推导证据；
- `audit_lcc_template`：只读审计用户工程/库和标准角色映射；
- `plan_parametric_lcc_model`：只读生成 Blueprint、操作清单、资产哈希、plan hash 和验收门槛；
- `build_parametric_lcc_model`：在确认和 plan hash 匹配后创建独立工程，执行构建、编译、稳态仿真和场景；
- `get_parametric_lcc_build_status`：返回阶段、场景、失败证据、最终路径和验收报告；
- `validate_lcc_operating_modes`：对已有工程或构建结果执行只读结构、稳态和运行方式验收。

新增工具继续使用现有结构化错误边界、工作区路径策略、构建 lease、日志和资产哈希机制。

## 错误与安全边界

新增稳定错误码包括：

- `LCC_RATING_INVALID`；
- `LCC_PARAMETER_DERIVATION_FAILED`；
- `LCC_OPERATING_MODE_INVALID`；
- `LCC_TEMPLATE_INCOMPATIBLE`；
- `LCC_TEMPLATE_AMBIGUOUS`；
- `LCC_SWITCHING_UNAVAILABLE`；
- `LCC_MODE_ACCEPTANCE_FAILED`。

任何参数、拓扑、模板或后端能力不确定都必须 fail closed。构建前仍要求 `confirm=true` 和精确 `expected_plan_hash`；已有目标不得覆盖；用户源模板、源工程和仓库资产不得被修改。

## 验证策略

### 单元和契约测试

- 参数 schema、单位、范围、覆盖优先级和推导证据；
- 单极/双极 Blueprint 的确定性和 plan hash 稳定性；
- 功率、电流、回流路径和控制角度的可行性检查；
- 模板端口/参数审计、缺失和歧义拒绝；
- 独立副本生成、路径隔离、确认和 lease；
- 仿真时钟、稳定事件 ID、重复事件和读回确认；
- 旧四个 LCC 工具和 77 工具库存回归。

### 结构和仿真验收

- 组件、端口、参数、线路和输出通道的 Blueprint 对比；
- 直流电压、电流、功率、触发角、灭角和换相重叠；
- 纹波、功率平衡、控制误差和极间不平衡；
- 大地回线、金属回线、极退出和恢复；
- 时序切换后的模式证据、恢复时间和保护行为。

### 授权 PSCAD 验收

默认测试不启动 PSCAD。单独的 opt-in 验收必须在隔离工作区通过生产 service/backend 边界运行，记录 blueprint、模板、资产、编译器、最终工程和输出哈希，并确认源文件未改变。未完成真实编译、仿真和验收时，只能报告相应的能力级别，不能称为已验收的自治 LCC 自动建模。

## 交付顺序

1. 参数推导、schema 和可行性检查；
2. 单极/双极参数化 Blueprint；
3. 稳态构建、仿真和物理验收；
4. 运行方式独立副本和跨模式比较；
5. 仿真内时序切换；
6. 用户模板只读审计和派生 Blueprint。

该顺序不改变最终范围，但把可验证的确定性基础放在模板适配和时序写入之前。
