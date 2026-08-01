# PSCAD 4.6.2 / 5.x 全功能双后端设计

**日期：** 2026-08-01

## 目标

让同一个 PSCAD MCP 在 PSCAD 4.6.2 和 PSCAD 5.x 环境中注册相同的 53 个工具，并尽量保持输入、输出、错误语义和安全约束一致。

PSCAD 4.6.2 使用 `mhrc.automation` 1.2.4 后端，PSCAD 5.x 使用 `mhi.pscad` 3.x 后端。MCP 工具不能直接依赖其中任意一种 API，而应通过统一后端接口执行操作。

## 已验证事实

- 本机安装 PSCAD 4.6.2 x86 和 x64。
- `mhi.pscad` 3.1.2 能发现 PSCAD 4.6.2，但使用现代 `/startup:au /port` 模式启动后，4.6.2 不会建立现代自动化连接。
- 本机已有官方 `mhrc_automation-1.2.4-py3-none-any.whl`。
- 使用 `mhrc.automation.launch_pscad()` 已成功启动并连接 PSCAD 4.6.2 x64。
- 已确认许可证有效，并成功读取 `master` 项目列表后正常退出。
- 当前 MCP 的 67 项基线测试通过，53 个工具可以注册，但尚未实现跨后端行为一致性。

## 总体架构

```text
FastMCP 工具层（53 个固定工具名）
                │
        PscadService 统一服务层
                │
       PscadBackend 抽象协议
          ┌─────┴─────┐
          │           │
 LegacyBackend     ModernBackend
 PSCAD 4.6.2       PSCAD 5.x
 mhrc.automation   mhi.pscad
```

### 工具层

工具层仅负责：

- 接收和验证 MCP 参数；
- 调用统一服务层；
- 返回 JSON 兼容结果；
- 对危险操作执行统一安全检查。

工具模块不得直接调用 `mhrc.automation`、`mhi.pscad` 或版本专属代理对象。

### 统一服务层

`PscadService` 为 53 个工具提供稳定操作接口，并负责：

- 项目、Canvas、元件和仿真集对象的统一定位；
- 参数和返回值标准化；
- 统一错误分类；
- 路径安全策略；
- 危险操作确认参数；
- 后端能力实现的组合调用。

### 后端协议

后端协议按职责拆分，而不是建立一个超大文件：

- `ApplicationBackend`：启动、连接、状态、设置、退出；
- `ProjectBackend`：加载、列出、新建、保存、构建、运行和输出；
- `SimulationSetBackend`：列出、运行和添加任务；
- `ComponentBackend`：查找、参数、位置、方向、端口、启停、克隆和删除；
- `CanvasBackend`：创建元件、导线、母线、连接、标注、图形框、控制框和空间查找；
- `ResultBackend`：`.psout` 读取和结果标准化。

实现文件可以共享连接和执行器，但不同职责必须保持清晰边界。

## 后端选择

增加以下环境变量：

- `PSCAD_MCP_BACKEND=auto|legacy|modern`，默认 `auto`；
- `PSCAD_MCP_VERSION`，例如 `4.6.2` 或 `5.0.2`；
- `PSCAD_MCP_X64=true|false`；
- `PSCAD_MCP_LAUNCH_TIMEOUT`，正整数秒数；
- `PSCAD_MCP_LEGACY_WHEEL`，可选，用于给出旧版官方 wheel 的安装位置提示。

自动选择规则：

1. 用户明确指定后端时严格遵循。
2. 指定 4.6.x 时选择 legacy。
3. 指定 5.x 时选择 modern。
4. 未指定版本时，优先连接已有自动化实例。
5. 没有已有实例时，优先选择最高已安装版本；同版本优先 64 位。

指定条件无法满足时返回已检测到的版本和所需安装步骤，不静默切换到其他后端。

## LegacyBackend 设计

### 直接映射能力

旧版库可直接覆盖：

- 启动、许可证、设置、加载和退出；
- 项目列表、保存、另存为、构建、运行、暂停、停止和输出；
- 工作区项目创建和仿真集操作；
- 元件查找、参数、位置、定义、端口位置和删除；
- Canvas 添加元件、添加导线、列出元件；
- 图形框、控制组件和仿真任务代理。

### 组合与命令桥接能力

旧版库未提供现代高层方法的操作，通过受控组合实现：

- 旋转、镜像和翻转：组件通用命令及 `Resource.h` 中的稳定命令 ID；
- 克隆：复制、粘贴、定位，并重新查询新元件 ID；
- 母线、连接标签、标注、图形框和控制框创建：Canvas 通用命令、选择范围和鼠标事件组合；
- 启用和禁用：优先使用旧版可用参数或层状态；若需命令 ID，则用已验证的命令桥接；
- 端口列表：从元件定义或已知端口元数据枚举，并通过 `get_port_location()` 计算绝对位置；
- 空白区域查找：基于组件列表、位置和边界信息计算候选矩形，并在创建前再次检查。

