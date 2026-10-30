# 完整自动化 LCC 实施与验收规范

> 本文档供 Codex 直接阅读和执行。
>
> 目标不是生成一份“看起来合理”的 PSCX，而是建立一个可审计、可回滚、可验证、缺证据即停止的真实 LCC 自动化流程。
>
> 本文档是实施规范，不等同于已经完成的真实 PSCAD 验收。所有 PENDING、UNVERIFIED 和 NOT_AVAILABLE 状态都必须保留，不能改写成成功。

---

## 0. 给 Codex 的执行指令

开始工作时必须遵守：

1. 阅读本文件全部内容；
2. 阅读：
   - docs/superpowers/plans/2026-08-21-lcc-parametric-auto-modeling.md
   - docs/superpowers/plans/2026-08-24-lcc-real-template-execution.md
   - docs/superpowers/specs/2026-08-24-real-lcc-template-binding-review.md
3. 在专用 worktree 工作：

~~~text
D:\pscad-mcp\.worktrees\codex-lcc-parametric-auto-modeling
~~~

4. 使用项目虚拟环境：

~~~powershell
& .\.venv\Scripts\python.exe
~~~

5. 每个新行为先写失败测试，再实现代码，再跑回归；
6. 不修改真实源模板；
7. 不把 fake executor、mock backend 或 XML 解析通过称为真实 PSCAD 验收；
8. 没有编译、仿真和波形证据时，不得返回 PASS 或 published；
9. 用户说“继续”时执行下一阶段，不重开基础设计；
10. 无法验证参数路径时停止并返回结构化错误。

### 0.1 四种状态必须分开

~~~text
implemented       = 代码已实现
test_verified     = 自动化测试已通过
installed         = 已安装到目标环境
live_accepted     = licensed PSCAD 真实编译/仿真/输出验收通过
~~~

implemented=true 不等于 live_accepted=true。

---

## 1. 当前基线

### 1.1 工作分支

~~~text
worktree = D:\pscad-mcp\.worktrees\codex-lcc-parametric-auto-modeling
branch   = codex/lcc-parametric-auto-modeling
latest_lcc_commit = 7a62170 feat: add fail-closed parametric template executor
~~~

### 1.2 已完成能力

- 参数记录和输入校验；
- 单位感知的派生参数计算；
- monopolar/bipolar 参数化蓝图；
- 运行方式和 EMTDC 时间校验基础；
- 用户 PSCX 只读模板审计；
- 参数化服务的计划、哈希、lease、journal 和状态生命周期；
- fail-closed 模板执行器边界；
- 六个参数化 LCC MCP 工具；
- acceptance report 基础契约。

最近 LCC 回归基线：

~~~text
490 passed, 4 skipped
compileall passed
git diff --check passed
~~~

### 1.3 真实模板

~~~text
C:\Users\335\Desktop\moxing\HVDC_Bipolar_1000MW_500kV.pscx
~~~

基线：

~~~text
SHA-256 = 159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993
size    = 348498 bytes
~~~

每次读取前都必须重新计算哈希。哈希变化会使旧绑定证据全部失效。

### 1.4 已确认结构

顶层 Definition：

~~~text
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
~~~

顶层极角色：

~~~text
RP1 = RectPole, rectifier positive pole
RP2 = RectPole, rectifier negative pole
IP1 = InverterPole, inverter positive pole
IP2 = InverterPole, inverter negative pole
~~~

已观察到：

~~~text
Station/Main Freq = 50.0 Hz
~~~

候选值只是审计线索，不是批准绑定：

~~~text
Rectifier_AC.source3: Vm=382.8672 kV, Es=382.8672 kV, F0=50.0 Hz
Inverter_AC.source3: Vm=215.05 kV, Es=215.05 kV, F0=$(Freq)
RectCC.PI_AntiWindUp: Kp=0.5, Ti=0.05, MaxOut=3.054, MinOut=0.52, Out_Rst=1.57
InvCtrl.PI_AntiWindUp: Kp=0.5, Ti=0.01, MaxOut=1.92/1.57, MinOut=0.52
~~~

