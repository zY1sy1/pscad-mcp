# 参数扫描与约束寻优

配置 `PSCAD_MCP_WORKSPACE`，将工程及其依赖放在该工作区内的独立源目录。
`PSCAD_MCP_TOOL_PROFILE=full` 包含扫描工具；也可以选择 `sweep` 或 `core,sweep`。
计划与创建仅处理文件；运行使用每次尝试独立的 Legacy PSCAD 实例及 COM 执行器。

## 工具

| 工具 | 用途 |
| --- | --- |
| `plan_parameter_sweep` | 校验工况、依赖和输出选择器，计算计划与源哈希 |
| `create_parameter_sweep` | 使用计划哈希与 `confirm=true` 建立不可变基线 |
| `run_parameter_sweep` | 使用 `confirm=true` 启动后台串行任务，立即返回进度 |
| `get_parameter_sweep_status` | 查询持久化进度；`include_report=true` 包含分页结果 |
| `cancel_parameter_sweep` | 使用 `confirm=true` 请求停止本任务的运行并恢复参数 |
| `resume_parameter_sweep` | 使用 `confirm=true` 续跑未完成／取消工况；`retry_scenarios` 明确指定重试的失败工况 |
| `analyze_parameter_sweep` | 比较基准工况，按数值约束筛选并排序已评估工况 |

## 一次扫描

以下元件 ID、参数名、工程名和通道路径应替换为工程中实际存在的值。
先将该对象作为 `spec` 传给 `plan_parameter_sweep`：

```json
{
  "source_root": "source/rlc",
  "entry_file": "case.pscx",
  "project_name": "case",
  "scenarios": [
    {"name": "R1", "updates": [{"component_id": 7, "parameters": {"R": 1.0}}]},
    {"name": "R2", "updates": [{"component_id": 7, "parameters": {"R": 2.0}}]},
    {"name": "R3", "updates": [{"component_id": 7, "parameters": {"R": 3.0}}]}
  ],
  "outputs": [{"path": "case.gf46/case_01.out", "channels": ["Main/Voltage"]}],
  "baseline_scenario": "R1",
  "max_samples": 10000
}
```

再调用 `create_parameter_sweep(spec, expected_plan_hash=<返回的 plan_hash>, confirm=true)`。
使用返回的 `campaign_id` 调用 `run_parameter_sweep(..., confirm=true)`，随后查询进度。
同一工作区只运行一个扫描任务；其他交互工具保留自己的实例。
现有 PSCAD 进程按已有启动策略处理；独立并行实例需要显式配置
`PSCAD_MCP_LEGACY_EXISTING_POLICY=allow`，不会终止或接管外部进程。

参数必须是 JSON 标量。每次尝试在写入之前核实目标参数和合法范围，写入后回读，
结束时恢复原值并核实实例退出。普通工况失败会保留证据并继续；恢复或清理未核实会阻止后续工况。
源目录不接受链接、逃逸依赖或绝对文件引用；依赖应在已批准的源副本内使用相对路径。

`.out` 使用同名 `.inf` 和完整编号数据集，例如 `case_01.out`、`case_02.out`。
每个输出使用精确通道路径；`.psout` 沿用现有读取器。
工况最多 1000 个，每工况最多 128 个组件，输出最多 16 个文件、每文件 128 个通道。

## 寻优

下面示例在平均电压至少 10 的工况中，选择峰值绝对电压最小的已运行工况。
数值单位沿用原始通道，PSOUT 未提供单位时返回 `null`。

```json
{
  "campaign_id": "<返回的 campaign_id>",
  "objective": {
    "output_path": "case.gf46/case_01.out",
    "channel": "Main/Voltage",
    "statistic": "peak_abs",
    "direction": "minimize"
  },
  "constraints": [{
    "output_path": "case.gf46/case_01.out",
    "channel": "Main/Voltage",
    "statistic": "mean",
    "operator": ">=",
    "value": 10
  }],
  "limit": 20
}
```

可用统计量为 `min`、`max`、`mean`、`first`、`last`、`rms`、`peak_abs`。
约束支持 `<=`、`>=`、`==`。返回最优可行工况、排序、违反约束的原因及排除的失败工况。
`optimization_scope=evaluated_scenarios` 表示在已运行的显式工况集合中选择，
不会证明连续参数空间的全局最优。

统计声明 `statistics_scope=bounded_sample`，不将采样峰值冒充整段波形峰值。
OUT 采样在达到上限时均匀保留首尾点；PSOUT 使用现有读取器的采样方式。
基准比较给出绝对差和相对差；基准为零时相对差为 `null`，基准失败时明确标记不可比较。

## 恢复与证据

记录保存在工作区 `.pscad-mcp/sweeps/<campaign_id>`，包括基线、追加的尝试目录、
参数原值、运行 PID 与创建时间、输出副本、SHA-256、checkpoint 和可重建报告。
取消请求和 checkpoint 原子写入；操作系统文件锁阻止不同进程重复运行。
重启后使用 `resume_parameter_sweep` 保留已完成结果；失败重试建立新的 `attempt-N`。

Legacy 不支持已验证的旧运行重连。旧任务实例仍存活或所有权不明确时返回
`SWEEP_NEEDS_REVIEW`，不向该进程发送命令。只有实例已核实不存在后才能恢复。
源、基线、结果或输出证据被改动时拒绝使用；不会悄悄替换旧证据。

## 验证范围

该流程的离线／假后端检查覆盖隔离、故障继续、取消与续跑、重启、互斥、
恢复失败、输出新鲜度、证据不变性和独立数值计算。
许可实机验收必须显式提供 `PSCAD_MCP_ACCEPTANCE=1`、绝对工作区和经审核的扫描请求。
2026-10-13：`a2aaa33` 的 vdiv 三工况范围已通过真实 PSCAD 4.6.2／GFortran 4.2.1 验收。
基准与 R=2 各有 801 点、两条通道，故意无效参数被拒绝后后续工况继续；42 项检查通过。
另行核实 14 个基准比较项及峰值约束下的 RMS 排序。
取消、重启续跑及 PSOUT 仍只有离线覆盖；此结果不声明模型物理 accepted。
详见[验收与失败修复记录](acceptance/parameter-sweep-20261013.md)。
