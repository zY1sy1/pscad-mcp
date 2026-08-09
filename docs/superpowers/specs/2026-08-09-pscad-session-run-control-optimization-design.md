# PSCAD 会话与运行控制优化设计

## 目标

在不修改元件禁用能力的前提下，提升 PSCAD 4.6.2 的会话可见性、重复使用安全性和暂停/停止命令的作用域可靠性；同时完成当前机器的 Codex MCP 注册与一次真实冒烟验收。

## 背景与边界

mhrc.automation 1.2.4 的 legacy 后端在启动时创建回连 socket，并以 /startup:au 参数启动 PSCAD。它没有可验证的事后接管普通 GUI 接口。PSCAD 4.6.2 的 pause/stop 命令也是应用级命令，会影响所有正在运行的工程。元件禁用仍保持现有明确失败行为，本次不改动相关代码或契约。

本设计不使用窗口坐标点击、强制结束 EMTDC/PSCAD 进程或未验证的工程文件篡改来制造“成功”。

## 设计

### 1. 受管 legacy 会话

- legacy 启动默认显示 PSCAD 窗口，避免后台启动后用户无法观察实际状态；通过 PSCAD_MCP_LEGACY_MINIMIZE 保留显式最小化选项。
- 启动前检查同版本 PSCAD 进程。默认发现外部进程时返回结构化 EXTERNAL_PSCAD_PRESENT，列出有限的 PID/可执行文件信息并阻止重复启动；开发者可通过显式环境变量覆盖为允许并行启动。
- 成功启动后保存受管进程 PID/可执行文件信息到后端内存状态，heartbeat 和 repair 使用该归属信息；disconnect 不会关闭外部进程，quit 只关闭 MCP 自己启动的进程。
- 不声称接管任意手动启动的普通 GUI。对不可接管场景返回可操作提示，建议关闭该进程后通过 MCP 受管启动。

### 2. 运行控制作用域

- legacy pause/stop 执行前枚举已加载工程并读取各自 run status。
- 目标工程不是唯一处于 building/running/paused 的工程时，返回结构化 RUN_CONTROL_SCOPE_CONFLICT，不发送全局命令。
- 目标工程未运行时返回结构化 RUN_NOT_ACTIVE，避免把空操作报告为成功。
- 作用域检查通过后才调用现有 PSCAD 应用级命令，并在有限超时内回读目标工程状态；回读不符合预期时返回 POSTCONDITION_FAILED。
- legacy 保留 scope=single-active-project 的诊断信息；现代后端优先使用厂商提供的单工程停止入口（若当前版本存在），否则沿用项目代理并报告实际作用域。
- 不改变已有 60 个 MCP 工具名称和默认输入形状；新增信息只进入结构化错误详情和状态诊断。

### 2.1 实机修订（2026-08-10）

PSCAD 4.6.2 GUI 在官方 Pause 命令后明确显示 `Paused.`，但 legacy `get-run-status` 持续返回 `running`。因此暂停不能伪称由厂商状态接口回读验证：后端只在目标为唯一活动工程、目标已进入 `running` 且官方 Pause 命令成功分派后，以 `command-tracked` 来源报告 `paused`；恢复、停止、终止或断开立即清除该状态。停止仍要求厂商状态回读到终止状态。

### 3. Codex 注册与冒烟

- 在 %USERPROFILE%\\.codex\\config.toml 增加 mcp_servers.pscad，指向仓库 .venv\\Scripts\\python.exe -m pscad_mcp.main，固定 legacy 4.6.2 x64、工作区和安全路径策略。
- 配置写入后验证 TOML 区块、服务器启动和 60 工具清单；提示新建 Codex 任务以加载新 MCP 进程。
- 实机冒烟只操作 D:\\PSCAD-Workspace\\acceptance 下的时间戳副本：启动、状态、加载、列出工程、运行、状态轮询、暂停/恢复/停止、退出，并确认无残留 PSCAD 进程。

## 错误与安全

- 所有新失败沿用现有 BackendError/FastMCP 序列化，包含 code、operation、details、retryable 和 suggested_action。
- 外部 PSCAD 检查只读取进程信息，不终止任何未由 MCP 启动的进程。
- 运行控制发生作用域冲突时不执行部分命令；超时后要求先 repair_connection。

## 测试策略

- 先为进程检测、最小化策略、运行作用域冲突、目标未运行和现代单工程停止写失败单元测试。
- 以现有 fake backend/vendor 代理验证 red-green；再运行完整 pytest 和包安装 smoke。
- 最后执行一次真实 4.6.2 x64 冒烟，记录工具数、PID、状态序列、输出和最终进程数。

## 非目标

- 元件禁用/启用或图层接口改造。
- 接管任意已经普通打开的 legacy GUI。
- 在同一 legacy PSCAD 进程中实现未经厂商支持的多工程并行暂停。
- PSCAD 5.x 的真实端到端验收。