### 1.5 当前核心阻塞

参数目录中的逻辑参数绑定仍为 unreviewed，因此必须保持：

~~~text
topology_plan.executable = false
~~~

真实模板内部参数没有经过唯一定位、单位确认和读回验证之前，不得自动写入。

---

## 2. 总体架构

~~~text
用户请求
  ↓
参数解析与单位校验
  ↓
工程量推导与可行性检查
  ↓
模板只读审计
  ↓
参数绑定解析
  ↓
确定性计划和 plan_hash
  ↓ confirm=true + expected_plan_hash
隔离 staging 复制
  ↓
参数写入
  ↓
参数读回
  ↓
PSCAD load/save/compile/run
  ↓
输出 selector 解析
  ↓
结构、稳态、回流、模式验收
  ↓
published/PASS 或 failed/INCOMPLETE_ANALYSIS
~~~

任何阶段失败都不能跳过后续门槛。

### 2.1 源文件与 staging

源文件只能读取，禁止原地写入、覆盖保存、改名替换或写测试值。

所有写入只能进入：

~~~text
<PSCAD_MCP_WORKSPACE>\.pscad-mcp\lcc-builds\<build_id>\
~~~

最终项目先写 staging，验收通过后才允许发布。

---

## 3. 参数分层

### 3.1 A 类：项目级直接绑定

可直接绑定的前提：

- 唯一组件/Definition；
- 唯一参数名；
- 明确单位；
- 无未声明系统副作用；
- PSCAD 或 XML 可读回。

首批候选：

~~~text
frequency_hz
ac_voltage_kv（仅当 Vm/Es 关系已审核）
明确滤波支路的 filter_capacitance_uf
明确平波电抗器的 smoothing_reactor_mh
~~~

### 3.2 B 类：组件组参数

需要同步修改多个组件，每个组件仍需单独审核，例如：

~~~text
整流/逆变侧交流源
整流/逆变侧滤波器
整流/逆变侧平波电抗器
控制器限幅、初值和增益
~~~

必须用 binding group 表达：

~~~json
{
  "logical_parameter": "ac_voltage_kv",
  "binding_kind": "group",
  "members": [
    {"definition": "Rectifier_AC", "component_definition": "master:source3", "parameter": "Vm", "units": "kV"},
    {"definition": "Rectifier_AC", "component_definition": "master:source3", "parameter": "Es", "units": "kV"}
  ],
  "consistency_rule": "Vm == Es",
  "binding_status": "reviewed"
}
~~~

### 3.3 C 类：系统级参数

不能通过单字段替换得到可信结果：

~~~text
rated_power_mw
dc_voltage_kv
dc_current_ka
scr
escr
overlap_angle_deg
min_extinction_angle_deg
~~~

C 类必须有组合绑定、物理公式或资产来源、受影响组件清单、读回后再推导闭环和 PSCAD 编译/仿真证据。无法证明时保持 unresolved。

---

## 4. 绑定数据契约

### 4.1 单个参数绑定

~~~json
{
  "binding_id": "B-001",
  "logical_parameter": "frequency_hz",
  "topology": "bipolar",
  "role": "station",
  "definition_scope": "Station",
  "component_id": "1549322604",
  "component_definition": "HVDC_Bipolar_1000MW_500kV:Main",
  "discriminator": {"parameter": "Freq", "value": "50.0 Hz"},
  "parameter": "Freq",
  "attribute": "value",
  "units": "Hz",
  "selector": {
    "kind": "semantic_xml",
    "definition": "Station",
    "component_definition": "HVDC_Bipolar_1000MW_500kV:Main",
    "component_id": "1549322604",
    "parameter": "Freq"
  },
  "match_count_expected": 1,
  "binding_status": "reviewed",
  "source": "real-template-readonly-audit",
  "source_sha256": "159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993"
}
~~~

