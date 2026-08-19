# PSCAD MCP 中文使用与验收说明

本项目把 PSCAD 自动化封装为 60 个通用 MCP 工具，可供 Codex、GitHub Copilot CLI 等支持 stdio MCP 的客户端调用。项目采用双后端：

- PSCAD 4.6.x：`mhrc.automation`，当前已在本机 PSCAD 4.6.2 x64 许可环境做真实验收；
- PSCAD 5.x：`mhi.pscad` 3.1.x，当前完成契约测试，但由于本机没有 PSCAD 5.x，不能声称端到端真实验收通过；
- 结果文件：`mhi.psout` 1.3.x。

完整工具库存为 73 = 60 个通用工具 + 10 个 HVDC 工具 + 3 个学习工具；原有 60 个通用工具的名称和默认返回形状保持不变。

Legacy PSCAD 4.6.2 后端只支持启动新的受管 Automation 实例，不能附加到用户普通方式打开的 GUI。受管窗口默认可见；默认检测到已有 PSCAD 进程时会在启动前返回 `EXTERNAL_PSCAD_PRESENT`。`repair_connection` 使用连接时缓存的进程归属：自有实例会先正常退出，外部进程不会被终止。

版本变更记录见 [CHANGELOG.md](../../CHANGELOG.md)，可移植的 stdio 配置模板见 [config.example.toml](../../config.example.toml)。

## PSCAD 4.6.2 已验证行为与限制

- 新建空算例和库使用随包分发、由 PSCAD 保存的模板；新建和另存会同时改写工程根身份及精确的工程自命名空间引用，并由 PSCAD 回读验证名称和类型。新目标会先尝试原生另存，未产生有效目标时回退；已有目标始终先保存当前操作副本，再通过原子替换生成目标。
- 工程设置只读取和写入所选工程的参数，不修改 PSCAD 应用全局设置。
- 运行命令非阻塞；PSCAD 4.6.2 的暂停和停止仍是应用级厂商命令，因此只有目标是唯一活动算例时才会发送。目标未活动返回 `RUN_NOT_ACTIVE`；存在第二个活动算例时返回 `RUN_CONTROL_SCOPE_CONFLICT` 且不发送命令。停止必须回读到终止状态才报告成功；legacy 状态接口在 GUI 已明确显示 `Paused.` 时仍返回 `running`，因此成功分派 Pause 后由后端以 `command-tracked` 来源报告 `paused`，恢复、停止、终止或断开时立即清除。
- 本机随 PSCAD 4.6.2 提供的 Automation Library 会拒绝 `create-layer` 和 `add-to-layer`；对已有且结构有效的图层加入成员也会失败。因此禁用元件会明确返回 `PSCAD_COMMAND_FAILED`，不能声称专用禁用层已生效。
- 已连接批量删除会先校验目标、把导线相对顶点转换为绝对坐标、检查所需选区是否包含非目标对象、执行一次原生画布删除，再验证全部计划 ID 消失。无法形成安全选区时会在变更前返回 `CAPABILITY_UNAVAILABLE`。
- 空位搜索使用 PSCAD 的 18 单位网格和碰撞余量。实时画布 XML 缺少几何时，会用已保存工程 XML 和实时位置补齐；两者都没有尺寸时才采用保守的 36×36 矩形。

## 功能范围

服务器固定注册 60 个工具，分为以下七组：

- 应用与文档 7 个：连接、状态、修复、退出、文档同步/列出/读取；
- 工程与参数 12 个：加载、列出、运行、暂停、停止、运行状态、元件查询、参数读取/写入/校验、工程设置读取/写入；
- 输出 2 个：工程消息和 `.psout`/`.out` 结果读取；
- 仿真集 10 个：列出、创建、删除、详情、任务列表、运行、添加任务、移除任务、任务参数读取、任务参数写入；仿真集是工作区级资源，不属于单个工程；
- 创建、保存与构建 7 个：新建算例/库、保存、另存、构建、全部构建、定义列表；
- 画布 12 个：元件、导线、母线、连接、端口连接、注释、图框、控制框、对象列表、空位搜索、批量删除；
- 元件操作 10 个：位置、旋转、镜像、克隆、端口、启用/禁用、删除。
- 静默学习 3 个：`record_goal_failure`、`review_improvement_backlog`、`clear_learning_history`。

