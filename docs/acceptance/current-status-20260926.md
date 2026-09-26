# 当前验收状态与版本边界（2026-09-26）

多个指定范围已有真实 PSCAD PASS，整体功能与模型族尚未全量验收。
本文件与 [acceptance-status.json](../acceptance-status.json) 同步，区分已合入本地
main 的实现、尚未合入的补全实现，以及真正待完成的范围。

## 已核实结果

| 范围 | 实际结果 | 测试提交及集成情况 |
| --- | --- | --- |
| 原生半桥 MMC 默认 640 kV／1000 MW／60 Hz 电缆平均值模型 | 正常、四类故障、独立重载六阶段 PASS，`model_accepted=true` | `5613ff7`，已合入本地 main；总表保留该历史报告 |
| 已发布全桥 MMC 故障与严格定时联合场景 | 首轮与独立重放各 122 项物理检查 PASS；1.0／1.2 s 边沿误差为 0 | `5613ff7`，已合入本地 main |
| 半桥 MMC 三组参数 | 默认 640 kV／1000 MW／60 Hz、同额定 +100 MVAr、500 kV／750 MW／50 Hz／-75 MVAr；共 18 阶段 PASS | `9cfe1d4`，`codex/complete-acceptance`，未合入 main |
| Legacy 核心与可靠性 | 15 项实机检查 PASS，包含 PSOUT 读取、暂停、恢复、停止，源哈希不变，自有进程已退出 | `d7805e7`，补全分支，未合入 main |
| 固定 LCC | WP1B/WP1C 工程检查 PASS，独立 golden 未完成，最终 `INCOMPLETE_ANALYSIS` | 最新 `85f9d84` 在补全分支；较早 `a2959fe` 工程结果已合入 main |
| 参数化 LCC 执行链 | 真实加载、保存、运行、读取输出、清理 PASS；`model_accepted=false` | `dfaa0b0`，补全分支；不等于公开额定构建器通过 |
| 原生平均桥臂组件 | 充放电与闭锁组件检查 PASS；`component_accepted=true`、`model_accepted=false` | `9cfe1d4`，补全分支；不等于整机通过 |
| 只读统一拓扑 | `generic+hvdc-v1` 指定范围历史 PASS | `6ec6118`；不推广为当前版本的全功能验收 |

半桥平均值模型的验收不包含器件开关应力、开关谐波、单个子模块均压和热行为，
也不代表全桥固有直流故障阻断能力。联合全桥结果只覆盖已发布模型及指定场景，
不能推广到任意额定值、全桥 AVM 或未经验证的原始模板入口。

## 仍需完成

| 范围 | 已知缺口与继续条件 |
| --- | --- |
| 参数化 LCC | 额定功率口径已由用户确定为系统总功率，双极 `P=2U极I极`、单极 `P=U极I极`；继续完成物理参数映射、额定矩阵及实机验证。原“等待功率口径决定”已不再是阻塞项 |
| 固定／原生 LCC 最终验收 | 需要独立参考工程、原始输出及真实审阅记录，随后执行 WP6 对照和最终验收 |
| 其他 MMC 模型及参数族 | 全桥 AVM、其他详细 PWM／额定组合需要自己的模型和物理证据；不能继承三组半桥 PASS |
| 通用 Blueprint Builder | 需要该构建器自己的已审阅蓝图／源样例和许可实机端到端报告 |
| PSCAD 5.x | 当前厂商枚举只有 4.6.2；需要可用的 5.x 安装、Automation、编译器及许可运行环境 |

## 证据与文档更新边界

核对时本地 main 为 `2d9012f3b031a425081e32139f232e303a56095d`，其 MMC 实机
生产提交为 `5613ff7df46e671a9732384c445a99cf500c4559`；两者之间未更改运行代码。
补全结果从已提交快照 `2a9ed5b81bc48bd65cc62e2780a5f9ab17627603` 读取，
未复制正在编辑的实现或将新报告改标为 main 的验收。

- [main 的 MMC 联合与完整套件交付记录](mmc-timing-fault-integration/delivery.md)
- [main 的半桥完整套件报告](D:/PSCAD-Workspace/mmc-merge-0923-native/suite-20260923-162524-9c8d4f0e/report.json)
- [补全分支 MMC 默认参数报告](D:/PA/c26v3a/suite-20260926-121407-e4d0b384/report.json)
- [补全分支 MMC 500 kV 参数报告](D:/PA/c26v3b/suite-20260926-121823-bfb0895a/report.json)
- [补全分支 MMC +100 MVAr 参数报告](D:/PA/c26v3c/suite-20260926-121823-af3bb399/report.json)
- [Legacy 15 项实机报告](D:/PSCAD-Workspace/acceptance/completion-20260926/legacy-130327.json)
- [固定 LCC 动态工程报告](D:/PA/l26fixed/run-20260926-115423-402/fixed-lcc-dynamic-report.json)

每份报告的精确提交、SHA-256、判定字段及关联文件以总表为准。旧失败尝试保存在
`historical_attempts`；[LCC/MMC 程序基线](lcc-mmc-program-baseline.json)继续作为历史
快照保留，不改写成新结果。总表中同一报告被父范围及子范围引用，不算新增独立实机运行。

本次只同步验收记录与说明，静态复核记录见
[证据完整性报告](status-integrity-20260926.json)。静态检查不运行 PSCAD，也不产生新版
物理 PASS。总表仍缺部分范围的持久化报告，`INCOMPLETE` 表示整体未齐备，不表示全部失败。

本次复核的 15 个范围中，12 个声明的报告证据完整性为 `VERIFIED`，无 `INVALID`；
`mmc_stage_a`、`generic_blueprint_builder`、`modern_core_5` 仍缺持久化报告。
上述 12 个包含工程未完成及部分覆盖范围，不代表 12 个模型全部通过。
另行复核的 main 半桥完整套件、较早固定 LCC 工程报告也均通过证据完整性检查。
现有验收总表及历史基线测试共 26 项通过，相关 Ruff、差异空白与本地链接检查通过。
