# 本轮验收与剩余条件（2026-10-13）

本轮完成了通用 Blueprint 的指定实机场景、Legacy 15 项实机回归、三组全桥电缆 AVM 的完整实机套件，以及 Corpus 三个 4.6.2 工程的生成、校验和重生成比对。整体任务尚未全部完成。PSCAD 5.x 按用户要求排除。

代码与记录位于独立分支 `codex/acceptance-oct09`，没有合入、推送或部署。精确提交、报告 SHA-256、判定字段和关联文件见 [验收总表](../acceptance-status.json)。历史报告和失败尝试均保留；[原程序基线](lcc-mmc-program-baseline.json)没有改写。

| 范围 | 本轮结果 | 证据与版本 |
| --- | --- | --- |
| 通用 Blueprint 指定分压器场景 | PASS：保存读回、独立重载、编译、仿真和物理检查 | `D:/PA/o13b1/report.json`，`4a6d253` |
| Legacy 核心与可靠性 | 15 项 PASS，92.370 s，运行器确认所拥有进程全部退出 | `D:/PA/o13legacy-report.json`、原始日志 `D:/PA/o13legacy1.log`，`4a6d253` |
| 全桥 AVM 独立桥臂 | 六个充放电、双向闭锁和负插入比窗口 PASS；仍是元件范围 | `D:/PA/o13fb2/attempt-20261013-181151-87715cd1/report.json`，`ecae478` |
| 全桥电缆 AVM，640 kV / 1000 MW / 0 MVAr / 60 Hz | 完整套件 PASS，`model_accepted=true` | `D:/PA/f13f/suite-20261013-185011-6cf6dd58/report.json`，`1d39dc9` |
| 全桥电缆 AVM，500 kV / 750 MW / +100 MVAr / 60 Hz | 完整套件 PASS，`model_accepted=true` | `D:/PA/f13g/suite-20261013-185504-c368baf9/report.json`，`1d39dc9` |
| 全桥电缆 AVM，800 kV / 1200 MW / −120 MVAr / 50 Hz | 完整套件 PASS，`model_accepted=true` | `D:/PA/f13h/suite-20261013-185514-2ba8e35b/report.json`，`1d39dc9` |
| Corpus v2 的三个 4.6.2 工程 | 生成、校验、字节一致重生成及压缩包内容校验完成；完整四工程迁移仍为 PARTIAL | `D:/PA/o13corpus/verification-report.json`、`moxing_462_v2_subset.zip`；静态校验提交 `bbb3a81` |

三组全桥 AVM 均使用 100 km 电缆。每组包含正常冷启动、稳态、功率阶跃和反转、交流三相故障、交流单相接地故障、直流极间故障、直流极地故障，以及新实例中的可携带工程独立重载，共 18 个实机检查。每次运行均核对源码/输入哈希、真实输出、原有物理判据和所拥有进程的退出。报告中的 `intrinsic_dc_fault_blocking=false` 表示本套件没有单独认证“不使用外部隔离时的固有故障阻断”；已经认证的范围包含实际的全桥双向电容插入支路及外部隔离。单个子模块均压、器件应力、开关谐波和热行为仍不在 AVM 中建模。

全桥冷启动增加了 16 个有串联电阻的实体辅助预充电电源，分别充电桥臂电容和两端直流母线，达到实测就绪条件后由实体开关断开。没有覆盖电容状态或赋予初始储能。原有充电电压、时间、能量、故障电流与恢复判据全部保留；新增辅助支路的实测电流也纳入 Kirchhoff 电流守恒检查，容差仍为 `1e-9 kA`。最初失败的 `f13a` 至 `f13e` 保留；`o13fb-network-reanalysis.json` 只是静态诊断，最终 PASS 来自重新运行的三个完整套件。

Blueprint 验收使用官方分压器的独立副本，将电源设为 35.355 kV RMS，源、负载电阻均为 1 Ω。仿真为 0.2 s，4001 个新样本，输出峰值约 ±24.99976 kV。证据覆盖参数与设置变更、读回、独立重载、编译、仿真及发布；其他操作类型或任意新电路需要各自证据。原始教程、已冻结种子、Master 和环境输入均保持哈希。

