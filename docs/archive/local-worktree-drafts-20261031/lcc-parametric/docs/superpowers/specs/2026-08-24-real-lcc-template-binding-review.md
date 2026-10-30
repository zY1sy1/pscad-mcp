# 真实 LCC 模板参数绑定审核清单

> 用途：供 Codex 后续阅读、审核和实现真实 PSCX 参数绑定。
>
> 本文档只定义审核工作和证据要求，不授权直接修改源模板，也不代表真实 PSCAD 验收已经完成。

## 1. 任务目标

为真实模板建立一份可审计的“逻辑参数 → PSCX/PSCAD 参数”绑定清单，使参数化 LCC 构建器能够安全完成：

1. 源模板只读检查；
2. 复制到隔离 staging 工作区；
3. 对已审核参数进行写入；
4. 读回并核对参数值和单位；
5. 通过 PSCAD 编译、仿真和波形验收。

在绑定没有唯一定位、单位没有确认或读回没有通过之前，必须保持：

```text
topology_plan.executable = false
```

## 2. 真实模板基线

### 源文件

```text
C:\Users\335\Desktop\moxing\HVDC_Bipolar_1000MW_500kV.pscx
```

基线 SHA-256：

```text
159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993
```

当前已知文件信息：

```text
size = 348498 bytes
last_write = 2026-04-17 19:25:00
```

Codex 每次开始审核前必须重新计算哈希；如果哈希变化，停止使用旧证据并重新审计。

## 3. 已确认的 PSCX 结构

真实模板包含以下顶层 `Definition`：

```text
PI_AntiWindUp
Inverter_AC
Rectifier_AC
RectCC
RectFilters
TransLine
InverterFilters
MasterPOCntrl
RectPole
InverterPole
InvCtrl
Station
Main
```

已确认的顶层角色：

| 角色 | 定义/实例 | 已知证据 |
|---|---|---|
| 整流正极 | `Main` 中 `HVDC_Bipolar_1000MW_500kV:RectPole` | `Des=RP1` |
| 整流负极 | `Main` 中 `HVDC_Bipolar_1000MW_500kV:RectPole` | `Des=RP2` |
| 逆变正极 | `Main` 中 `HVDC_Bipolar_1000MW_500kV:InverterPole` | `Des=IP1` |
| 逆变负极 | `Main` 中 `HVDC_Bipolar_1000MW_500kV:InverterPole` | `Des=IP2` |
| 站级参数 | `Main` 的 form 参数及 `Station` 中的 Main 实例 | `Freq` 已观察到 `50.0 Hz` |
| 接地电极 | `Main` 中 `master:ammeter` | `Name=Ielectrode` |
| 整流交流系统 | `Rectifier_AC` | `source3`、电抗器、电阻 |
| 逆变交流系统 | `Inverter_AC` | `source3`、电抗器、电阻 |
| 整流滤波器 | `RectFilters` | 多个 `capacitor`、`inductor`、`breaker3` |
| 逆变滤波器 | `InverterFilters` | 多个 `capacitor`、`inductor`、`breaker3` |
| 直流线路 | `TransLine` | 电容、电感、电阻 |
| 整流控制 | `RectCC` | `PI_AntiWindUp`、`AOR` 等 |
| 逆变控制 | `InvCtrl` | `Gamma`、`AOI`、`PI_AntiWindUp` 等 |

## 4. 绑定审核原则

### 4.1 禁止使用的位置索引

禁止把以下形式写入生产绑定：

```text
definitions[12]/schematic[105]/User[0]/paramlist[9]
```

禁止依赖：

- XML 子节点顺序；
- “第一个 capacitor”；
- 仅按 `defn` 子字符串匹配；
- 仅按参数名匹配而不核对组件定义、实例 ID 和角色；
- 把所有同名 `C`、`L` 或 `Value` 一起修改。

### 4.2 允许的稳定定位字段

每个绑定至少必须包含：

```json
{
  "logical_parameter": "frequency_hz",
  "topology": "bipolar",
  "role": "station",
  "definition": "Main",
  "component_id": "1549322604",
  "component_definition": "HVDC_Bipolar_1000MW_500kV:Main",
  "parameter": "Freq",
  "attribute": "value",
  "units": "Hz",
  "binding_status": "reviewed",
  "match_count": 1,
  "source": "real-template-readonly-audit"
}
```

