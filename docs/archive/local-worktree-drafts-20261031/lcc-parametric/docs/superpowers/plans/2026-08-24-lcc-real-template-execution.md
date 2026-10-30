# LCC Real Template Execution Continuation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已完成的参数化 LCC 推导和只读模板审计，推进到可审计的真实 PSCX 参数写入、PSCAD 编译/仿真和逐模式验收，同时保持未具备证据时 fail-closed。

**Current baseline:** 分支 `codex/lcc-parametric-auto-modeling` 已通过 `490 passed, 4 skipped`。真实模板 `C:\Users\335\Desktop\moxing\HVDC_Bipolar_1000MW_500kV.pscx` 可审计且哈希为 `159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993`；当前 `topology_plan.executable=false`，因为所有模板参数绑定仍是 `unreviewed`。

**Architecture:** 先建立“逻辑参数→精确模板节点/PSCAD 参数”的审核目录，再由执行器在所有绑定唯一解析后复制并修改 staging PSCX。只有真实 PSCAD 服务、编译结果、波形输出和完整验收证据齐备时才允许 `published/PASS`。

---

### Task 1: 固化真实模板参数绑定目录

**Files:**
- Modify: `pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json`
- Modify: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/template_audit.py`
- Create: `tests/fixtures/lcc_parametric/real_binding_template.pscx`
- Create: `tests/test_lcc_template_bindings.py`

- [ ] **Step 1: 从真实模板建立只读证据表。**
  记录 `Main` 中 `RP1/RP2/IP1/IP2` 的 instance id、definition，以及 `RectPole/InverterPole` 内部 `g6p200` 和 `xfmr-3p2w` 的实际参数表；不修改原始 PSCX。

- [ ] **Step 2: 先写失败测试。**
  测试每个绑定必须包含 `logical_parameter`、`role`、`selector`、`attribute`、`units`、`binding_status="reviewed"`；缺失、重复、多个 XML 匹配或单位不一致时返回 `LCC_PARAMETER_BINDING_UNAVAILABLE`。

- [ ] **Step 3: 更新目录和资源校验。**
  仅登记真实观察到的稳定路径；禁止通过组件名称模糊匹配生成路径。资源校验必须拒绝未审核绑定和重复 selector。

- [ ] **Step 4: 运行绑定测试。**
  `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_template_bindings.py tests/test_lcc_template_audit.py`

- [ ] **Step 5: 提交。**
  `git commit -am "feat: approve audited LCC template bindings"`

**停止条件:** 如果真实模板内部参数没有稳定、唯一、可复现的 selector，就停在 `executable=false`，改走 PSCAD API 的显式组件参数读写审核，不得猜路径。

### Task 2: 把审核绑定接入参数化执行计划

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_executor.py`
- Test: `tests/test_lcc_parametric_service.py`
- Test: `tests/test_lcc_parametric_executor.py`

- [ ] **Step 1: 写执行前置测试。**
  断言审核绑定完整时 `topology_plan.executable is True`，staging 修改只发生在 binding validation 之后；绑定不完整时不会获取 lease、不会调用 `load_projects`。

- [ ] **Step 2: 生成确定性 bindings。**
  由 catalog 的审核声明生成计划中的 `bindings`，每项携带派生值、单位、selector 和预期匹配数；计划哈希必须随 selector、单位或派生值变化而变化。

- [ ] **Step 3: 接入执行器。**
  `execute_parametric_template()` 先验证 source hash、bindings 和 XML 匹配，再原子写入 staging；记录 `source_sha256`、`staging_sha256`、`modified_paths` 和每项读回值。

- [ ] **Step 4: 运行测试。**
  `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_service.py tests/test_lcc_parametric_executor.py`

- [ ] **Step 5: 提交。**
  `git commit -am "feat: connect reviewed bindings to LCC build plans"`

### Task 3: 接入真实 PSCAD 项目生命周期

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_executor.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- Create: `tests/test_lcc_parametric_pscad_lifecycle.py`

- [ ] **Step 1: 写 fake-backend 生命周期测试。**
  对 `load_projects`、项目设置写入、保存 staging、编译/运行轮询、输出文件发现分别记录调用顺序；验证任何 binding 错误都发生在首次 PSCAD 调用之前。

- [ ] **Step 2: 实现最小真实边界。**
  仅调用现有 `PscadService` API：`load_projects`、`set_project_settings`、`save_project_as`、`run_project` 或 `run_simulation_set`、`read_output_file`。不直接使用 `LegacyBackend` 穿透应用服务边界。

- [ ] **Step 3: 增加编译和失败状态。**
  编译失败、运行超时、输出缺失分别记录稳定错误码；staging 证据保留，final target 不提前创建，lease 在所有终态释放。

