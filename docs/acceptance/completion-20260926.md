# 2026-09-26 补全记录与剩余验收

工作分支：`codex/complete-acceptance`，起点 `2d9012f`。
整体补全尚未完成；本记录不声明当前分支通过实机验收。

## 本轮验证结果

验证代码提交：`d9980e66ef7573a725fb61956570bf4b2c70ce6d`。

- 完整离线测试：**3822 passed, 52 skipped**，227.01 秒。许可测试仍按原 opt-in
  跳过，没有把这些跳过项视为验收成功。
- 受影响的 golden、总表、完整性审计和文档回归：62 项通过。
- 新增 Python 文件的 Ruff 全项检查通过；修改的既有文件通过
  `E9,F63,F7,F82,I` 检查；Git 空白检查通过。
- 原 golden 缺少独立审阅也能生成的失败回归已先行观察；修复后涵盖未批准审阅、
  错误范围/合同/时间步、源输出改变、验证后输入改变和旧 golden 保留。
- 静态预检 8/8 PASS；没有打开 PSCAD 或运行任何物理仿真。
- 离线证据审计没有无效范围，整体为 INCOMPLETE，真实 CLI 退出码为 2。

保存的检查报告：

- `D:/PSCAD-Workspace/completion-offline-20260926-110106/static-preflight.json`
- `D:/PSCAD-Workspace/completion-offline-20260926-110106/inventory-audit.json`

这些报告绑定上述代码提交。后续仅更新本文的验证记录，不把它们升级为新版本的
licensed acceptance。两个修复提交为 `5624305`（golden 审阅门）和
`d9980e6`（范围登记与证据审计），尚未合并到 main。

## 已修复

1. LCC golden 生成以前只要求确认写入，普通 JSON 波形可以直接生成非占位参考。
   回归测试先复现了这一行为。现在必须提供独立审阅记录，并验证参考工程、库、原始
   OUT/PSOUT、INF/INFX、归一化波形、编译器、目标合同和时间步的身份。证据缺失、
   哈希改变或输出覆盖输入时拒绝生成，保留旧 golden。
2. 验收总表从八个旧范围更新为十一个范围，分别登记原生半桥默认模型和全桥联合场景。
   保留旧失败记录，不再把已解决的定义映射、定时或故障通道问题写成统一当前阻塞。
   固定 LCC 的工程 PASS 与未完成 golden 分开登记；参数族仍为部分覆盖。
3. 增加离线完整性审计入口，并同步中英文说明和路线图。它验证文件，不启动 PSCAD，
   不把历史 PASS 改写为当前版本或整个模型族的 PASS。

## 真实证据核对

- MMC 合并后的六阶段完整套件报告哈希为
  `ffb61ce075bc651036cc370364a76e1d83e63eaf31ba382c7771531cd488c9d2`。
  六份子报告和 21 个接受文件的记录均通过哈希复核。
- 全桥联合最终报告哈希为
  `95953d8f9e47bb91c48abfa628ebfddc37f458b17291ca263f3ef2ad7574d5fc`。
  报告记录物理验证完成、进程已清理、无待清理项且锁已释放。
- LCC WP1C 报告哈希为
  `226cdd1120d113f7d79c0769df960bc97194d14d1af245f166052a79cedac165`。
  其工程结果为 PASS，golden 及最终结果仍为 INCOMPLETE_ANALYSIS。
- 当前审计总表中六个范围的声明证据完整，五个范围无持久化报告。重复引用同一套件
  不算新增物理验收。详见 `../acceptance-status.json`。

## 尚未完成的工作与准确前提

| 工作 | 已知状态 | 继续所需条件 |
| --- | --- | --- |
| 本轮 PSCAD 4.6.2 实机运行 | 模板、Master、编译器文件存在；当前进程未设置 acceptance opt-in，未启动验收 | 明确启用本次进程的 licensed acceptance；使用独立实例和独立工作区 |
| 参数化 LCC | 实现已合入，缺额定值矩阵的真实完成证据 | 在许可实例上复现执行路径，逐项修复并跑完各参数与运行模式；不能继承固定案例 PASS |
| LCC WP6 | WP1C 工程完成，独立 golden 缺失 | 独立参考工程/原始输出及真实审阅记录，随后完成目标对照与最终发布验收 |
| MMC 剩余模型与参数 | 默认半桥六阶段、已发布全桥联合场景已验收；其他路径仍未全面覆盖 | 按目标路径和额定参数分别执行构建、场景和物理验收；修复可复现缺陷 |
| PSCAD 5.x | 标准安装目录仅发现 PSCAD 4.6.2 | 可用的 5.x 安装、Automation、编译器和许可证，或对应的外部测试主机 |
| 开关应力/谐波/单模块均压/热模型 | 平均值模型明确不包含这些物理行为 | 采用相应详细模型，提供器件与损耗/热参数，并定义相应验收合同 |

当时观察到的外部 PSCAD PID 为 31628；它不是本任务所有。本任务没有停止或附加该进程。
该 PID 只记录当时观察，不能作为未来的进程所有权凭证。

## 续跑入口

以下命令是待明确启用许可运行后的操作说明，本轮未执行。先冻结干净命名分支，
在独立 PowerShell 进程中设置变量，避免污染机器级环境。现有报告保持原样。

```powershell
$env:PSCAD_MCP_ACCEPTANCE = '1'
$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT = '1'
$env:PSCAD_MCP_NATIVE_AVM_FULL_ACCEPTANCE = '1'
& D:/pscad-mcp/.venv/Scripts/python.exe scripts/run_mmc_native_avm_full_acceptance.py `
  --workspace-root D:/PSCAD-Workspace/completion-20260926-native
```

LCC 使用 `scripts/run_fixed_lcc_smoke_acceptance.ps1` 和
`scripts/run_fixed_lcc_dynamic_acceptance.ps1`，遵守 WP1B-before-WP1C 顺序并为两个
报告保留同一代码版本。WP6 参考输入格式见
[独立参考说明](lcc-independent-reference.md)。该步骤不等于参数化 LCC 验收。

无需许可即可运行的完整性检查：

```powershell
& D:/pscad-mcp/.venv/Scripts/python.exe scripts/audit_acceptance_inventory.py
```

审计状态 `INCOMPLETE` 表示总表还有无持久化报告的范围；退出码为 2。
它不等于物理仿真失败，也不能被解释成当前版本全部通过。
