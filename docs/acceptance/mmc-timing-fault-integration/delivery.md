# 两个独立任务与联合交付

完成日期：2026-09-23。A、B 两个独立任务及联合验收均已完成；所有本任务拥有的运行进程已退出，工作区锁已释放。

| 工作 | 分支 / 版本 | 验收结论 |
| --- | --- | --- |
| A：严格 EMTDC 定时控制 | codex/emt-timed-control，16c7bf9 | 最小事件、官方 PWM 命令及各自独立保存重放 PASS。 |
| B：MMC 故障证据 | codex/mmc-fault-evidence，effe983 | 双稳态窗口、DC 故障与电气恢复 PASS；公共重放修复已同步。 |
| A+B 联合验收 | codex/mmc-timing-fault-integration，运行版本 6410b5e | 首轮与独立重放的物理、时序检查均 PASS；最终恢复报告 PASS。 |

## 联合结果与交付模型

| 指标 | 首轮联合运行 | 独立保存模型重放 |
| --- | ---: | ---: |
| 物理检查 | 122 / 122 PASS | 122 / 122 PASS |
| 故障电流峰值，固定上限 20 kA | 8.246814 kA | 8.246814 kA |
| 功率命令上升 / 下降沿 | 1.0 / 1.2 s | 1.0 / 1.2 s |
| 两条边沿实测误差 | 均为 0 | 均为 0 |
| 采样数 / 输出范围 | 20001 / 0–5 s | 20001 / 0–5 s |
| 故障施加、负插入、闭锁与恢复 | 全部通过 | 全部通过 |

积分步长 25 μs，输出步长 250 μs，事先固定的联合时序容差为 500 μs。
物理与时序证据来自各自同一套完整 OUT/INF/INFX 数据；每次有 312 个物理/诊断通道和一个独立定时命令通道。

- [联合模型及相邻依赖包](D:/PSCAD-Workspace/mmc-joint-20260922-r2/joint/JointFaultCase.pscx)
- [最终联合验收报告](D:/PSCAD-Workspace/mmc-joint-replay-20260922-r1/.pscad-mcp/mmc-builds/99f5b751febe446ab35182a8156b4692/journal.json)
- [首轮联合分析](D:/PSCAD-Workspace/mmc-joint-20260922-r2/joint/joint-analysis/bc916f4809fb45448a7722560dba8df1.json)
- [独立重放 worker 报告](D:/PSCAD-Workspace/mmc-joint-replay-20260922-r1/replay/worker/report.json)
- [公开模型](D:/PSCAD-Workspace/mmc-timing-fault-integration/public-joint-20260917-b172f6d-r2/public/PublicFault_c269d4cc.pscx)与[发布恢复报告](D:/PSCAD-Workspace/mmc-publication-recovery-20260922-r1/.pscad-mcp/mmc-builds/59d8d98b1fec42a5aa0b870ba1c682a7/journal.json)

最终报告于 00:05:25（Asia/Shanghai）写入 PASS，physical_acceptance_verified=true，
worker_exit_code=0，cleanup_pending=false，lease_retained=false，无收尾错误。
报告 SHA-256：285a9af72060b26d9051c609948bcc260bba6f1bd4519fb4302966a3d22c132b。
联合交付模型 SHA-256：dc3f5b8dd35267a19c625b8fde234606bebff04f04bdcce54d820f7428c80e07。
独立 worker 从该模型的逐字节副本启动，随后保存模型的允许差异均经过完整结构核对。

## 两个工作文档及独立验收

- [工作 A 文档](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-emt-timed-control-work.md)及[A 验收记录](D:/pscad-mcp/.worktrees/emt-timed-control/docs/acceptance/emt-timed-control/final-acceptance.md)
- [工作 B 文档](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-mmc-fault-evidence-work.md)及[B 执行记录](D:/pscad-mcp/.worktrees/mmc-fault-evidence/docs/acceptance/mmc-fault-evidence/execution.md)

A 独立实机生产版本为 216c18b，0.02 / 0.03 s 边沿实测误差均为 0，满足 20 μs 容差。
B 原生物理生产版本为 86adfe0，固定配方为 native_full_sort_dc_integral_004_v1；原始输入、阈值和历史报告保持原样。
Pref2 是控制命令证据；实际故障动作和恢复由 B 的独立物理测量通道证明。

## 验证与保留记录

恢复与相关回归 187 项通过；同步至 B 的重放回归 77 项通过，Ruff 和 diff 检查通过。
模型派生、层级比较和续跑入口均通过独立审查。最终恢复核对了 323 个输入/代码文件身份，
并以新的独立 PSCAD 实例完成重放、全部物理与时序检查及清理。

旧 FAIL 报告保留为失败尝试记录。首轮联合物理已通过，后续仅层级顺序和合法实例编号比较需要修复，
因此保留未改变的首轮模型与数据，仅重跑受影响的独立重放；最终报告明确关联两部分证据。

当前集成工作树：D:/pscad-mcp/.worktrees/mmc-timing-fault-final。
旧 D:/pscad-mcp/.worktrees/mmc-timing-fault-integration 已冻结以保留历史代码身份。
分支尚未合并或推送。完整诊断、修复与失败尝试见[集成执行记录](D:/pscad-mcp/.worktrees/mmc-timing-fault-final/docs/acceptance/mmc-timing-fault-integration/execution.md)。
