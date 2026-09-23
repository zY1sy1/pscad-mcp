# 工作 A：严格 EMTDC 定时控制 Implementation Plan

> **For agentic workers:** 使用 `executing-plans` 按任务清单执行；开始修改前使用 `using-git-worktrees`，行为变更使用 `test-driven-development`，失败诊断使用 `systematic-debugging`，交付前使用 `verification-before-completion`。这是实现与验收工作，不是重复元件映射离线预审。

**Goal:** 让 PSCAD 4.6.2 的 MMC detailed PWM 路径执行具有明确 EMTDC 时间、源文件身份、保存回读和真实事件波形证据的定时控制。

**Architecture:** 复用现有 `select_timing_mode`、场景执行器和 PWM staging 生命周期。先核实原生 API 能力；缺少可信原生调度时，在任务拥有的工程副本中生成嵌入式 EMTDC 控制，以独立适配模块接入场景执行。事件证据通过固定的交接合同供工作 B 使用。

**Tech Stack:** Python 3.10+、asyncio、ElementTree、pytest、PowerShell、PSCAD Automation Library、EMTDC。

## 1. 执行依据与当前状态

**执行状态（2026-09-23）：独立任务及 A+B 联合验收均已完成。** 分支
`codex/emt-timed-control`，交付提交 `16c7bf948bdd9724283478f2a66ae5bf097a188d`，
实际验收生产版本 `216c18ba187f0b86194c4f91dfd3c19d1b281714`。
最小事件工程、官方 PWM 命令及各自独立保存重放均 PASS，四个自有进程已清理；
两条边沿误差均为 0，离线全套 2517 通过、50 跳过。详细证据见
[独立验收记录](D:/pscad-mcp/.worktrees/emt-timed-control/docs/acceptance/emt-timed-control/final-acceptance.md)。
下方实施清单保留为原始计划，实际完成情况以上述证据为准。
A+B 首轮联合运行及独立重放均通过 122 项物理检查，1.0 / 1.2 s 命令边沿实测误差均为 0，
自有进程已清理。完整交付见
[联合交付清单](D:/pscad-mcp/.worktrees/mmc-timing-fault-final/docs/acceptance/mmc-timing-fault-integration/delivery.md)。

- 首先读取 [验收与失败处理规则](D:/pscad-mcp/docs/acceptance-criteria.md)。它适用于本任务的代码、模型、实机运行和完成判定。
- 阅读 [总路线图 WP3](D:/pscad-mcp/docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md:632) 与 [并发验收记录](D:/pscad-mcp/docs/acceptance/concurrent-acceptance-20260908.md)。旧路线图的全局串行约束按用户最新的独立实例规则执行。
- 配套任务是 [工作 B：MMC 故障证据链补齐](D:/pscad-mcp/docs/superpowers/plans/2026-09-08-mmc-fault-evidence-work.md)。元件映射离线预审由已有任务继续，本任务只读取其最终产物。
- 编写时主分支已包含 `db65d74` 的并发隔离与失败处理修改，以及 `a759a46` 的验证记录。执行时记录实际基线 SHA，不把这两个提交号当作本任务验收证据。
- 现有 [timing.py](D:/pscad-mcp/pscad_mcp/hvdc/timing.py) 支持原生调度和仿真时钟轮询；Legacy 当前检查项目对象上是否存在方法。方法存在本身不能证明其时基和精度。
- 现有 [template_native.py](D:/pscad-mcp/pscad_mcp/hvdc/builders/mmc/template_native.py) 能在副本中配置部分模板控制，但尚不能代表任意事件序列均有严格调度能力。

## 2. 隔离与文件分工

推荐分支：`codex/emt-timed-control`。推荐工作树：`D:/pscad-mcp/.worktrees/emt-timed-control`。实机证据根目录：`D:/PSCAD-Workspace/emt-timed-control`，每次运行再创建唯一子目录。

工作树从包含并发支持的当前主分支创建；已存在时核对所属任务、分支及未提交修改后续做，不能重建覆盖。主目录中的其他任务修改不属于本任务。