如果组件 ID 在 PSCAD 保存后不稳定，必须补充稳定的语义证据，例如：

- 所在 `Definition` 名称；
- 完整 definition 名称；
- role/discriminator，例如 `Des=RP1`；
- 参数名；
- 关键端口或邻接关系；
- 写入前后唯一匹配数量。

不能因为 ID 存在就跳过语义核对。

### 4.3 绑定必须可读回

每个审核通过的绑定都必须支持：

1. 读取旧值；
2. 写入测试值；
3. 再次读取；
4. 确认值和单位一致；
5. 恢复或丢弃测试 staging 文件；
6. 确认源模板哈希没有变化。

## 5. 待审核绑定清单

下表是工作目标，不是已批准绑定。每项完成后才可把状态从 `PENDING` 改为 `REVIEWED`。

| ID | 逻辑参数 | 目标区域 | 候选参数 | 单位 | 状态 |
|---|---|---|---|---|---|
| B-001 | `frequency_hz` | `Main` form 参数 / `Station` Main 实例 | `Freq` | Hz | `PENDING` |
| B-002 | `ac_voltage_kv`（整流侧） | `Rectifier_AC` 的 `master:source3` | `Vm`、`Es` | kV | `PENDING` |
| B-003 | `ac_voltage_kv`（逆变侧） | `Inverter_AC` 的 `master:source3` | `Vm`、`Es` | kV | `PENDING` |
| B-004 | `smoothing_reactor_mh`（整流侧） | `RectPole` 内部指定电抗器 | `L` | mH/H | `PENDING` |
| B-005 | `smoothing_reactor_mh`（逆变侧） | `InverterPole` 内部指定电抗器 | `L` | mH/H | `PENDING` |
| B-006 | `filter_capacitance_uf`（整流侧） | `RectFilters` 指定滤波支路 | `C` | uF/F | `PENDING` |
| B-007 | `filter_capacitance_uf`（逆变侧） | `InverterFilters` 指定滤波支路 | `C` | uF/F | `PENDING` |
| B-008 | `min_firing_angle_deg` | `RectCC` 控制链 | 角度设定/限幅参数 | deg/rad | `PENDING` |
| B-009 | `max_firing_angle_deg` | `RectCC` 控制链 | 角度上限/限幅参数 | deg/rad | `PENDING` |
| B-010 | `min_extinction_angle_deg` | `InvCtrl` 控制链 | Gamma 最小值/限幅参数 | deg/rad | `PENDING` |
| B-011 | `overlap_angle_deg` | `RectCC`/`InvCtrl` 控制链 | 换相或控制补偿参数 | deg/rad | `PENDING` |
| B-012 | `dc_voltage_kv` | 直流线路、控制基准和测量基准 | 组合绑定，禁止单字段猜测 | kV | `PENDING` |
| B-013 | `dc_current_ka` | 直流控制、电流基准和测量基准 | 组合绑定，禁止单字段猜测 | kA | `PENDING` |
| B-014 | `rated_power_mw` | 交流源、控制功率阶跃和测量基准 | 组合绑定，禁止单字段猜测 | MW | `PENDING` |
| B-015 | `scr` | 交流系统等值阻抗 | 组合绑定，禁止单字段猜测 | 1 | `PENDING` |
| B-016 | `escr` | 交流系统等值阻抗与补偿 | 组合绑定，禁止单字段猜测 | 1 | `PENDING` |

## 6. 已观察到的候选值（仅作审计线索）

这些值来自源模板只读扫描，不能直接当作参数绑定或目标值：

```text
Rectifier_AC.source3:
  MVA = 100.0 [MVA]
  Vm  = 382.8672 [kV]
  Es  = 382.8672 [kV]
  F0  = 50.0 [Hz]

Inverter_AC.source3:
  MVA = 100.0 [MVA]
  Vm  = 215.05 [kV]
  Es  = 215.05 [kV]
  F0  = $(Freq)

RectCC.PI_AntiWindUp:
  Kp     = 0.5
  Ti     = 0.05
  MaxOut = 3.054
  MinOut = 0.52
  Out_Rst = 1.57

InvCtrl.PI_AntiWindUp:
  Kp     = 0.5
  Ti     = 0.01
  MaxOut = 1.92 或 1.57
  MinOut = 0.52
  Out_Rst = 1.92 或 1.57
```

