# LCC 双极带大地回线理解能力设计

## 1. 背景

当前 HVDC 域层能够从 PSCX/XML 证据中识别 LCC、双极、整流器、逆变器、极、直流线路、断路器和保护信号，也能对已有测点执行基本波形指标分析。但“带大地回线的双极 LCC”仍主要依赖组件名称、标签和通用 profile，尚未显式建模：

- 正极、负极和中性点的角色；
- 整流端、逆变端接地极；
- 大地回线与金属回线的路径；
- 当前回流运行方式；
- 回流路径与开关状态的一致性。

本设计只针对 LCC 双极系统，第一阶段只做只读识别与验证，不开放运行方式切换或工程修改。

## 2. 目标

第一阶段完成后，MCP 应能够：

1. 识别 LCC 双极系统中的正极、负极、中性点、接地极、回流路径和相关开关；
2. 区分 `earth_return`、`metallic_return`、`mixed_transition` 和 `unknown`；
3. 判断回流路径是否闭合，并保留可追溯证据；
4. 将极电压、极电流、接地回流电流、金属回流电流和模式开关映射为 canonical signals；
5. 在证据缺失、冲突、方向或单位不明时返回结构化的不完整/歧义结果；
6. 对四类基准 fixture 给出稳定、可回归的 inspect/validate 结果。

## 3. 非目标

第一阶段不包含：

- 自动插入接地极或重接回流线路；
- 自动切换大地回线/金属回线；
- 自动发出极退出或断路器命令；
- 保护定值优化或保护配合判定；
- 接地极热、电流密度或腐蚀评估；
- VSC/MMC 回流模式；
- 任意工程的自由拓扑重构；
- 真实 licensed acceptance。

## 4. 范围内运行场景

必须覆盖以下四类只读场景：

1. 双极正常大地回线；
2. 双极正常金属回线；
3. 一极退出、另一极通过大地回线运行；
4. 回流路径不完整或模式证据冲突。

金属回线到大地回线的动态切换作为后续扩展，不作为第一阶段的完成条件。

## 5. 领域模型

### 5.1 拓扑摘要

扩展 `HvdcTopologySummary`，增加：

```python
return_mode: str
return_path_status: str
return_path: tuple[HvdcSourceRef, ...]
pole_roles: dict[str, HvdcSourceRef]
neutral_assets: tuple[HvdcSourceRef, ...]
mode_evidence: tuple[str, ...]
```

`return_mode` 仅允许：

```text
earth_return
metallic_return
mixed_transition
unknown
```

`return_path_status` 仅允许：

```text
verified
incomplete
ambiguous
```

### 5.2 回流路径

新增独立的 `HvdcReturnPath` JSON-safe record：

```python
class HvdcReturnPath:
    mode: str
    segments: tuple[HvdcSourceRef, ...]
    endpoints: tuple[HvdcSourceRef, ...]
    closed: bool
    confidence: float
    evidence: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
```

独立 record 用于避免把金属回线、接地回线和后续其他回流方式的细节全部塞进拓扑摘要。

### 5.3 资产类型

在现有 `pole` 等资产之外，增加下列 canonical kinds：

```text
positive_pole
negative_pole
neutral_bus
neutral_conductor
earth_electrode
earth_return
metallic_return
grounding_switch
metallic_return_switch
pole_breaker
neutral_breaker
ground_fault
return_path_measurement
```

分类必须保留 `HvdcSourceRef`、置信度和原始证据；不得以没有来源的字符串结果代替资产证据。

## 6. Profile 设计

新增独立 profile：

```text
lcc_bipolar_earth_return_v1
```

该 profile 不继承 `lcc_bipolar_generic`。原因是现有通用 LCC profile 会引入与回流模式无关的功率、触发角、PLL 等要求，导致工程实际核心证据完整但整体仍被判定为不完整。

profile 至少包含：

```text
required_assets
topology_constraints
measurement_mappings
return_path_rules
mode_rules
result_channels
metric_roles
```

第一版 canonical measurements：

```text
positive_pole_voltage
negative_pole_voltage
positive_pole_current
negative_pole_current
earth_return_current
metallic_return_current
rectifier_neutral_voltage
inverter_neutral_voltage
rectifier_electrode_current
inverter_electrode_current
positive_pole_status
negative_pole_status
earth_return_switch_status
metallic_return_switch_status
```

每个映射必须声明：

```text
source
units
direction
location
status
confidence
```

`direction` 为必需语义，防止双极系统中电流符号约定不同导致错误判断。

## 7. 数据流与模块职责