| 文件范围，以本任务工作树为根 | 本任务职责 |
| --- | --- |
| `pscad_mcp/hvdc/timing.py` | 时基校验、事件校验、调度与确认语义 |
| `pscad_mcp/hvdc/scenarios.py` | 调度选择、预先生成嵌入式场景、运行与取消、事件证据记录 |
| `pscad_mcp/hvdc/builders/mmc/timed_control.py`，新增 | 模板事件适配、工程副本生成与回读；需要独立模块以避免与 B 修改同一文件 |
| `pscad_mcp/hvdc/builders/mmc/scenarios.py` | MMC 事件请求到调度合同的映射 |
| `pscad_mcp/hvdc/builders/mmc/engines/pwm.py` | detailed PWM 接入及调度失败证据保留 |
| `pscad_mcp/core/backend/base.py`、`legacy.py`、`modern.py` | 仅在现有接口不足时做必要的定时接口兼容修改 |
| `tests/test_hvdc_timing.py`、`test_hvdc_backend_timing_providers.py`、`test_hvdc_scenario_strict.py`、`test_mmc_scenarios.py`、`test_mmc_pwm_engine.py` | 现有相关回归 |
| `tests/test_mmc_timed_control.py`、`tests/test_emt_timed_control_real.py`，新增 | 嵌入式合同与专用 licensed gate |
| `docs/acceptance/emt-timed-control/`，新增 | 设计决定、执行记录与小型交接文件；大型 OUT 文件留在实机证据根目录 |

`template_native.py`、`template_audit.py`、`blank_service.py`、MMC `acceptance.py` 和故障通道模块归 B 修改，A 只使用其现有接口。`profiles.py` 的故障测量语义也归 B。A 在自己的模块中实现新增调度，不改写 B 的评估函数。LCC 模型、固定 MMC 资产和正在进行的元件映射清单不在本任务修改范围。

## 3. 两任务共用的交接合同

A 独占写入 `docs/acceptance/emt-timed-control/schedule-handoff.json`；B 读取最终提交中的稳定版本，不读取正在写入的产物。该文件是新交接文件，不改变既有运行报告的 `status` 枚举。

| 字段 | 必须表达的含义 |
| --- | --- |
| `schema_version`、`producer_revision` | 初始版本为 1；记录实际生产代码提交 |
| `source_hashes` | 原始 Master、官方 project、官方 library 的路径及 SHA-256 |
| `schedule_sha256` | 在修改工程前，对规范化事件合同计算的 SHA-256 |
| `time_basis`、`schedule_source` | 时基为 `EMTDC`；来源明确区分 verified vendor API 与 embedded control |
| `time_step_s`、`output_step_s`、`max_timing_error_s` | 运行前固定，使用秒；不依据结果事后放宽容差 |
| `events` | 每项包含唯一 `event_id`、`time_s`、`end_time_s`、目标实例路径/owner/参数、前/中/后值、单位和事件通道 selector |
| `event_channels` | 信号的 owner、实例层级、定义、端口、单位、0/1 或其他值的物理语义 |
| `readback` | 保存后重新解析的值、实际工程哈希与预期合同的比较结果 |
| `run_evidence` | run ID、最终报告与输出索引路径、报告 SHA-256、实际测得的事件时间和误差 |

事件按时间与稳定 ID 规范化；拒绝非有限值、负时间、结束早于开始、同一目标上的冲突事件。相同目标上合法的不重叠事件序列允许保留。工程中的所有事件目标和条件端口必须有唯一可解释的绑定。

B 独占写入 `docs/acceptance/mmc-fault-evidence/channels-handoff.json`。交接时比较双方原始输入哈希；A 的调度副本与 B 的仪表化副本可以有不同哈希，但必须记录完整的派生关系及共同的 `schedule_sha256`。

## 4. 实施清单

### A1. 建立基线并复现能力缺口

- [x] 阅读本文件、验收规则、适用 AGENTS.md 和 B 的文件所有权表。
- [x] 在独立工作树记录基线、Python 路径、并发支持版本和原始输入哈希。
- [x] 运行第 6 节的现有离线回归，记录真实结果；不沿用其他任务的测试数量。
- [x] 检查安装的 Automation Library 文档与项目对象 API，保存调度方法、时间单位、阻塞行为和读回能力的证据。不得为不存在的厂商 API 伪造适配成功。
- [x] 复现 PWM 的 `HVDC_TIMED_CONTROL_UNAVAILABLE` 路径，保留场景、调用边界和错误详情；确定原生 API 或嵌入式控制的适用范围。

