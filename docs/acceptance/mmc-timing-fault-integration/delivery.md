# 两个独立任务与联合交付

更新日期：2026-09-22。两个独立任务已验收；联合交付仍在执行，不应标记为完成。

| 工作 | 分支与当前提交 | 已完成的验收 |
| --- | --- | --- |
| A：严格 EMTDC 定时控制 | `codex/emt-timed-control`，`16c7bf9` | 最小事件工程、官方 PWM 命令及各自独立保存重放均 PASS；四个自有进程已退出。 |
| B：MMC 故障证据 | `codex/mmc-fault-evidence`，`d1139ff` | 两个稳态窗口、DC 故障及电气恢复均 PASS；原始输入未改，自有进程已退出。 |
| A+B 联合交付 | `codex/mmc-timing-fault-integration`，执行版本 `330017c` | 公开模型及发布恢复已通过；r2 首轮联合定时/物理检查 PASS，独立重放的层级排序比较待修复。 |

## 独立交付证据

- [A 工作文档](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-emt-timed-control-work.md)
- [A 最终验收记录](D:/pscad-mcp/.worktrees/emt-timed-control/docs/acceptance/emt-timed-control/final-acceptance.md)
- [B 工作文档](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-mmc-fault-evidence-work.md)
- [B 执行与物理验收记录](D:/pscad-mcp/.worktrees/mmc-fault-evidence/docs/acceptance/mmc-fault-evidence/execution.md)
- [B 原生验收报告](D:/PSCAD-Workspace/mmc-fault-evidence/fault-evidence-20260912T052440515065Z/acceptance-report.json)

A 的实际验收生产版本为 `216c18b`：0.02 s 和 0.03 s 两条边沿的误差均为 0，
满足事先固定的 20 μs 容差。官方 `Pref2` 输出证明功率控制命令的定时行为。

B 的实际验收生产版本为 `86adfe0`，模型配方为
`native_full_sort_dc_integral_004_v1`。故障电流峰值为 8.255083 kA，
原定上限为 20 kA；十二个桥臂均具有真实负插入电压证据，清故障后电气恢复通过。

## 联合交付的剩余步骤

旧公开模型运行和独立重放各含 312 个通道，122 项物理检查全部通过。
当时的故障发生在随后复制结果包时：Windows 路径过长导致 WinError 206。
旧 FAIL 报告与部分复制目录均已保留。

路径修复和恢复/续跑代码已通过独立审查；相关恢复、联合续跑和生命周期回归
99 项通过。恢复入口先校验 282 个冻结文件，再重读波形、重新评估物理判据，
将完全一致的已测模型复制至短路径，最后验证交付副本。

恢复报告已最终 PASS，交付副本 `validate_model` 返回 `accepted: true`，
两个工作区锁均已释放，原始失败证据保持不变。本次恢复没有启动 PSCAD。

[publication recovery journal](D:/PSCAD-Workspace/mmc-publication-recovery-20260922-r1/.pscad-mcp/mmc-builds/59d8d98b1fec42a5aa0b870ba1c682a7/journal.json)。
报告 SHA-256：`268605847ec6d2b257de39e0b133bc889bdfd55d3800fa1e7359bcde7fe32ede`。

[交付的公开模型](D:/PSCAD-Workspace/mmc-timing-fault-integration/public-joint-20260917-b172f6d-r2/public/PublicFault_c269d4cc.pscx)
与已测原模型完全一致，SHA-256 为
`907ca7b02153b1a59587aa6234a1375b87432f3ca1924a69e1ed060c78cf21cc`。

联合 r1 在 20:44:39（Asia/Shanghai）从独立 workspace 启动：
[joint acceptance journal](D:/PSCAD-Workspace/mmc-joint-20260922-r1/.pscad-mcp/mmc-builds/9d05449d39ac48ada2844f48de0954a0/journal.json)。
该次运行于 21:03:54 结束，在首次保存后的完整 XML 比较处 FAIL，未进入编译和仿真；
自有实例与锁已清理。原始模板在 vendor save 时迁移了大量默认字段，不能直接忽略。

`330017c` 改为从已验收、已保存的 public 模型派生联合副本，复制其 15 个固定依赖，
精确重绑定两处 TLine 路径并加入 A 的定时命令；所有其他物理内容仍完整比较。
新增 A 元件的显示尺寸、CRC 以及原滑块面板标签的清空由局部规则验证。
修复后的比较已接受 r1 的真实 vendor-saved 工程，相关 88 项回归通过。
新的联合仿真、故障响应、独立重放和清理仍须重新验收。

固定提交的独立审查已 PASS，并拒绝了 9 项越界修改。r2 已于 22:11:58
（Asia/Shanghai）启动，使用全新工作区，实际 Python PID 为 43124。
当前报告见 [joint r2 journal](D:/PSCAD-Workspace/mmc-joint-20260922-r2/.pscad-mcp/mmc-builds/8107d3b43a1c494fa9c20a3925964942/journal.json)。
运行中的占位 FAIL 只在 `history` 最后一项为 `finished` 时才能解释为最终结果。

r2 已通过真实保存与编译，并完成首轮联合仿真。首轮 122 项物理检查全部 PASS，
故障电流峰值为 8.246814 kA（原定上限 20 kA）。功率命令边沿实测为
1.0 s 和 1.2 s，两条边沿误差均为 0，包含 800 个有效区间样本。
首轮分析证据见 [joint dataset analysis](D:/PSCAD-Workspace/mmc-joint-20260922-r2/joint/joint-analysis/bc916f4809fb45448a7722560dba8df1.json)。
独立重放 worker（launcher PID 28972，实际 Python PID 43220）在保存后比较时 FAIL，
未进入第二次编译或仿真。差异只有层级清单中两条 DCTL call 的顺序互换，实例、
参数和接线未改变。主实例 25872 和重放实例 32816 均已清理，工作区锁已释放。
将保留已通过的首轮模型及完整数据，修复层级比较后仅重跑独立重放；整体验收尚未完成。

分支尚未合并或推送。完整诊断与执行历史见
[集成执行记录](D:/pscad-mcp/.worktrees/mmc-timing-fault-integration/docs/acceptance/mmc-timing-fault-integration/execution.md)。