```text
PSCX/XML
  -> scanner
  -> evidence graph
  -> asset extraction
  -> pole/neutral/return-path classification
  -> profile mapping
  -> mode validation
  -> inspect/validate result
```

模块职责保持单一：

- `scanner.py`：提取 XML、组件、端口、标签、参数和连接证据；
- `classifier.py`：识别资产、极性、回流候选和路径；
- `models.py`：提供 JSON-safe 领域 record；
- `profiles.py`：声明 LCC 大地回线需要的资产、信号和规则；
- `mappings.py`：解析来源、单位、方向和冲突；
- `service.py`：接入 `inspect_hvdc_project` 和 `validate_hvdc_project`；
- `metrics.py`：仅处理经过映射和验证的时间序列。

## 8. 判定规则

回流模式判定优先级固定为：

1. 已确认 profile 绑定；
2. 端口连接图形成的闭合路径；
3. 组件定义和参数证据；
4. 标签和数据标签；
5. 波形一致性；
6. 无法确认则返回 `unknown`。

单个 `ground`、`earth` 或 `electrode` 标签不能单独证明当前运行于大地回线。只有路径证据和模式证据一致，才能返回 `earth_return`。

验证至少包含：

- 正极和负极角色是否都能确认；
- 两端接地极是否能确认；
- 大地回线或金属回线是否闭合；
- 回流模式与开关状态是否一致；
- 极电压/电流和回流电流测点是否存在；
- 单位是否符合 profile；
- 单极运行时是否只有一极保持输电；
- 方向和符号约定是否已定义。

证据冲突时不得选择“最像”的模式；必须降级为 `unknown` 或 `ambiguous`。

## 9. 错误与结果契约

复用现有错误码：

```text
HVDC_TOPOLOGY_AMBIGUOUS
HVDC_MAPPING_MISSING
INCOMPLETE_ANALYSIS
```

新增：

```text
HVDC_RETURN_PATH_UNRESOLVED
```

示例：

```json
{
  "return_mode": "unknown",
  "return_path_status": "ambiguous",
  "valid": false,
  "errors": [
    {
      "code": "HVDC_RETURN_PATH_UNRESOLVED",
      "message": "Earth electrode exists but the return path is not closed."
    }
  ]
}
```

所有推断资产和映射必须保留项目路径、canvas、component、definition 和 label 等来源引用。

## 10. 指标扩展

在结构识别稳定后，增加以下指标：

```text
earth_return_current_peak
earth_return_current_rms
metallic_return_current_peak
pole_current_imbalance
pole_voltage_imbalance
return_current_closure_error
return_mode_consistency
```

这些指标必须声明单位和源通道。缺少关键通道、时间轴无效、单位未确认或方向不明时，返回 `INCOMPLETE_ANALYSIS`，不得用零值填充。

## 11. 测试计划

新增 fixture 目录：

```text
tests/fixtures/hvdc/lcc_earth_return/
```

至少包含：

```text
bipolar_earth_return.pscx
bipolar_metallic_return.pscx
positive_pole_outage_earth_return.pscx
incomplete_return_path.pscx
ambiguous_return_mode.pscx
```

建议新增测试模块：

```text
tests/test_hvdc_return_path_model.py
tests/test_hvdc_lcc_earth_return_classifier.py
tests/test_hvdc_lcc_earth_return_profile.py
tests/test_hvdc_return_path_validation.py
tests/test_hvdc_lcc_earth_return_fixture.py
```

每个 fixture 必须验证：

- family 和 polarity；
- return mode；
- return path closure；
- pole roles；
- grounding assets；
- canonical mappings；
- evidence source；
- unresolved/error output。

负向用例必须证明：无闭合路径、模式冲突和方向未知时不会误判为 `earth_return`。

## 12. 向后兼容与完成标准

必须保持：

- 现有 10 个 HVDC 工具名称不变；
- 现有 60 个通用工具不变；
- `hvdc_breaker_difforder` 现有行为不变；
- VSC/MMC profile 测试不变；
- 只读工程扫描的路径策略不变；
- 没有 command binding 时继续禁止写操作。

第一阶段完成定义：

> 对 LCC 双极大地回线工程，MCP 能基于结构证据正确识别正负极、接地极和回流路径，区分大地回线与金属回线，并在证据不足或冲突时返回未知/不完整，而不是猜测或修改工程。

## 13. 后续阶段

只有第一阶段 fixture 和验证规则稳定后，才考虑：

- 方式切换状态机；
- 大地回线/金属回线切换场景；
- 经过确认的命令绑定；
- `run_hvdc_scenario` 的只读验证型方式切换；
- 波形级回流闭合和极间不平衡分析。

