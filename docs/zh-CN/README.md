# PSCAD MCP 中文使用与验收说明

本项目把 PSCAD 自动化封装为 53 个 MCP 工具，可供 Codex、GitHub Copilot CLI 等支持 stdio MCP 的客户端调用。项目采用双后端：

- PSCAD 4.6.x：`mhrc.automation`，当前已在本机 PSCAD 4.6.2 x64 许可环境做真实验收；
- PSCAD 5.x：`mhi.pscad` 3.1.x，当前完成契约测试，但由于本机没有 PSCAD 5.x，不能声称端到端真实验收通过；
- 结果文件：`mhi.psout` 1.3.x。

Legacy PSCAD 4.6.2 后端只支持启动新的 Automation 实例，不能附加到用户已打开的 GUI。`repair_connection` 仅在后端确认该进程属于 MCP 时退出旧实例；非自有连接只会断开，不会终止外部进程。

## PSCAD 4.6.2 已验证行为与限制

- 新建空算例和库使用随包分发、由 PSCAD 保存的模板；新建和另存会同时改写工程根身份及精确的工程自命名空间引用，并由 PSCAD 回读验证名称和类型。新目标会先尝试原生另存，未产生有效目标时回退；已有目标始终先保存当前操作副本，再通过原子替换生成目标。
- 工程设置只读取和写入所选工程的参数，不修改 PSCAD 应用全局设置。
- 运行命令非阻塞；PSCAD 4.6.2 的暂停和停止仍是应用级命令，即使工具参数中包含工程名。
- 本机随 PSCAD 4.6.2 提供的 Automation Library 会拒绝 `create-layer` 和 `add-to-layer`；对已有且结构有效的图层加入成员也会失败。因此禁用元件会明确返回 `PSCAD_COMMAND_FAILED`，不能声称专用禁用层已生效。
- 已连接批量删除会先校验目标、把导线相对顶点转换为绝对坐标、检查所需选区是否包含非目标对象、执行一次原生画布删除，再验证全部计划 ID 消失。无法形成安全选区时会在变更前返回 `CAPABILITY_UNAVAILABLE`。
- 空位搜索使用 PSCAD 的 18 单位网格和碰撞余量。实时画布 XML 缺少几何时，会用已保存工程 XML 和实时位置补齐；两者都没有尺寸时才采用保守的 36×36 矩形。

## 功能范围

服务器固定注册 53 个工具，分为以下七组：

- 应用与文档 7 个：连接、状态、修复、退出、文档同步/列出/读取；
- 工程与参数 12 个：加载、列出、运行、暂停、停止、运行状态、元件查询、参数读取/写入/校验、工程设置读取/写入；
- 输出 2 个：工程消息和 `.psout`/`.out` 结果读取；
- 仿真集 3 个：列出、运行、添加任务；
- 创建、保存与构建 7 个：新建算例/库、保存、另存、构建、全部构建、定义列表；
- 画布 12 个：元件、导线、母线、连接、端口连接、注释、图框、控制框、对象列表、空位搜索、批量删除；
- 元件操作 10 个：位置、旋转、镜像、克隆、端口、启用/禁用、删除。

## D 盘安装

以下命令假定仓库位于 `D:\pscad-mcp`：

```powershell
py -3 -m venv D:\pscad-mcp\.venv
& D:\pscad-mcp\.venv\Scripts\python.exe -m pip install --upgrade pip
& D:\pscad-mcp\.venv\Scripts\python.exe -m pip install -e "D:\pscad-mcp[windows]"
```

PSCAD 4.6.x 还需要安装与许可证配套的官方 Automation Library wheel。该 wheel 受厂商授权约束，本仓库不会复制或分发：

```powershell
& D:\pscad-mcp\.venv\Scripts\python.exe -m pip install `
  "D:\合法安装介质\mhrc_automation-1.2.4-py3-none-any.whl"