## Windows 安装

以下命令从仓库根目录执行，并通过变量保留路径可移植性：

```powershell
$repoRoot = (Get-Location).Path
$venvPath = Join-Path $repoRoot ".venv"
py -3 -m venv $venvPath
& (Join-Path $venvPath "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $venvPath "Scripts\python.exe") -m pip install -e "$repoRoot[windows]"
```

PSCAD 4.6.x 还需要安装与许可证配套的官方 Automation Library wheel。该 wheel 受厂商授权约束，本仓库不会复制或分发：

```powershell
& (Join-Path $venvPath "Scripts\python.exe") -m pip install `
  "C:\合法安装介质\mhrc_automation-1.2.4-py3-none-any.whl"
```

本地虚拟环境就是仓库下的 `.venv`：它是一套只供本项目使用的 Python、MCP 和 PSCAD Python 包，不会替换系统 Python，也不会修改 PSCAD 安装目录。删除虚拟环境只会删除这些项目依赖；仓库代码和 PSCAD 工程不受影响。

## 环境变量

启动相关变量有七个，另有两个工作区安全变量：

| 变量 | 示例 | 作用 |
|---|---|---|
| `PSCAD_MCP_BACKEND` | `legacy` | `auto`、`legacy` 或 `modern`；显式选择失败时不会静默换后端 |
| `PSCAD_MCP_VERSION` | `4.6.2` | 指定 PSCAD 版本 |
| `PSCAD_MCP_X64` | `true` | 选择 x64 或 x86 |
| `PSCAD_MCP_LAUNCH_TIMEOUT` | `30` | 启动超时秒数，必须为正整数 |
| `PSCAD_MCP_LEGACY_WHEEL` | `D:\...\wheel.whl` | 旧版依赖缺失时显示合法 wheel 位置提示 |
| `PSCAD_MCP_LEGACY_MINIMIZE` | `false` | `false` 默认显示受管窗口；`true` 显式最小化 |
| `PSCAD_MCP_LEGACY_EXISTING_POLICY` | `reject` | `reject` 拒绝已有外部 PSCAD；`allow` 只允许另启受管实例，并不接管外部 GUI |
| `PSCAD_MCP_WORKSPACE` | `D:\PSCAD-Workspace` | 限制工程、保存和结果文件的可访问根目录 |
| `PSCAD_MCP_ALLOW_UNSCOPED_PATHS` | `false` | 仅受控开发环境允许未配置工作区时访问路径 |
| `PSCAD_MCP_LEARNING_ENABLED` | `true` | 默认启用本地标量元数据学习；接受 `1/true/yes/on` 和 `0/false/no/off` |
| `PSCAD_MCP_LEARNING_DB` | 可选绝对路径 | 覆盖本地 SQLite 路径，不记录工具参数或结果 |
| `PSCAD_MCP_LEARNING_BACKLOG` | 可选绝对路径 | 覆盖生成的 `improvement-backlog.md` 路径 |
| `PSCAD_MCP_LEARNING_RETENTION_DAYS` | `90` | 保留天数，范围 `1..3650` |
| `PSCAD_MCP_LEARNING_MAX_EVENTS` | `20000` | 最大事件数，范围 `100..1000000` |

推荐 PSCAD 4.6.2 配置：

```powershell
$env:PSCAD_MCP_BACKEND = "legacy"
$env:PSCAD_MCP_VERSION = "4.6.2"
$env:PSCAD_MCP_X64 = "true"
$env:PSCAD_MCP_LAUNCH_TIMEOUT = "30"
$env:PSCAD_MCP_LEGACY_MINIMIZE = "false"
$env:PSCAD_MCP_LEGACY_EXISTING_POLICY = "reject"
$env:PSCAD_MCP_WORKSPACE = "D:\PSCAD-Workspace"
$env:PSCAD_MCP_ALLOW_UNSCOPED_PATHS = "false"
$env:PSCAD_MCP_LEARNING_ENABLED = "true"
$env:PSCAD_MCP_LEARNING_RETENTION_DAYS = "90"
$env:PSCAD_MCP_LEARNING_MAX_EVENTS = "20000"
```

## Codex 配置

仓库提供了可移植模板 [`config.example.toml`](../../config.example.toml)。把其中的 `mcp_servers.pscad` 区块复制到 `%USERPROFILE%\.codex\config.toml`，再把 Python 解释器和工作区路径替换为本机路径：

```toml
[mcp_servers.pscad]
type = 'stdio'
command = 'C:/path/to/pscad-mcp/.venv/Scripts/python.exe'
args = ['-m', 'pscad_mcp.main']
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = 'legacy'
PSCAD_MCP_VERSION = '4.6.2'
PSCAD_MCP_X64 = 'true'
PSCAD_MCP_LAUNCH_TIMEOUT = '30'
PSCAD_MCP_LEGACY_MINIMIZE = 'false'
PSCAD_MCP_LEGACY_EXISTING_POLICY = 'reject'
PSCAD_MCP_WORKSPACE = 'C:/path/to/PSCAD-Workspace'
PSCAD_MCP_ALLOW_UNSCOPED_PATHS = 'false'
PSCAD_MCP_LEARNING_ENABLED = 'true'
PSCAD_MCP_LEARNING_RETENTION_DAYS = '90'
PSCAD_MCP_LEARNING_MAX_EVENTS = '20000'
```

保存后新建 Codex 任务，使 MCP 配置重新加载。普通安装流程不会自动改写全局 Codex 配置。

## 静默本地学习

学习默认开启，只保存本机的有界标量元数据。不会持久化参数、结果、工程路径、提示词、异常文本、错误详情或 traceback，也不会上传遥测或训练模型。

Windows 默认状态目录为 `%LOCALAPPDATA%\pscad-mcp`，其中的 `learning.sqlite3` 是证据源，`improvement-backlog.md` 是生成的 Markdown 投影。该文件会原子替换，手工编辑会被覆盖；仓库内的 `.pscad-mcp/learning/` 已加入忽略规则。

正常成功操作保持静默。普通失败证据等待后续审查；只有定义明确的正确性、部分变更或恢复风险才可能产生一次简短 critical 提醒，原有运行或安全错误仍会显示。目标失败后，宿主界面仍可能显示折叠的 `record_goal_failure` 审计条目，但日常用户可见 prose 仍保持静默。

三个学习工具是 `record_goal_failure`、`review_improvement_backlog` 和 `clear_learning_history`。清除历史必须显式确认，并会重新生成只有标题的 backlog。

每周一 `09:00 Asia/Shanghai` 的 Codex desktop heartbeat 必须单独创建；MCP server 和 installer 不会隐式创建它。定时工作要求机器开机、Codex desktop app 正在运行、仓库仍可访问且 MCP server 在该时刻可用。

## 安全边界

仿真集管理工具包括 `create_simulation_set`、`remove_simulation_set`、
`list_simulation_set_tasks`、`remove_tasks_from_set`、
`get_simulation_task_parameters`、`set_simulation_task_parameters` 和
`get_simulation_set_details`。删除仿真集或移除任务必须显式传入
`confirm=true`。旧的 `project_name` 参数仅为兼容保留，不用于限定工作区级
仿真集。PSCAD 4.6.2 可写任务字段只有 `controlgroup`、`volley` 和
`affinity`；`namespace` 只读。

- 必须设置 `PSCAD_MCP_WORKSPACE`；未设置时文件工具返回
  `WORKSPACE_NOT_CONFIGURED`，不会访问未受限路径；
- 只有在受控开发环境中才设置 `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=true`；
- 设置或修改工作区变量后必须重启 MCP 连接；
- 设置 `PSCAD_MCP_WORKSPACE` 后，工作区外的工程和结果路径会被拒绝；
- 支持的工程/结果后缀采用允许列表，不接受任意文件；
- 退出 PSCAD、删除元件、覆盖保存等操作需要显式 `confirm=true`；
- 批量删除会先校验所有 ID，再开始删除，避免只删一半；
- 所有 PSCAD COM/RMI 操作由单线程执行器串行处理，超时后必须修复连接；
- MCP 工具不再暴露原始 PSCAD 代理，不能绕过服务层的安全检查；
- 所有工具错误统一返回 `code`、`details`、`retryable` 和 `suggested_action`，不会在 MCP 边界丢失后端诊断；
- 真实验收只复制公共示例到 `D:\PSCAD-Workspace\acceptance` 的时间戳目录，不修改原始示例；
- 验收发现已有 PSCAD 进程时会拒绝运行，也不会用通配方式强制结束其他 PSCAD 进程。

## 自动化测试与真实验收

HVDC 事件中的 `time_s` 始终表示 EMTDC 仿真时间，不使用墙钟时间兜底。
没有经过验证的原生调度或仿真时钟轮询能力时，事件会安全拒绝。内置
`hvdc_breaker_difforder` 是 v2 配置，包含七个带单位的明确只读结果选择器，
故意不包含可写断路器或故障绑定；用户配置必须提供经过确认且限定工程的命令
绑定。`PlotType="OUT"` 只允许在已确认的派生工程中修正。

内置选择器为：`dc_voltage_breaker`（`kV`）、`dc_current_breaker`（`kA`）、
`breaker_command_observed`（二值），以及整流侧/逆变侧两极的四个直流电压选择器
（`pu`）。路径和 legacy call ID 均按明确选择器解析；写操作不会根据别名推断。
当 v2 场景请求指标时，预检还要求后端提供输出通道元数据，并在任何参数写入前
核对 path、call ID 和单位；无法检查时返回结构化安全拒绝。

VSC 两电平和 MMC 通用 Profile 现在提供显式测量选择器和单位感知语义，覆盖
直流量、P/Q、PLL/dq、桥臂电流、子模块电容电压和环流。通用 Profile 在注册
项目级结果选择器或命令绑定前仍保持只读。

基于轮询的 EMTDC 控制现在使用有界轮询间隔，并检测仿真时钟停滞。定时事件带有
稳定 ID，重复 ID 会在分发前被拒绝。Legacy 和 Modern 后端只有在加载工程显式
提供对应能力时才会声明定时调度、仿真时钟或输出通道能力，否则安全失败。

真实验收必须显式设置 `PSCAD_MCP_ACCEPTANCE=1`、
`PSCAD_MCP_HVDC_SOURCE`、`PSCAD_MCP_HVDC_LIBRARY` 和
`PSCAD_MCP_WORKSPACE` 四个环境变量：

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py -q -s
```