### A2. 先固定合同，再实现调度适配

- [x] 为下表每类行为添加有意义的失败回归，先观察失败，再修改生产代码。
- [x] 在已有接口上增加必要的时基与事件合同校验；兼容现有 LCC 调度，更新实际受影响的 fake 对象合同。
- [x] 为嵌入式路径在 `mmc/timed_control.py` 实现结构化 XML 配置；复用现有 Master 元数据和模板审计，不复制一套 registry。
- [x] 事件合同先规划、计算哈希，然后生成唯一副本。保存后重新解析目标实例、参数和输出 owner；重新核对原始输入哈希。
- [x] 原生 API、仿真时钟轮询和嵌入式控制分开表达能力。轮询只能使用可信仿真时间，并证明误差满足合同；墙钟仅用于超时与存活检测。

| 回归输入 | 必须观察的行为 |
| --- | --- |
| 只有墙钟，或时基未得到证明 | 保持明确的 unsupported 错误，不发送定时写操作 |
| NaN、Infinity、负时间、反向区间、冲突目标 | 在工程修改前拒绝 |
| 重复 owner 或条件端口不唯一 | 绑定失败，不选择第一个匹配项 |
| 调度合同或原始输入哈希改变 | 旧计划失效，不继续运行 |
| ACK 数量相同但事件 ID、目标或值不匹配 | 拒绝确认成功；不能只比较列表长度 |
| 保存后的参数或 owner 漂移 | 回读失败，保留诊断证据 |
| 取消、超时、时钟倒退或停滞 | 停止本任务的运行，释放自己的 lease，保留报告 |
| 缺事件通道或实测时间越界 | 缺证据或检查失败；不能把已注册调度当作已发生事件 |

### A3. 接入真实调用路径

- [x] 在场景执行器中接入已经审计的调度方式，使预先生成的嵌入式事件在编译前生效。
- [x] 通过现有公开场景/PWM 入口调用该实现；避免只在独立脚本内演示成功。
- [x] 保存 scenario source、调度合同、derived project 和 output 的对应关系；错误处理保留首次失败原因和相关产物。
- [x] 在 B 尚未完成时，用专用事件通道完成 A 的测试；不把 B 的完整 MMC 故障判据作为本任务单元测试的前置条件。

### A4. 最小工程实机验证

- [x] 新增专用 licensed test，复用 [进程所有权策略](D:/pscad-mcp/pscad_mcp/acceptance/process_scope.py) 和既有连接生命周期，不另造全局 PID 清理逻辑。
- [x] 使用原创建模的小型事件工程：事件 `0 -> 1 -> 0`，请求区间 `[0.02, 0.03)` 秒，仿真至 `0.05` 秒，积分步长和输出步长均为 `10 us`，预先固定边沿最大误差 `20 us`。
- [x] 从真实 OUT/INF 得到上升沿、下降沿和高电平持续区间；输出 sample count、时间范围、单位及源文件哈希。上述数值只属于定时测试，不作为 MMC 电气验收阈值。
- [x] 验证工程能保存、重新加载、编译并运行，原始文件哈希不变，结束后本任务拥有的实例退出。
- [x] 若失败，按第 7 节分类并修复后复跑，直到本测试闭合或有可证明的外部阻塞。

### A5. PWM 接入验证与交接

- [x] 在独立官方模板副本上，通过真实 PWM candidate/场景入口生成至少一个已验证的 EMTDC 事件通道。
- [x] 明确记录已支持的事件集合；未实现的功率反转或控制序列不能自动降级或声明支持。
- [x] 运行受影响的共享场景与 LCC 定时回归，完成代码审查和 `git diff --check`。
- [x] 保存 `schedule-handoff.json`，记录最终提交、输入/工程/报告/输出哈希、命令、结果和未验证范围。
- [ ] B 完成后，在独立集成分支接入其最终提交；A 负责共享场景/PWM 连接处的集成，B 负责物理判据和通道复核。集成后的受影响验收使用新的证据。