- [ ] **Step 4: 运行测试。**
  `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_pscad_lifecycle.py tests/test_lcc_parametric_service.py tests/test_lcc_executor.py`

- [ ] **Step 5: 提交。**
  `git commit -am "feat: execute parameterized LCC through PSCAD service"`

**停止条件:** 没有 licensed PSCAD 4.6.2 或没有可证明的 compile/run 状态时，只允许返回 `LCC_BUILD_UNAVAILABLE` 或 `INCOMPLETE_ANALYSIS`。

### Task 4: 完成 LCC 结构、稳态和输出验收

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/acceptance.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/validator.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_executor.py`
- Create: `tests/test_lcc_parametric_acceptance_contract.py`

- [ ] **Step 1: 写验收契约测试。**
  要求 compile evidence、`.out/.psout` 文件哈希、精确 channel selector、单位、Gamma/Alpha、正负极电压电流、neutral/return current 和派生参数报告全部存在；缺一项都不能 `PASS`。

- [ ] **Step 2: 实现模式无关稳态门。**
  复用现有 output reader 和 selector 校验，增加极间不平衡、回流闭合、额定功率一致性、角度区间和单位检查；缺采样或未知单位返回 `INCOMPLETE_ANALYSIS`。

- [ ] **Step 3: 保存有界证据。**
  journal 和 acceptance report 只保存路径、哈希、统计量、selector 证据和错误摘要，不保存无限制原始波形或用户秘密。

- [ ] **Step 4: 运行测试。**
  `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_acceptance_contract.py tests/test_lcc_acceptance.py`

- [ ] **Step 5: 提交。**
  `git commit -am "feat: add parameterized LCC acceptance gates"`

### Task 5: 接入运行方式副本和 EMTDC 时间切换

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/modes.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- Modify: `pscad_mcp/hvdc/scenarios.py`
- Test: `tests/test_lcc_operating_modes.py`

- [ ] **Step 1: 写模式隔离测试。**
  断言 `bipolar_run`、`monopolar_earth_return`、`monopolar_metallic_return` 使用独立计划/证据目录，任一模式失败不会污染其它模式。

- [ ] **Step 2: 写切换前置失败测试。**
  无严格 simulation-clock、无精确 writable binding、无所需输出 selector 时，在任何写入前返回 `LCC_SWITCHING_UNAVAILABLE`。

- [ ] **Step 3: 接入时间调度。**
  所有 `time_s` 通过 EMTDC-time provider；禁止 wall-clock 时间和未经授权的 alias 命令；每次切换记录 requested/observed time。

- [ ] **Step 4: 添加模式验收。**
  每个模式单独验证 return path、波形、恢复时间和模式一致性，汇总报告只有全部声明模式通过时才允许 `PASS`。

- [ ] **Step 5: 运行测试并提交。**
  `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_operating_modes.py tests/test_hvdc_timing.py tests/test_hvdc_scenario_containment.py`
  `git commit -am "feat: execute and validate LCC operating modes"`

### Task 6: 进行真实验收和交付核对

**Files:**
- Modify: `tests/test_lcc_real_acceptance.py`
- Modify: `tests/test_lcc_real_acceptance_contract.py`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 默认非许可环境验证。**
  `pip check`、`compileall`、全部 `tests/test_lcc_*.py` 与 `tests/test_hvdc_*.py`、工具清单 `83/83`、`git diff --check` 全部通过；默认不得启动 PSCAD。

- [ ] **Step 2: 只在明确启用时运行许可验收。**
  设置 `PSCAD_MCP_LCC_ACCEPTANCE=1`、绝对 `PSCAD_MCP_WORKSPACE`、PSCAD 4.6.2 backend 和已批准模板路径；复制到时间戳隔离目录，不修改源模板。

- [ ] **Step 3: 独立核对报告。**
  报告必须包含 source/template/catalog/provenance/final project 哈希、compile 状态、输出文件、每个模式的 selector 和 acceptance 结果；只有最终状态为 `PASS` 才能称为真实验收完成。

- [ ] **Step 4: 更新文档并提交。**
  明确区分“已实现”“测试通过”“已安装”“真实 PSCAD 验收”；若许可运行不可用，保留 `INCOMPLETE_ANALYSIS` 证据，不写成完成。

---

## 最终完成定义

- [ ] 参数推导和单位/可行性检查通过。
- [ ] 真实模板绑定经过审核且计划 `executable=true`。
- [ ] 源模板哈希不变，staging 修改可复现并有读回证据。
- [ ] PSCAD 编译、仿真和输出 selector 均有真实证据。
- [ ] 所有声明运行方式分别通过结构、稳态、回流和切换验收。
- [ ] 非许可回归全部通过；许可验收报告最终为 `PASS`，否则明确标记为未完成。