验收会把工程和库复制到带时间戳的工作区并核对源文件哈希；若没有严格定时或
唯一命令绑定，应在写参数前得到 `HVDC_TIMED_CONTROL_UNAVAILABLE` 或
`HVDC_MAPPING_MISSING` 的安全拒绝。

日常测试不会启动 PSCAD：

```powershell
Set-Location D:\pscad-mcp
& .\.venv\Scripts\python.exe -m unittest discover tests -v
```

真实 PSCAD 4.6.2 x64 验收：

```powershell
Set-Location D:\pscad-mcp
& .\scripts\run_legacy_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\acceptance' `
  -Version '4.6.2' -X64
```

脚本运行 6 个原有实机测试和 9 个可靠性测试，每个变更场景使用独立的时间戳副本。覆盖只读、画布变更、构建、仿真与消息、运行控制、PSOUT，以及模板新建/重载、另存回退、工程设置、图层能力限制、连接删除、18 网格碰撞搜索、自有进程修复和仿真集生命周期。脚本会打印副本路径、证据目录、启动的 PSCAD PID 和最终 `ACCEPTANCE_COMPLETE=PASS`；任何自有残留进程都会导致验收失败，但脚本不会强制关闭未确认的进程。

完整终验还应执行：

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall pscad_mcp
& .\.venv\Scripts\python.exe -m unittest discover tests -v
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
git diff --check
git status --short --branch
```

