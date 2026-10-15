# PWM 补充修复交接（2026-10-15）

用户明确指定由现有对话“查找后续可做事项”
（`01a13848-3726-7f91-a251-c8ba955b7501`）继续负责，要求本对话整理修复并发送交接。
本对话不再启动实机套件，不合并、推送或改动接收分支及已验收模型。

接收分支当前为 `codex/mmc-detailed-pwm`，文档提交 `abdeaca`。
交接时读取的 `D:/PA/pwm14/public-v6/report.json` 为 `PASS`、
`model_accepted=true`、`stage=finished`、`sources_immutable=true`、
`remaining_owned_processes=[]`，验收代码为
`95655d1e06c45eda820b4ba22d2fefded55e1e39`。
报告 SHA-256 为
`bf099c66d2c7b6ec2a074f6b3a9f0b117ddddf05b54269fb1dac18c604724136`。
该报告及接收分支的完整验收记录属于其自身版本；没有转移到本分支。

## 可审阅成果

本分支 `codex/mmc-pwm-closure` 的共同基线为 `2287d93`，实现截至
`8bf57ea`，前一份状态文档为 `0fd0bb7`。工作树：
`C:/Users/335/.codex/worktrees/mmc-pwm-closure/pscad-mcp`。

- `903c243`：以实际 `I_AC1/I_AC2` 三相电流驱动已有交流断路器的 7.5 kA
  保护；在派生副本中改变了保护行为。单相故障诊断在该提交通过 484 项检查，
  断路器于 2.3032 s 断开，故障电流峰值 30.2738 kA。证据在
  `D:/PA/p15/slg2` 和 `D:/PA/p15/slg2-analysis`。这是另一个可比较的保护方案，
  与接收分支的 SLG 序网络分析修复不同；不能直接加入已验收模型并继承其 PASS。
- `227efa8`、`79dbb62`：冻结完整矩阵证据与代码，拒绝仅凭读取器 PASS
  接受模型，并通过物理重算复核。接收分支 `4d9f486`、`95655d1` 已有更完整的
  验证和独立发布运行，宜仅比较遗漏项。
- `ddf42de`：交付真实相对路径编译库并核验哈希。
  接收分支 `95655d1` 已实现同类修复和发布隔离，保留其已验收实现。
- `45dae67`、`8bf57ea`：真实测量探针与输出组解析，并覆盖工程重命名。
  接收分支 `738d91a`、`d0e547d` 已实现同类功能。
- `5a3738d`：等待完整输出分片和结束时间。
  接收分支 `3475c27` 已有同类修复。

可比较的新增回归包括 `tests/test_mmc_pwm_ac_protection.py`、
`tests/test_mmc_pwm_publication.py`、`tests/test_mmc_pwm_measurement_profile.py`。
本分支曾有 4158 项全套离线测试通过、55 项跳过；最后增量的 106 项相关回归通过。
wheel/源码包已构建并在独立目录核验。原始日志及哈希见
`D:/PA/p15/closure-status.json` 与
`docs/acceptance/mmc-pwm-closure-20261015.md`。

## 证据和运行边界

本分支仅有单相故障诊断实机 PASS；完整套件 `D:/PA/p15/s1` 因重复实机运行而中断，
不能作为完整验收。`D:/PA/p15/s1-interruption-cleanup.json` 保存中断报告哈希、
源/代码不变和自有 PID `18828` 退出的证据；诊断实例 PID `4444` 也已退出。
没有终止或附加接收对话的实例，没有根据全局 PID 差认领进程。

原始 `closure-status.json` 及其已登记哈希保持不变，属于中断时的历史证据。
`D:/PA/p15/handoff.json` 单独记录用户的负责对话选择和本次交接。
若以后采用本分支的保护变更，应先审阅接收分支现有实现，再冻结新提交并对受影响的
物理场景和完整性合同重新验收。全部 11 个必需场景及独立重载要求保持不变。