如果组件 ID 不稳定，必须补充 Definition、完整 definition、role/discriminator、参数名、关键端口/邻接和唯一匹配证据。

### 4.2 审核状态

~~~text
unreviewed → reviewed → readback_verified → live_verified
~~~

失败时回到 rejected 或保持原状态，不能直接改成 live_verified。

---

## 5. 代码文件边界

### 5.1 资产和绑定

~~~text
pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json
pscad_mcp/assets/lcc/lcc_parametric_bindings_v1.json
pscad_mcp/hvdc/builders/lcc/assets.py
pscad_mcp/hvdc/builders/lcc/template_audit.py
~~~

职责：保存审核绑定，校验源哈希、单位、角色、唯一性和状态。

### 5.2 计划和执行

~~~text
pscad_mcp/hvdc/builders/lcc/planner.py
pscad_mcp/hvdc/builders/lcc/parametric_service.py
pscad_mcp/hvdc/builders/lcc/parametric_executor.py
pscad_mcp/hvdc/builders/lcc/journal.py
~~~

职责：确定性 plan_hash、无副作用 planning、staging 原子写入、读回、lease 和 journal。

### 5.3 PSCAD 生命周期

~~~text
pscad_mcp/core/service.py
pscad_mcp/core/backend/base.py
pscad_mcp/core/backend/legacy.py
pscad_mcp/core/backend/modern.py
~~~

只允许应用层调用 PscadService；若服务不具备稳定参数读写能力，应扩展应用层 contract，不能在参数化服务中直接访问 vendor object。

### 5.4 验收和报告

~~~text
pscad_mcp/hvdc/builders/lcc/acceptance.py
pscad_mcp/hvdc/builders/lcc/validator.py
tests/test_lcc_parametric_acceptance_contract.py
tests/test_lcc_real_acceptance.py
tests/test_lcc_real_acceptance_contract.py
~~~

---

## 6. 分阶段执行计划

### Phase 0：环境和基线锁定

命令：

~~~powershell
Set-Location D:\pscad-mcp\.worktrees\codex-lcc-parametric-auto-modeling
& .\.venv\Scripts\python.exe --version
Get-FileHash -LiteralPath 'C:\Users\335\Desktop\moxing\HVDC_Bipolar_1000MW_500kV.pscx' -Algorithm SHA256
$env:PYTHONPATH = "$PWD\tests"
$files = Get-ChildItem tests -Filter 'test_lcc_*.py' | ForEach-Object FullName
& .\.venv\Scripts\python.exe -m pytest -q $files
~~~

通过条件：模板哈希仍为基线；非许可 LCC 回归通过；没有启动真实 PSCAD。

### Phase 1：只读生成真实模板证据

新增脚本：

~~~text
tools/audit_real_lcc_template.py
~~~

输出必须包含：

~~~json
{
  "source_path": "...",
  "source_sha256": "...",
  "definitions": [],
  "roles": {},
  "components": [],
  "candidate_parameters": [],
  "ambiguous_candidates": [],
  "status": "read_only_audit"
}
~~~

每个候选带 Definition、component definition、component id、parameter、原始值、单位和角色。禁止使用 XML 索引作为生产 selector。

### Phase 2：审核第一批直接绑定

首批：

~~~text
B-001 frequency_hz
B-002 ac_voltage_kv rectifier group
B-003 ac_voltage_kv inverter group
B-004 smoothing_reactor_mh rectifier
B-005 smoothing_reactor_mh inverter
B-006 filter_capacitance_uf rectifier
B-007 filter_capacitance_uf inverter
~~~

每项完成唯一定位、单位/范围确认、staging 测试写入、读回、源哈希不变和失败回滚。

在 B-001 至 B-007 完成前，禁止处理额定功率、直流电压、电流、SCR、ESCR。

### Phase 3：将审核绑定接入 catalog 和 plan

要求：