工具数量应输出 `73 73`，即 `73 = 60 + 10 + 3`；其中稳定的 generic 合约仍是 60 个工具。真实 PSCAD 5.x 必须在安装并运行对应版本后另做相同级别验收。

## 常见故障

- `DEPENDENCY_MISSING`：确认 4.6.x 的官方 `mhrc.automation` wheel 安装在本项目虚拟环境；
- 找不到指定版本：检查 `PSCAD_MCP_VERSION`、`PSCAD_MCP_X64` 与本机实际安装是否一致；
- MCP 能启动但工具超时：先查看 `get_pscad_status.executor` 中的 `healthy`、`last_operation`、`last_error`、`last_timeout_seconds`、`reset_generation` 和 `previous_worker_retiring`，再调用 `repair_connection`；不要并行向 PSCAD 发多条变更命令；
- `REPAIR_CLEANUP_FAILED`：MCP 自己启动的 PSCAD 在执行器重建后仍无法正常退出。修复流程不会继续启动第二个实例；请手动关闭该 PSCAD 进程，再调用 `repair_connection`；
- `EXTERNAL_PSCAD_PRESENT`：普通打开的 PSCAD 4.6.2 不能被 legacy API 事后接管；关闭该 GUI 后让 MCP 启动，或明确设置 `PSCAD_MCP_LEGACY_EXISTING_POLICY=allow` 另启受管实例；
- `RUN_CONTROL_SCOPE_CONFLICT`：还有其他活动算例；先停止或等待其他算例结束，再对唯一活动目标执行暂停/停止；
- `RUN_NOT_ACTIVE`：目标当前不是启动、构建、运行或暂停状态；先运行目标并等待进入活动状态；
- 路径被拒绝：配置正确的 `PSCAD_MCP_WORKSPACE` 后重启 MCP；如果看到
  `WORKSPACE_NOT_CONFIGURED`，不要反复重试文件工具；
- 删除、覆盖或退出被拒绝：确认目标无误后，重新调用并传入 `confirm=true`；
- Codex 看不到新配置：保存 `config.toml` 后新建任务或重启 Codex。

## 可选工作流扩展

现有 60 个工具的名称和默认返回形状保持不变，同时支持以下可选参数：

- `get_project_output(project_name, structured=true)` 返回带有
  `severity`、`text` 和可选 `source` 的 JSON 消息记录；默认仍返回文本。
- `read_output_file(file_path, channel="Root/Voltage/PGB:Data",
  summary_only=true)` 按规范化通道路径筛选，并只返回有界统计量
  （`count`、`min`、`max`、`mean`、`first`、`last`），不返回原始采样值。
  无法读取的通道会记录在 `warnings` 和 `skipped_channels` 中。
- `get_project_settings` 和 `set_project_settings` 支持
  `mode="parameter_grid"`，动作仅限 `view_project`、`load`、`save`，文件后缀
  必须为 `.csv`。现代后端转发到厂商参数网格代理；PSCAD 4.6.2 legacy
  自动化不支持时会明确返回 `CAPABILITY_UNAVAILABLE`。