实际构建日志显示 PSCAD 4.6.2 使用 GFortran 4.2.1 和 `.gf42` 编译目录。脚本还冻结了单独的 GFortran 4.6 环境探针；不能把该探针的哈希当作实际编译器版本。观察记录为 `D:/PA/o13-toolchain-pwm-observations.json`，编译命令保存在各报告中。

| 剩余范围 | 已完成的诊断 | 最小下一条件 |
| --- | --- | --- |
| 参数化 LCC | 三组额定计划均可解析、可导出和重新解析、解析上可行；仍有 13 个未审核物理映射。已收集 71 个候选实体/参数记录 | 用户说明 60 µF 是每支滤波支路还是站内合计，以及 5°–45° 限制整流侧还是也限制逆变侧；随后完成实体映射和额定实机矩阵 |
| 固定 LCC 的 golden 与最终验收 | 官方本机 CIGRE 工程已独立编译运行，未调用被测构建器。核对发现电源、变压器、平波电抗器参数及所需 P/Q/重叠角通道不匹配 | 物理工况匹配、包含完整测量通道的独立参考输出及真实的独立审阅记录；现有官方输出尚不能生成合格 golden |
| 详细 PWM 与其他 MMC 范围 | 已连接嵌入式 EMTDC 定时控制，并保存真实失败。发现默认 `OnOff` 没有定义或接线，`Dblk` 与故障开关选项不能代表断路器/故障命令；已移除这些无依据的默认绑定 | 为详细 PWM 准备经过验证的实际控制接线、单位/极性、额定变更及测量映射；全部 11 个场景保持必需。架空线 AVM 和原 `both` 额定矩阵也仍待完成 |
| Corpus 完整四工程迁移 | 三个 4.6.2 工程的可复现子集已交付。完整迁移以 `CORPUS_DEFINITION_SOURCE_MISMATCH` 保留失败证据 | 版本声明为 **4.6.3** 的原版 `master.pslx`，用于原第四工程；4.6.2 或 4.6.3.1 均没有被冒充为该来源 |

前三个剩余范围的资料分别是 `D:/PA/o13lcc/physical-binding-audit.json`、`D:/PA/o13lcc/reference-qualification.json` 和 `D:/PA/o13pwm3/diagnostic-case.json`。详细 PWM 最新报告为 `HVDC_MAPPING_MISSING`，明确指出 `reset_command` 缺少绑定；这是未验证的控制接口与尚待实现的模型工作，不是许可失败。空默认绑定没有跳过任何物理验收场景；执行保持关闭，直到提供真实接线与绑定。

本轮另行检查了[官方 Intermediate Library](https://www.pscad.com/knowledge-base/article/525)和[官方 CIGRE 参考](https://www.pscad.com/knowledge-base/article/189)。下载的最新 PWM 工程与本机工程字节相同；下载的 CIGRE 文件声明 5.0.2、60 Hz，未进行许可运行，也未作为目标的 golden。[官方 4.6.3 版本说明](https://www.pscad.com/knowledge-base/article/528)区分原版 Master 4.6.3 与热修复版 4.6.3.1，并要求通过 MyCentre 获取对应下载。检索及下载哈希记录在 `D:/PA/o13vendor/source-search.json`。

离线全套回归在 `1d39dc9` 为 **4038 passed、53 skipped**，334.61 s，日志 `D:/PA/o13-regression2.log`。前一次出现一次 Windows 文件替换拒绝访问；该日志保留，针对性重试及新的全套运行均通过，未作无证据补丁。随后默认 PWM 绑定修复 `a87efca` 的 145 项相关回归通过。wheel/源码包在独立导出副本中构建，产物放在 `D:/PA/o13pkg-r2`；这些离线检查不构成新的电气模型 PASS。

[静态证据完整性复核](status-integrity-20261013.json)核对了总表中的 21 个范围，其中 19 个为 `VERIFIED`，没有 `INVALID`。旧 `mmc_stage_a` 和已排除的 `modern_core_5` 没有单一持久化报告，因此全表完整性仍为 `INCOMPLETE`。`VERIFIED` 表示报告、关联文件及其声明相符，不表示全部模型已通过。本轮所有运行结束后，观察到的 PSCAD 进程列表为空；每份实机报告另有独立的所属进程清理核验。