- 只有 binding_status=reviewed 的绑定可进入 executable plan；
- plan 显式包含 bindings；
- plan_hash 覆盖 request、derived、template hash、catalog hash、selector、units 和 target；
- 任一绑定或值改变都改变 plan_hash；
- executable=false 时 build 在 lease 前失败。

测试名称示例：

~~~python
def test_unreviewed_binding_blocks_before_lease(): ...
def test_reviewed_binding_changes_plan_hash(): ...
def test_binding_selector_must_match_once(): ...
def test_source_hash_change_is_plan_stale(): ...
~~~

### Phase 4：staging 写入和读回

严格顺序：

~~~text
校验 source hash
  ↓
校验 binding schema
  ↓
校验 selector 唯一匹配
  ↓
建立 staging parent
  ↓
复制 source 到临时文件
  ↓
写入参数
  ↓
原子替换 staging
  ↓
重新读取 staging
  ↓
逐项读回核对
~~~

写入前必须满足：

- 所有绑定验证通过；
- confirm=true；
- expected_plan_hash 匹配；
- final target 不存在；
- workspace lease 成功。

失败保留 staging/journal，释放 lease，不发布 final target。

### Phase 5：接入 PscadService

只能通过应用服务调用：

~~~python
await pscad_service.load_projects([staging_path])
await pscad_service.set_project_settings(project_name, settings)
await pscad_service.save_project_as(project_name, filename, folder)
await pscad_service.run_project(project_name)
await pscad_service.run_simulation_set(project_name, sim_set_name)
await pscad_service.read_output_file(output_path, ...)
~~~

若需要组件参数读写，先检查现有 base/legacy/modern contract，再扩展应用层。不能让 LegacyBackend 直接穿透。

状态至少包括：

~~~text
validated
staged
loaded
parameters_written
parameters_verified
compiled
simulated
outputs_verified
published
failed
interrupted
incomplete_analysis
~~~

每次迁移写 journal。

### Phase 6：系统级参数策略

以下参数必须用组合绑定和再推导：

~~~text
rated_power_mw
dc_voltage_kv
dc_current_ka
scr
escr
~~~

最低闭环：

~~~text
Pdc = Vdc × Idc
整流功率 ≈ 逆变功率 + 损耗
正极/负极功率和电流符合双极关系
控制器功率参考与请求一致
~~~

无法获得闭环证据时返回 LCC_PARAMETER_DERIVATION_FAILED 或 INCOMPLETE_ANALYSIS。

### Phase 7：控制角和运行方式

控制链必须确认：

~~~text
输入设定值 → 限幅器 → PI_AntiWindUp → AOR/AOI → 阀组控制 → Gamma/Alpha 输出
~~~

运行方式分别使用独立计划、staging 和报告：

~~~text
bipolar_run
monopolar_earth_return
monopolar_metallic_return
~~~

切换必须使用 EMTDC simulation time；无严格时间、精确 writable binding 或输出 selector 时，在写入前返回 LCC_SWITCHING_UNAVAILABLE。

### Phase 8：结构、编译、输出和稳态验收

每次 build 至少保存：

~~~json
{
  "source_template_sha256": "...",
  "catalog_sha256": "...",
  "blueprint_sha256": "...",
  "provenance_sha256": "...",
  "staging_project_sha256": "...",
  "final_project_sha256": "...",
  "compile": {"status": "PASS", "messages": []},
  "simulation": {"status": "PASS", "duration_s": 0.0},
  "output": {"path": "...", "sha256": "...", "channels": []},
  "derived": {},
  "modes": []
}
~~~

必需输出类别：

~~~text
正负极直流电压
正负极直流电流
整流/逆变有功功率
整流/逆变无功功率
Alpha/AOR
Gamma/AOI
Ielectrode
neutral/metallic/earth return current
~~~

缺 channel、样本、单位或 selector 时不能 PASS。

### Phase 9：真实许可环境验收

默认测试不得启动 PSCAD。真实验收必须显式设置：