```

本地虚拟环境就是 `D:\pscad-mcp\.venv`：它是一套只供本项目使用的 Python、MCP 和 PSCAD Python 包，不会替换系统 Python，也不会修改 PSCAD 安装目录。删除虚拟环境只会删除这些项目依赖；仓库代码和 PSCAD 工程不受影响。

## 环境变量

启动相关变量有五个，另有一个工作区安全变量：

| 变量 | 示例 | 作用 |
|---|---|---|
| `PSCAD_MCP_BACKEND` | `legacy` | `auto`、`legacy` 或 `modern`；显式选择失败时不会静默换后端 |
| `PSCAD_MCP_VERSION` | `4.6.2` | 指定 PSCAD 版本 |
| `PSCAD_MCP_X64` | `true` | 选择 x64 或 x86 |
| `PSCAD_MCP_LAUNCH_TIMEOUT` | `30` | 启动超时秒数，必须为正整数 |
| `PSCAD_MCP_LEGACY_WHEEL` | `D:\...\wheel.whl` | 旧版依赖缺失时显示合法 wheel 位置提示 |
| `PSCAD_MCP_WORKSPACE` | `D:\PSCAD-Workspace` | 限制工程、保存和结果文件的可访问根目录 |

推荐 PSCAD 4.6.2 配置：

```powershell
$env:PSCAD_MCP_BACKEND = "legacy"
$env:PSCAD_MCP_VERSION = "4.6.2"
$env:PSCAD_MCP_X64 = "true"
$env:PSCAD_MCP_LAUNCH_TIMEOUT = "30"
$env:PSCAD_MCP_WORKSPACE = "D:\PSCAD-Workspace"
```

## Codex 配置

在 `%USERPROFILE%\.codex\config.toml` 中加入：

```toml
[mcp_servers.pscad]
command = 'D:\pscad-mcp\.venv\Scripts\python.exe'
args = ['-m', 'pscad_mcp.main']
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = 'legacy'
PSCAD_MCP_VERSION = '4.6.2'
PSCAD_MCP_X64 = 'true'
PSCAD_MCP_LAUNCH_TIMEOUT = '30'
PSCAD_MCP_WORKSPACE = 'D:\PSCAD-Workspace'
```

保存后新建 Codex 任务，使 MCP 配置重新加载。本轮代码验收不会自动改写全局 Codex 配置。

## 安全边界

- 设置 `PSCAD_MCP_WORKSPACE` 后，工作区外的工程和结果路径会被拒绝；
- 支持的工程/结果后缀采用允许列表，不接受任意文件；
- 退出 PSCAD、删除元件、覆盖保存等操作需要显式 `confirm=true`；
- 批量删除会先校验所有 ID，再开始删除，避免只删一半；
- 所有 PSCAD COM/RMI 操作由单线程执行器串行处理，超时后必须修复连接；
- MCP 工具不再暴露原始 PSCAD 代理，不能绕过服务层的安全检查；
- 真实验收只复制公共示例到 `D:\PSCAD-Workspace\acceptance` 的时间戳目录，不修改原始示例；
- 验收发现已有 PSCAD 进程时会拒绝运行，也不会用通配方式强制结束其他 PSCAD 进程。

## 自动化测试与真实验收

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

脚本运行 6 个原有实机测试和 8 个可靠性测试，每个变更场景使用独立的时间戳副本。覆盖只读、画布变更、构建、仿真与消息、运行控制、PSOUT，以及模板新建/重载、另存回退、工程设置、图层能力限制、连接删除、18 网格碰撞搜索和自有进程修复。脚本会打印副本路径、证据目录、启动的 PSCAD PID 和最终 `ACCEPTANCE_COMPLETE=PASS`；任何自有残留进程都会导致验收失败，但脚本不会强制关闭未确认的进程。

完整终验还应执行：

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall pscad_mcp
& .\.venv\Scripts\python.exe -m unittest discover tests -v
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
git diff --check
git status --short --branch
```

工具数量应输出 `53 53`。真实 PSCAD 5.x 必须在安装并运行对应版本后另做相同级别验收。

## 常见故障

- `DEPENDENCY_MISSING`：确认 4.6.x 的官方 `mhrc.automation` wheel 安装在本项目虚拟环境；
- 找不到指定版本：检查 `PSCAD_MCP_VERSION`、`PSCAD_MCP_X64` 与本机实际安装是否一致；
- MCP 能启动但工具超时：先用 `repair_connection`，不要并行向 PSCAD 发多条变更命令；
- 路径被拒绝：把工程复制到 `D:\PSCAD-Workspace` 下，或调整工作区根目录后重启 MCP；
- 删除、覆盖或退出被拒绝：确认目标无误后，重新调用并传入 `confirm=true`；
- Codex 看不到新配置：保存 `config.toml` 后新建任务或重启 Codex。