独立交付已完成，生产代码为 `216c18ba187f0b86194c4f91dfd3c19d1b281714`。
最终证据见 `docs/acceptance/emt-timed-control/final-acceptance.md` 和同目录
`schedule-handoff.json`。最后一项属于 root 协调的后续联合集成，不将 A 的
控制命令波形当作 B 的故障作用证据。

## 5. 并发执行规则

两任务可以同时编写代码和运行独立实机测试。每个执行者使用独立 Python 进程、PSCAD 连接、executor、workspace 和输出目录，单实例内部的自动化调用保持串行。

只在当前执行进程环境中设置 `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1`。这一开关不替代任何已有的 licensed opt-in。启动前确认工作树包含对应 runner 支持；不设置系统级变量，不接管或终止其他任务实例，不通过全局 PID 前后差推断所有权。

本任务不修改 B 所有的文件。若发现必须共同修改的接口，先在自己的工作树记录最小变更及失败回归，按第 2 节的唯一文件所有者落实；其他独立工作继续推进。B 所需的共享 backend 输出接口变更由 A 汇总实现并给出明确提交，不要求 B 同时编辑 `legacy.py`。

## 6. 验证命令

以下命令从 A 工作树运行，使用仓库已安装依赖的解释器。实机命令仅在保留既有许可 opt-in、完成对应测试实现后执行。

```powershell
git rev-parse HEAD
git status --short --branch
git merge-base --is-ancestor db65d74 HEAD
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_hvdc_timing.py tests/test_hvdc_backend_timing_providers.py tests/test_hvdc_scenario_strict.py tests/test_mmc_scenarios.py tests/test_mmc_pwm_engine.py -q
```

期望：祖先检查退出 0；离线测试通过。失败时记录基线问题并诊断，不能伪记为通过。

实现完成后：

```powershell
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_mmc_timed_control.py -q
git diff --check
$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT = '1'
$env:PSCAD_MCP_WORKSPACE = 'D:/PSCAD-Workspace/emt-timed-control'
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_emt_timed_control_real.py -q -s
```

新增实机测试使用 `PSCAD_MCP_ACCEPTANCE=1` 作为明确 opt-in；已有 MMC runner 继续保留其 `PSCAD_MCP_MMC_ACCEPTANCE` 等原有条件。运行前创建 workspace，测试自身为每次运行分配唯一子目录。缺少 opt-in 导致 skip 时，本项仍为未验收。全仓检查和 lint 在交付与集成时按实际受影响范围执行并记录。

## 7. 完成条件与失败处理

独立交付要求：可信时基与事件合同已实现；最小事件实机测试通过；PWM 实际入口产生至少一个符合容差的事件输出；回读、输入不变性、失败证据和本实例清理均有最终代码版本的证据。仅有计划、mock 测试或 compile 结果不算完成。

资源争用归为环境问题；接口、调度、脚本和报告缺陷归为实现问题；控制作用错误归为模型问题；缺许可、不可用的厂商能力或缺失不可变输入归为外部能力问题。保留失败报告，先修复可复现的本任务缺陷，再运行受影响的验收。外部阻塞交接必须列明证据、已尝试操作、已完成的独立工作与准确缺少的前提。

本任务通过不代表 MMC 已通过 DC fault 物理验收，也不提升 WP2、WP5 或 WP6 状态。正式集成和最终发布仍按路线图的实际依赖与证据门执行。

## 8. 可直接发送给执行任务的指令

> 执行 `D:/pscad-mcp/docs/superpowers/plans/2026-09-08-emt-timed-control-work.md`。这是严格 EMTDC 定时控制的实际实现与实机验证，元件映射离线预审由另一个任务负责。读取验收规则，在自己的工作树、PSCAD 实例和 workspace 内推进，遵守 A/B 文件所有权与事件交接合同。持续修复可复现问题并复跑受影响验收，交付最终提交与真实事件波形证据；不要将单次 FAIL 或 mock 通过当作任务完成。