注意：同一参数名在模板中可能出现多次。必须用角色、Definition、组件 ID 和邻接关系确认具体目标，不能批量替换所有同名参数。

## 7. 推荐审核顺序

### 第一步：先审核 B-001

验证 `Freq` 的真正控制点：

- `Main` form 参数声明；
- `Station` 中 Main 实例的 `Freq` 值；
- 下游 `$(Freq)` 引用是否随之生效；
- `source3.F0` 是否是独立值还是变量引用。

### 第二步：审核交流源 B-002/B-003

确认 `Vm` 与 `Es` 是否必须同步修改，并确认单位为 `kV`。写入测试值后必须检查：

- 两个字段是否都更新；
- 交流源是否仍可加载；
- PSCAD 读回值是否与计划一致。

### 第三步：审核一个明确滤波支路和一个明确电抗器

不能先处理所有 `C` 或 `L`。先选定一个具有电路拓扑、注释或稳定邻接证据的支路，完成唯一绑定闭环后再扩展。

### 第四步：审核控制角度

控制角度通常不是一个名为 `Alpha` 或 `Gamma` 的简单常量。必须沿控制信号链确认：

- 输入设定点；
- 限幅器；
- `PI_AntiWindUp`；
- 输出 `AOR`/`AOI`；
- 结果通道 `Gamma`。

如果只能找到输出测量点，不能把输出点当作写入点。

### 第五步：最后处理 P/V/I/SCR/ESCR

这些是系统级参数，必须先形成组合绑定和公式证据，再允许写入。单独修改某个交流源或某个控制常量不足以证明额定功率、直流电压、电流或 SCR 已改变。

## 8. Codex 执行要求

Codex 开始实施时必须：

1. 使用项目虚拟环境：

   ```powershell
   & .\.venv\Scripts\python.exe
   ```

2. 先写失败测试，再写生产代码；
3. 所有源模板操作使用只读句柄并重新计算 SHA-256；
4. 所有写操作仅发生在 workspace staging；
5. 绑定校验失败时，不调用 `load_projects`、`set_project_settings`、`save_project_as`、`run_project` 或仿真 API；
6. 不直接让 `LegacyBackend` 穿透应用服务生命周期；
7. 不把测试替身结果描述为真实 PSCAD 结果；
8. 不删除失败 staging 证据；
9. 不修改用户源文件；
10. 最终状态必须区分：`implemented`、`test_verified`、`installed`、`live_accepted`。

## 9. 每个绑定的验收记录格式

```json
{
  "binding_id": "B-001",
  "logical_parameter": "frequency_hz",
  "source_template_sha256": "...",
  "definition": "Main",
  "component_id": "...",
  "component_definition": "...",
  "parameter": "Freq",
  "units": "Hz",
  "old_value": "50.0 Hz",
  "test_value": "55.0 Hz",
  "readback_value": "55.0 Hz",
  "match_count": 1,
  "staging_sha256": "...",
  "source_unchanged": true,
  "status": "REVIEWED",
  "evidence": "..."
}
```

## 10. 停止条件

遇到以下任一情况，必须停止自动写入并保留诊断：

- selector 匹配 0 个或多个节点；
- 同一逻辑参数对应多个未区分角色的节点；
- 单位缺失、冲突或无法换算；
- 参数写入后读回不一致；
- 共享 Definition 修改会同时影响多个极且没有独立覆盖机制；
- 只能找到测量输出，找不到合法控制输入；
- 不能确认 PSCAD API 的真实写入和保存效果；
- 源模板哈希发生变化；
- 没有 licensed PSCAD 运行环境。

对应结果应为：

```text
LCC_PARAMETER_BINDING_UNAVAILABLE
LCC_TEMPLATE_AMBIGUOUS
LCC_TEMPLATE_INCOMPATIBLE
LCC_PLAN_STALE
LCC_BUILD_UNAVAILABLE
INCOMPLETE_ANALYSIS
```

## 11. 完成定义

只有同时满足以下条件，才能把绑定状态标记为 `REVIEWED`，并允许 `executable=true`：

- 唯一语义定位已确认；
- 单位和允许范围已确认；
- 写入测试只修改 staging；
- 读回值与计划一致；
- 源文件哈希保持不变；
- 计划哈希包含绑定证据；
- 绑定测试和 LCC 回归测试通过；
- 在 licensed PSCAD 中完成编译/仿真验证，或明确标记为尚未 live accepted。