~~~powershell
$env:PSCAD_MCP_LCC_ACCEPTANCE = '1'
$env:PSCAD_MCP_WORKSPACE = 'D:\pscad-mcp-live-workspace'
~~~

必须确认 licensed PSCAD 4.6.2、正确 backend、绝对 workspace、源哈希不变和进程清理边界。

真实流程：

1. 只读审计源；
2. plan；
3. 核对 plan hash；
4. confirm build；
5. 轮询终态；
6. 独立读取 journal/report；
7. 再算源哈希；
8. 核对每个模式；
9. 只有全部 gate PASS 才宣布 live accepted。

---

## 7. 错误矩阵

| 条件 | 错误码/状态 | 是否允许写入 |
|---|---|---:|
| source hash 改变 | LCC_PLAN_STALE | 否 |
| selector 0 匹配 | LCC_PARAMETER_BINDING_UNAVAILABLE | 否 |
| selector 多匹配 | LCC_TEMPLATE_AMBIGUOUS | 否 |
| 单位冲突 | LCC_PARAMETER_BINDING_UNAVAILABLE | 否 |
| topology 不匹配 | LCC_TEMPLATE_TOPOLOGY_MISMATCH | 否 |
| catalog hash 改变 | LCC_ASSET_MISMATCH | 否 |
| workspace 不合规 | LCC_LAYOUT_INVALID | 否 |
| final target 存在 | LCC_BUILD_CONFLICT | 否 |
| 无 PSCAD service | LCC_BUILD_UNAVAILABLE | 否 |
| 无严格仿真时钟 | LCC_SWITCHING_UNAVAILABLE | 否 |
| 编译失败 | LCC_BUILD_FAILED | staging 保留 |
| 输出缺失 | INCOMPLETE_ANALYSIS | 不发布 |
| 模式证据不足 | INCOMPLETE_ANALYSIS | 不发布 |

---

## 8. 测试计划

### 8.1 单元和绑定

~~~text
tests/test_lcc_parametric_models.py
tests/test_lcc_derivation.py
tests/test_lcc_parametric_blueprints.py
tests/test_lcc_template_audit.py
tests/test_lcc_template_bindings.py
tests/test_lcc_parametric_executor.py
tests/test_lcc_operating_modes.py
~~~

### 8.2 生命周期

~~~text
tests/test_lcc_parametric_service.py
tests/test_lcc_parametric_pscad_lifecycle.py
tests/test_lcc_builder_service.py
tests/test_lcc_executor.py
~~~

### 8.3 验收

~~~text
tests/test_lcc_acceptance.py
tests/test_lcc_parametric_acceptance_contract.py
tests/test_lcc_real_acceptance.py
tests/test_lcc_real_acceptance_contract.py
~~~

### 8.4 完整非许可验证

~~~powershell
Set-Location D:\pscad-mcp\.worktrees\codex-lcc-parametric-auto-modeling
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$files = Get-ChildItem tests -Filter 'test_lcc_*.py' | ForEach-Object FullName
& .\.venv\Scripts\python.exe -m pytest -q $files
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$files = Get-ChildItem tests -Filter 'test_hvdc_*.py' | ForEach-Object FullName
& .\.venv\Scripts\python.exe -m pytest -q $files
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
git diff --check
~~~

预期：测试通过，工具清单 83 83，未启动 PSCAD。

---

## 9. 证据目录

每次 build 使用独立 build_id：

~~~text
<workspace>/.pscad-mcp/lcc-builds/<build_id>/
├── journal.json
├── plan.json
├── source-manifest.json
├── binding-report.json
├── staging/<project>.pscx
├── outputs/<project>.out 或 <project>.psout
├── output-manifest.json
├── modes/bipolar_run.json
├── modes/monopolar_earth_return.json
├── modes/monopolar_metallic_return.json
└── acceptance-report.json
~~~

证据必须 JSON-safe、有大小上限、带哈希和时间戳、与 build_id 绑定，失败时保留，清理只针对本次 build。

---

