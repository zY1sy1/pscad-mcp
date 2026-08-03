# PSCAD MCP 交付加固设计

## 目标

在不实施 PSCAD 5.x 真机验收的前提下，把已经完成的 PSCAD 4.6.2 仿真集功能整理成可审阅、可持续集成、可移植安装和可发布的交付版本。

本轮范围包含：

1. 创建交付分支并推送，创建 Draft PR；
2. 增加 Windows CI；
3. 提供不依赖本机绝对路径的配置模板和安装说明；
4. 更新版本号并增加变更记录；
5. 清理已确认的 detached 验证 worktree。

本轮明确不包含 PSCAD 5.x 真实端到端验收、直接合并 PR、删除远端分支或删除仍用于回滚的功能 worktree。

## 交付策略

所有改动集中在 `codex/pscad-delivery-hardening` 分支。分支建立在当前已验证提交 `67908a9` 之上。完成本地核验后推送到 `origin`，并创建 Draft PR；PR 只包含交付加固文件，不改动已完成的仿真集实现。

当前本机 Codex 配置继续使用用户目录中的真实配置文件，不纳入 Git。仓库只提供示例配置、变量说明和安装步骤。

## CI 设计

新增 `.github/workflows/windows-ci.yml`，在 Windows runner 上执行 Python 3.10、3.11 和 3.12 矩阵。每个矩阵任务执行：

- 安装基础依赖和测试依赖；
- `python -m pytest -q`；
- `python -m pip check`；
- `python -m compileall -q pscad_mcp tests`；
- 创建 MCP server 并断言工具数为 60，且工具名唯一。

CI 不安装或启动 PSCAD，不声称完成真实 PSCAD 验收。真实 4.6.2 验收仍由现有 PowerShell 脚本在许可机器上手动执行；5.x 仍保持契约测试限制。

## 配置与安装设计

新增仓库内的配置模板（例如 `config.example.toml`），使用环境变量或用户可替换的示例路径，不写入真实机器路径。模板覆盖：

- MCP server command 和 `-m pscad_mcp.main` 参数；
- `PSCAD_MCP_BACKEND`、`PSCAD_MCP_VERSION`、`PSCAD_MCP_X64`；
- 启动超时、工具超时和工作区路径。

README 英文和中文文档补充：

- Windows 虚拟环境创建与依赖安装；
- 如何复制并替换配置模板中的解释器和工作区路径；
- Legacy 4.6.2 与 Modern 5.x 的选择方式；
- 配置修改后需要新建 Codex 任务才能加载 MCP；
- 不把本机 `D:\pscad-mcp` 或 `D:\PSCAD-Workspace` 描述成通用必需路径。

## 版本与变更记录

将 `pyproject.toml` 版本从 `0.1.0` 更新为 `0.2.0`。新增 `CHANGELOG.md`，以 Keep a Changelog 风格记录：

- 新增 7 个仿真集工具，工具总数达到 60；
- Legacy 4.6.2 真实验收状态；
- Modern 5.x 仅契约测试的限制；
- 删除确认、回读校验、失败恢复等安全行为；
- CI、配置模板和本次交付流程。

不把真实 PSCAD 5.x 验收写成已完成，也不把未推送或未合并写成已发布。

## Worktree 清理

清理前先执行 `git worktree list`，只移除已确认的两个 detached 验证 worktree：

- `C:\Users\335\.codex\worktrees\50f8\pscad-mcp`；
- `C:\Users\335\.codex\worktrees\bcf0\pscad-mcp`。

保留：

- 主仓库 `D:\pscad-mcp`；
- 当前交付 worktree `D:\pscad-mcp\.worktrees\pscad-delivery-hardening`；
- 已验证的功能 worktree，直到交付分支和 Draft PR 验证完成。

删除操作只针对上述精确 worktree 路径，不使用递归删除命令。

## 验证与完成条件

完成前必须在交付 worktree 中重新执行：

```text
python -m pytest -q
python -m pip check
python -m compileall -q pscad_mcp tests
git diff --check
python -c "创建 server 并断言 60 个唯一工具"
```

还必须确认：

- 配置模板不包含真实本机绝对路径；
- 文档中的版本号、工具数和 Modern 限制一致；
- Git 工作树干净；
- 分支成功推送；
- Draft PR 已创建且描述列出验证结果和未实施的 5.x 真机验收限制。
