# PSCAD MCP 基础安全与交付一致性设计

## 状态

已获用户确认，准备进入实现计划阶段。

## 目标

在不改变现有 60 个 MCP 工具名称、默认参数和默认返回形状的前提下，完成第一阶段基础加固：

1. 消除源码版本、已安装包元数据和运行时版本之间的漂移；
2. 让构建后的包在全新环境中可安装、可启动、可发现 60 个唯一工具；
3. 将未配置工作区时的文件访问改为默认拒绝，并提供显式开发例外；
4. 保留已配置 `PSCAD_MCP_WORKSPACE` 时的现有相对路径和安全行为；
5. 用测试和 CI 检查防止版本漂移、路径越界和安装回归再次发生。

## 范围

### 包含

- `pyproject.toml`、`pscad_mcp/__init__.py` 和打包元数据的一致性检查；
- 新环境安装 smoke test；
- `PathPolicy` 的 workspace fail-closed 行为；
- `PSCAD_MCP_ALLOW_UNSCOPED_PATHS` 显式开发例外；
- 对相对路径、绝对路径、路径遍历、错误 payload 和已配置 workspace 的回归测试；
- README、中文文档、示例配置和 CHANGELOG 的配置说明；
- Windows CI 中的版本、构建、安装和工具发现检查。

### 不包含

- PSCAD 5.x 真机端到端验收；
- MCP SDK 2.x 迁移；
- MCP Resources、Prompts、进度通知或取消机制；
- 新增 PSCAD 业务工具；
- 改变 vendor backend、进程所有权或现有工具返回协议；
- 自动修改用户机器上的 Codex 配置文件。

## 现状问题

`pyproject.toml` 当前声明版本为 `0.2.0`，但现有虚拟环境的 editable 安装元数据仍可能显示 `0.1.0`。仅在源码中修改版本号不能防止此类漂移，因此需要同时验证源码版本、构建 metadata 和安装后 import 结果。

`PathPolicy` 当前在未配置 workspace 时允许绝对路径访问任意位置。相对路径会以当前工作目录解析，这在本地调试时方便，但不适合作为 LLM 驱动文件操作的默认安全边界。

## 设计

### 1. 版本单一事实源与安装验证

保留 `pyproject.toml` 作为发布版本的单一事实源，并让 `pscad_mcp.__version__` 与它保持一致。实现一个只读的 metadata 校验辅助函数或测试入口，校验以下三项相等：

- `pyproject.toml` 的 `[project].version`；
- `pscad_mcp.__version__`；
- 构建并安装后的 `importlib.metadata.version("pscad-mcp")`。

CI 和本地测试都必须先构建 wheel/sdist，再将 wheel 安装到临时虚拟环境或临时 target 环境，最后执行：

```text
python -c "import importlib.metadata as m; import pscad_mcp; assert m.version('pscad-mcp') == pscad_mcp.__version__"
```

测试不得依赖当前仓库 `.venv` 的旧 editable metadata。若安装 metadata 不匹配，测试应失败并报告三个实际版本。

### 2. workspace fail-closed 策略

`PathPolicy` 新增显式的未受限开关，建议环境变量名为 `PSCAD_MCP_ALLOW_UNSCOPED_PATHS`，默认值为 `false`。

行为定义如下：

| 配置 | 相对路径 | 绝对路径 |
| --- | --- | --- |
| `PSCAD_MCP_WORKSPACE` 已设置 | 解析并限制在 workspace 内 | 仅允许 workspace 内 |
| workspace 未设置，allow=false | 返回结构化配置错误 | 返回结构化配置错误 |
| workspace 未设置，allow=true | 以当前目录解析 | 保持现有不受限行为 |

路径策略错误应使用现有 service/tool 错误序列化路径，错误码为 `WORKSPACE_NOT_CONFIGURED`，并包含：

- 操作名称；
- 候选路径是否为相对路径；
- 建议设置的环境变量；
- 是否可通过显式开发开关临时放宽。

`PathPolicy.resolve_child()` 始终保持 base directory containment 检查，即使启用 allow=true 也不能允许候选路径逃逸其 base directory。

为避免 import 时冻结配置造成测试和客户端行为不一致，路径策略对象应在服务创建时读取环境变量；测试可以通过构造 `PathPolicy(workspace_root=...)` 或传入显式开关来控制行为。

### 3. 兼容性边界

现有已配置 workspace 的行为必须保持：

- workspace 内相对路径仍解析为绝对路径；
- `..`、符号链接/junction 逃逸仍被拒绝；
- suffix 和 `must_exist` 校验顺序与现有契约一致；
- 现有 60 个工具不增加必填参数；
- 结构化错误仍由 `register_tool` 统一转换。

未配置 workspace 的改变只影响需要文件系统路径的操作，不影响状态查询、组件查询、项目内参数读写和不接收文件路径的工具。

### 4. 文档和配置

英文 README、中文 README 和 `config.example.toml` 要明确：

- 生产使用必须配置 `PSCAD_MCP_WORKSPACE`；
- `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=true` 仅用于受控开发环境；
- 修改配置后需要重启 MCP 连接；
- 路径错误的恢复动作是配置 workspace，而不是反复重试工具。

文档不得写入当前机器的真实项目路径。

## 测试设计

采用测试优先，先添加失败测试，再实现最小行为：

1. 版本一致性测试：源码、构建 metadata、安装 metadata 三者一致；
2. 未配置 workspace 时相对路径失败；
3. 未配置 workspace 时绝对路径失败；
4. allow=true 时保留显式开发行为；
5. 配置 workspace 时正常解析并拒绝越界；
6. `resolve_child` 在所有模式下都拒绝逃逸；
7. FastMCP 工具错误仍为 JSON-safe 结构；
8. 全量工具数量仍为 60 且名称唯一；
9. 构建 wheel 后在隔离安装环境中能导入、启动 server 并发现 60 个工具。

## 验收标准

完成后必须有新鲜命令输出证明：

```text
python -m pytest -q
python -m pip check
python -m compileall -q pscad_mcp tests
git diff --check
```

另外必须验证：

- 一个新构建 wheel 可安装到临时环境；
- 临时环境报告版本 `0.2.0`；
- 临时环境创建 server 后发现 60 个唯一工具；
- 未设置 workspace 的路径操作返回 `WORKSPACE_NOT_CONFIGURED`；
- 已配置 workspace 的现有路径安全测试全部通过；
- 文档、配置示例和 CHANGELOG 对新环境变量的描述一致。

## 风险与回滚

主要兼容性风险是某些现有用户没有配置 workspace，却依赖绝对路径操作。该行为变化必须在错误消息和文档中明确说明；开发者可用显式环境变量临时恢复旧行为。

回滚只需要恢复路径策略默认分支和相关文档/测试，不涉及 PSCAD 工程文件、用户项目或 vendor 进程。