## 10. 回滚

### 写入失败

- 保留 staging；
- 不创建 final target；
- journal 记录错误和已修改路径；
- 释放 lease；
- source 不变。

### 编译失败

- 保留 staging 和编译消息；
- 状态为 failed；
- 不发布。

### 输出失败

- 状态为 incomplete_analysis；
- 保存输出发现证据；
- 不把缺失输出当成零值；
- 不返回 PASS。

### 外部替换 final target

- 发布前后重新计算目标哈希；
- 保留外部文件；
- 本次候选移动到 build 专属 quarantine；
- journal 记录外部替换。

---

## 11. 绑定进度表

| Binding | 逻辑参数 | reviewed | readback_verified | live_verified |
|---|---|---:|---:|---:|
| B-001 | frequency_hz | PENDING | PENDING | PENDING |
| B-002 | ac_voltage_kv rectifier | PENDING | PENDING | PENDING |
| B-003 | ac_voltage_kv inverter | PENDING | PENDING | PENDING |
| B-004 | smoothing_reactor_mh rectifier | PENDING | PENDING | PENDING |
| B-005 | smoothing_reactor_mh inverter | PENDING | PENDING | PENDING |
| B-006 | filter_capacitance_uf rectifier | PENDING | PENDING | PENDING |
| B-007 | filter_capacitance_uf inverter | PENDING | PENDING | PENDING |
| B-008 | min_firing_angle_deg | PENDING | PENDING | PENDING |
| B-009 | max_firing_angle_deg | PENDING | PENDING | PENDING |
| B-010 | min_extinction_angle_deg | PENDING | PENDING | PENDING |
| B-011 | overlap_angle_deg | PENDING | PENDING | PENDING |
| B-012 | dc_voltage_kv | PENDING | PENDING | PENDING |
| B-013 | dc_current_ka | PENDING | PENDING | PENDING |
| B-014 | rated_power_mw | PENDING | PENDING | PENDING |
| B-015 | scr | PENDING | PENDING | PENDING |
| B-016 | escr | PENDING | PENDING | PENDING |

---

## 12. 最终完成定义

只有满足全部条件，才能描述为“真实 LCC 自动化已完成”：

- 所有声明参数有审核绑定或被明确标记为不支持；
- executable=true 只在绑定完整时出现；
- source template 哈希未改变；
- staging 参数写入可复现；
- 每个参数有读回证据；
- licensed PSCAD 4.6.2 成功加载和保存；
- 项目成功编译；
- 仿真成功运行；
- .out/.psout 存在且可读取；
- 必需 selector 唯一且单位正确；
- 正负极、功率、回流和角度验收通过；
- 每个声明运行方式独立验收通过；
- acceptance report 最终状态为 PASS；
- 非许可回归和安装检查通过；
- 文档区分实现、测试、安装和真实验收。

如果任何一项未完成，最终状态必须是：

~~~text
INCOMPLETE_ANALYSIS
~~~

而不是 PASS。

---

## 13. Codex 首个执行任务

先只实现 B-001 frequency_hz 的最小闭环：

~~~text
输入：真实模板基线 SHA-256
操作：staging 中 50 Hz → 55 Hz
输出：
  1. 唯一绑定记录；
  2. 读回值 55 Hz；
  3. source hash 不变；
  4. binding tests 通过；
  5. live_verified=false，除非 licensed PSCAD 已真实验证。
~~~

B-001 完成“审核、写入、读回、源保护”闭环后，才继续 B-002/B-003。

---

## 14. 阶段交付报告格式

~~~text
阶段：<phase name>
代码状态：implemented / not implemented
测试状态：test_verified / failed / skipped
安装状态：installed / not installed / not applicable
真实验收：live_accepted / not available / not run

已修改文件：
- ...

已生成证据：
- ...

验证命令：
- ...

结果：
- ...

剩余阻塞：
- ...
~~~

禁止只报告“完成”而不说明是否连接了 licensed PSCAD。