组合操作必须具有后置条件检查。例如克隆后必须确认新增元件 ID、定义和目标位置一致；创建导线后必须确认返回的导线端点。

## ModernBackend 设计

现代后端使用 `mhi.pscad` 3.x，并保留已有的 API 修复：

- `Project.definitions()` 返回字符串；
- 元件定义属性使用 `defn_name`；
- 设置和仿真集位于 `PSCAD` 对象；
- `.psout` 使用 `mhi.psout.File`；
- 所有 PSCAD 调用通过初始化 COM 的单工作线程执行；
- 连接时只选择 PSCAD 5.x，不再尝试用现代协议启动 4.6.x。

## 统一数据模型

后端返回内部标准对象或字典：

- 项目：`name`、`type`、`description`；
- 元件：`id`、`name`、`definition`、`location`；
- 端口：`name`、`x`、`y`、`dim`、`type`；
- 运行状态：`status`、`progress`；
- 连接状态：`backend`、`version`、`x64`、`alive`、`busy`、`licensed`、`owns_process`；
- 错误：`code`、`message`、`backend`、`operation`、`details`。

工具层不得把 XML 节点、COM 对象、MHI 代理或版本专属类直接返回给 MCP 客户端。

## 53 个工具的兼容性要求

每个工具必须满足：

1. legacy 和 modern 后端使用相同工具名与参数结构；
2. 返回字段一致；
3. 错误码和可恢复性说明一致；
4. 至少有两个后端合约测试；
5. 对修改性操作有真实 PSCAD 验收或明确的后置条件测试；
6. 不允许仅注册工具名却在 4.6.2 中固定返回“不支持”。

## 安全设计

- 所有读写路径受 `PSCAD_MCP_WORKSPACE` 限制；
- 创建、另存为和导出操作也必须经过路径策略；
- 删除、退出、覆盖保存和批量修改增加 `confirm=true`；
- 验收使用公共 PSCAD 示例的工作区副本，不修改系统示例；
- 只终止由验收程序启动且已核对路径和自动化参数的 PSCAD 实例；
- 不把旧版官方 wheel 提交到 Git；用户必须从合法 PSCAD 安装介质安装；
- 日志写入 stderr，不能污染 MCP stdio 协议。

## 测试与验收

### 自动化测试

- 后端协议合约测试；
- legacy/modern 双实现测试；
- 工具层统一输出测试；
- COM 初始化和超时恢复测试；
- 路径遍历与危险操作确认测试；
- 53 项兼容矩阵测试；
- MCP 注册和 JSON 序列化测试。

### PSCAD 4.6.2 真实验收

1. 将 `C:\Users\Public\Documents\PSCAD\4.6\Examples` 中选定的小型示例复制到 `D:\PSCAD-Workspace\acceptance`。
2. 通过 legacy 后端启动 PSCAD 4.6.2 x64。
3. 按只读、修改、构建、仿真和结果五组运行工具。
4. 每个修改测试使用独立工程副本。
5. 验收结束后退出测试实例并检查进程清理。

### PSCAD 5.x 验收

在没有 PSCAD 5.x 安装时，modern 后端只进行完整合约测试和 API 形状验证，不宣称真实端到端通过。安装 5.x 后运行相同兼容矩阵。

## 实施阶段

1. 建立后端协议、选择器和连接生命周期。
2. 迁移应用、项目、仿真集和结果工具。
3. 迁移元件读取与参数工具。
4. 实现元件变换、克隆、端口和启停。
5. 实现全部 Canvas 创建和连接操作。
6. 增加危险操作确认和完整路径限制。
7. 运行 53 项 legacy 合约测试和 PSCAD 4.6.2 真实验收。
8. 保留 modern 5.x 合约测试，并在可用环境执行真实验收。

## 依赖与分发

- 基础依赖继续包含 FastMCP、`mhi-pscad`、`mhi-psout` 和 `psutil`。
- `mhrc.automation` 不是普通公开依赖，不在仓库中分发 wheel。
- 安装程序检测 legacy 包；缺失时返回官方安装说明和 `PSCAD_MCP_LEGACY_WHEEL` 配置提示。
- D 盘开发虚拟环境可以安装本机合法 wheel 用于验收，但 `.venv` 保持 Git 忽略。

## 非目标

- 不远程控制其他计算机上的 PSCAD。
- 不把 MCP 暴露为无认证的网络服务。
- 不修改 PSCAD 许可证或登录配置。
- 不承诺未安装版本的真实端到端结果。
