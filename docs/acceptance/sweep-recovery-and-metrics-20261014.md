# 扫描恢复与物理指标验收（2026-10-14）

实现位于独立分支 `codex/sweep-recovery-metrics`，实机与 PSOUT 文件回放的冻结版本为
`144ba5f`。本轮没有合入主线。该结果只覆盖以下扫描工作流和已有文件分析范围，
不声明完整电气模型或整个项目已经通过验收。

| 范围 | 结果 | 实际覆盖 |
| --- | --- | --- |
| PSCAD 4.6.2 扫描取消、跨进程续跑、意外退出保护与恢复 | PASS，62 项检查 | 第二工况真实 running 后取消；原值恢复和实例退出；新 Python 进程保留第一工况结果并续跑；意外退出后对仍存活的旧实例返回 `SWEEP_NEEDS_REVIEW`；按厂商 PID 与创建时间清理所属实例后显式重试 |
| OUT 物理指标与约束排序 | 包含在上述实机检查中，另有独立复核 | 能量、I²t、峰值及阈值时间；两组三工况，每条通道 8001 个样本；能量/I²t 与独立 Simpson 积分一致；结果哈希、时间窗、单位与基准差保留 |
| 新鲜恢复证据、单位和阈值复核 | PASS，58 项检查 | 核实 54 个文件、所有所属实例退出、V=RI 的全部样本和阈值时间；原始、首次准备及修正准备工程均保持各自哈希 |
| 厂商真实 Cigre.psout 文件回放 | PASS，10 项文件检查；整体 PSOUT 范围 PARTIAL | 两条指定 DC 通道各 2001 个真实样本，与直接厂商 API 读取逐点一致；能量/I²t 独立核算、单位声明及源/副本哈希核实 |

PSOUT 检查读取的是厂商已有二进制示例，`fresh_simulation=false`、
`workflow_accepted=false`、`model_accepted=false`。单位缺失时的 kV/kA 是显式审计声明，
`unit_certification=false`，没有据此认证原模型额定值。未使用的模块/域读取警告完整保留。

## 实现与使用

`analyze_parameter_sweep` 增加可选 `metrics` 参数，支持 `energy`、`i2t`、
`peak_abs` 和 `threshold_crossing`。`objective` 和 `constraints` 可以通过
`metric` 选择指标，也继续支持原来的通道统计。工具总数仍为 112。
定义数量、通道、路径、时间窗、单位和数值均有验证；已保留输出的哈希改变时拒绝分析。
指标在后台线程读取，分析不启动 PSCAD，也不改写 checkpoint。

积分使用保留样本之间的线性信号；能量精确积分电压和电流插值的乘积，I²t 精确积分
电流插值的平方，正向能量与绝对能量在信号变号处继续分段。结果明确声明
`bounded_sample_piecewise_linear`，不外推时间窗，不把采样结果当作连续波形的认证峰值。
缺失阈值事件返回 null，依赖它的工况从排序中明确排除。
完整调用示例见 [参数扫描说明](../parameter-sweeps.md)。

## 保留失败与修复

1. 首轮报告为 `SWEEP_METRIC_UNAVAILABLE`：原分压器把 `Load Current` PGB 的单位写成 kV。
   真实测量是 `master:ammeter` 的 `Iload`，PGB Scale=1.0。只在新建 source-v2 副本中
   将单位修正为 kA；原始工程和首次准备工程均保留。所有 8001 个样本满足 V[kV]=R[Ω]I[kA]，
   预先记录的容差为相对 2×10⁻⁵、绝对 2×10⁻⁵ kV。
2. 第二轮运行器错误地用“必需输出文件”验证工作目录，已通过先失败的回归测试复现。
   `faf66fd` 改为包含性检查与目录类型检查；缺失、文件冒充和路径逃逸仍被拒绝。
   原失败报告不改写，之后按所属 PID 单独核实清理。
3. 第三轮遇到短暂存活的目录外子进程，安全守卫拒绝终止。`144ba5f` 增加有限等待，
   让这些子进程自然退出后再处理核实的所属实例；不扩展可终止进程的范围。
   新回归测试先复现即时拒绝，再验证等待而不终止目录外子进程。
4. 第四轮重新执行完整实机套件，62 项全部通过，形成当前范围的最终新鲜证据。

没有降低物理判据、跳过失败检查或把旧报告替换成 PASS。每个尝试都保留独立目录。
意外退出的未完成尝试仍记为失败，恢复使用新的源副本和新实例；最终两个 campaign
的前三工况尝试数均为 1、2、1，已完成的首个结果哈希不变。

## 证据

工作区：`D:/PSCAD-Workspace/sweep-recovery-metrics-20261014`。

- 实机最终报告：`recovery-20261014-032834-b2210f2b/report.json`。
- 独立复核与 54 文件哈希索引：`final-evidence-audit.json`。
- PSOUT 最终文件审计：`psout-audit-20261014-032913-7a429b68/report.json`。
- 只读源诊断及新计划：`source-metadata-diagnosis.json`、`request-v2.json`。
- 原始失败：`recovery-20261014-031735-cd8aeeb8`、
  `recovery-20261014-032030-c38cc200`、`recovery-20261014-032426-3139517b`。
- 对应报告 SHA-256、冻结版本和显式判定指针见 [验收总表](../acceptance-status.json)。

运行器 `python -m scripts.run_sweep_recovery_acceptance --workspace <绝对工作区> --spec <绝对请求>`
要求既有 `PSCAD_MCP_ACCEPTANCE=1`，不会自行开启许可。每次启动新的报告目录和 campaign。
实机请求把副本仿真延长到 2 s、步长改为 1 μs，使真实 running 状态足以观测；
输出间隔仍为 250 μs。实例内调用串行，每次尝试独立；并发配置只存在于子进程环境。

## 剩余边界

`mhi.pscad.versions()` 只返回 4.6.2 的 x64/x86 安装；当前扫描执行器要求 Legacy。
新生成 PSOUT 的完整扫描仍未验收，需要具备原生 PSOUT 输出能力的许可安装、
该后端经过核实的扫描执行器，以及经审核的 PSOUT 源工程。诊断证据为
`psout-prerequisites.json`。本轮已完成的已有文件读取和 Legacy 工作流不替代这一范围。

固定/参数化 LCC、详细 PWM、其他 Blueprint 场景和整个项目的既有验收边界没有改变。

## 最终验证

`cc86cf6` 的完整离线回归为 **4126 passed、55 skipped**，321.74 s。
许可跳过项不作为实机证据；实机与 PSOUT 已有文件的独立报告仍绑定 `144ba5f`。
两个版本的 `pscad_mcp/` 与 `scripts/` 字节一致；后续记录提交只修改本验收文档。
最终 wheel 在独立目录安装并检查了 112 个注册工具、新可选参数、五个关键运行文件哈希
及解析积分例子；改变文件的 lint 与 Git 空白检查通过。

验收总表为 21 个 VERIFIED、0 个 INVALID；原 `mmc_stage_a` 和 `modern_core_5`
仍缺持久化报告，总体完整性保留 INCOMPLETE。当前运行中的 PSCAD 进程观测为空，
每个本轮所属 PID 另有独立退出核实。最终测试日志、wheel 哈希、安装探针和范围说明
保存在工作区 `verification-final.json`，没有将记录更新解释为新的全项目物理 PASS。
