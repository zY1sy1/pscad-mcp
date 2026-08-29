# LCC/MMC WP0 Baseline Design and Completion Record

**Scope:** WP0 only

**执行分支：** `codex/lcc-mmc-wp0-baseline`

**结论：** WP0 已完成；合并本分支后允许开始 WP1 的独立设计与
implementation plan。该结论不表示任何 LCC/MMC 电气模型已取得最终
licensed acceptance。

## Inputs

WP0 登记并在 licensed preflight 中复核了以下只读输入：

| 输入 | 路径 | SHA-256 |
| --- | --- | --- |
| Master Library | `C:/Program Files (x86)/PSCAD46/master.pslx` | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |
| compiler configuration | `C:/Program Files (x86)/PSCAD46/fortran_compilers.xml` | `bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1` |
| GFortran executable | `C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe` | `fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665` |
| official LCC project | `D:/pscad-mcp-example-inspection-20260829/cigre_lcc_bidirectional/Cigre_LCC_Bidirectional.pscx` | `f36738fbec4c9bdb0995ca73726e16d18e85c10166eaa893e6599a591d5c4a43` |
| official MMC project | `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/H_MMC_Mono_DC.pscx` | `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd` |
| official MMC library | `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/intermediate.pslx` | `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b` |

随包资产登记 5 项：fixed LCC manifest、LCC parametric catalog、monopole
blueprint、bipole blueprint 和 fixed MMC manifest。它们的路径与 hash 保存在
`docs/acceptance/lcc-mmc-program-baseline.json`，执行时重新计算后全部匹配。

## Schema

`pscad_mcp.acceptance.baseline` 提供严格 field-set validator、canonical ASCII
serialization 和 SHA-256。program baseline 包含 repository、environment、
sources、assets、reports 和九个 scope；未知字段、短 commit、非 lowercase hash、
非 UTC RFC3339 时间、重复 scope/run ID 均被拒绝。

每个 scope 具有唯一 `builder_path` 和 `owner_work_package`。报告只有在以下维度
全部一致时才能更新当前状态：

```text
scope + builder_path + owner + repository.base_commit + capability_state
```

`licensed_compile` 只能形成 `compiled`，`licensed_simulation` 只能形成
`simulated`，`licensed_acceptance` 才能形成 `accepted`。compile PASS 和
simulation PASS 均不能自动晋升为 accepted。

当前 baseline 的 canonical SHA-256 为：

```text
9344f4fe768f764a3783c76c38f74a102c2eb9af4b61acbd7f72de36de3f0a7f
```

baseline 中的 evidence target commit 是：

```text
9b12dd707d9ee07ff719d5819baa8ecb614045b6
```

它是 evidence boundary、cleanup 和 read-only source 修复完成后的 clean
implementation commit。随后 `5cbe907dfe08820cbf4f511162de0f98a369052f`
只刷新 baseline 证据指针；最终 preflight 单独证明该 baseline-containing commit。

## Evidence Index Rules

`index_explicit_reports()` 只接受 `{"path": ...}` descriptor，不扫描目录，也不
允许 descriptor 提供 commit、scope、builder 或 status。报告根对象必须自己提供：

- `schema_version=1`；
- full commit、run ID、scope、builder path 和 kind；
- capability state、licensed status 和 UTC generation time。

索引拒绝最终文件或任一父目录为 symlink/junction/reparse point 的路径，限制 JSON
为 16 MiB，并从同一次 regular-file handle 读取字节。JSON parsing 与登记 SHA-256
使用同一份字节；解析后若 path identity 或内容发生变化，返回
`PROGRAM_EVIDENCE_INVALID/evidence_changed`。

`apply_scope_report()` 只接受 report path，并在内部调用该索引。调用者构造的
mapping、虚构 path/hash 或自称 `verified_local` 无法直接更新 scope。

现有四份运行记录均不满足当前 durable report contract：

| 记录 | SHA-256 | 归类原因 |
| --- | --- | --- |
| Master binding compile report | `e541947b914ca78b919b7c4796ee2b7e589fbb9868a47261538ca86106f7b38e` | report-owned commit 缺失 |
| blank LCC journal | `edfb882a9f709b703e2b8625b23ef9eb94b4101e2d6466abe0afaadb9a2108f1` | commit 与 durable report metadata 缺失 |
| blank MMC journal | `ad6ec80ac2223ba5c68740566bd60d15ae13e31b5bdce8c6f3cbe4dd76e394a9` | commit 与 durable report metadata 缺失 |
| MMC parametric report | `18975323c2b563d308a81d6e1743ef866bfb66d193be2de04cd4284917d5d4e5` | commit 为旧提交且 routing metadata 不完整 |

因此初始 baseline 的 `reports` 为空，所有九个 scope 的 `evidence_run_id` 均为
`null`；旧运行只作为 historical sources 保存。

## Static Preflight

静态 preflight 验证并在最终报告中记录：

- named branch、exact clean commit；
- workspace 可写且与 repository、Master、compiler 和所有只读源互不包含；
- Master、compiler XML、真实 GFortran executable；
- `mhrc.automation` 可发现；
- 无外部 PSCAD 进程；
- 三份官方 project/library 均为 regular read-only source；
- production legacy output scanner 能发现 `.gf42/..._01.out`。

output discovery probe 只创建临时 `.out`，不创建 `.pscx`、`.pslx` 或 `.pswx`。
其 scanner 与 `PscadService.discover_output_files()` 共用同一个 bounded helper。

## Licensed Session Preflight

最终 licensed 报告：

```text
path   = D:/PSCAD-Workspace/lcc-mmc-program-preflight/preflight-20260830-042215-773/program-preflight-report.json
sha256 = fe77de2364573d6d2bd6e701a038fe12191b2d5961fdaa1dde80e2bf48274d7f
commit = 5cbe907dfe08820cbf4f511162de0f98a369052f
time   = 2026-08-29T20:22:20.158653Z
status = PASS
```

该报告证明 PSCAD 4.6.2 x64 Legacy runtime `alive=true`、`licensed=true`，managed
PID 为 `5360`。session 前后 workspace project inventory 都是 `{}`；runner
目录只有该 JSON。`quit_error=null`、`remaining_processes=[]`，运行结束后系统
PSCAD 进程数为 0。

Master、compiler configuration、compiler executable 和三份官方源的 before/
after hash 全部相同，`source_immutability_status=PASS`。Legacy backend 还增加了
post-launch process probe 和 initial heartbeat 失败清理测试；部分 attach 失败时
自有 application 必须退出并清空 ownership state。

## Current Baseline Identity

九个 current-truth scope 如下：

| Scope | Builder path | Capability | Licensed status | Owner |
| --- | --- | --- | --- | --- |
| `lcc.master_bindings` | `lcc.master_binding_registry` | `compiled` | `NOT_RUN_ON_CURRENT_COMMIT` | WP1 |
| `lcc.blank_native` | `lcc.blank_native` | `simulated` | `NOT_RUN_ON_CURRENT_COMMIT` | WP1 |
| `lcc.fixed_autonomous` | `lcc.fixed_autonomous` | `planned` | `INCOMPLETE_ANALYSIS` | WP1 |
| `lcc.parametric` | `lcc.parametric` | `planned` | `NOT_RUN_ON_CURRENT_COMMIT` | WP1 |
| `mmc.blank_native_full_bridge` | `mmc.blank_native_full_bridge` | `simulated` | `NOT_RUN_ON_CURRENT_COMMIT` | WP4 |
| `mmc.detailed_pwm_full_bridge` | `mmc.detailed_pwm_full_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | WP5 |
| `mmc.avm_full_bridge` | `mmc.avm_full_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | WP5 |
| `mmc.avm_half_bridge` | `mmc.avm_half_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | WP5 |
| `mmc.parametric` | `mmc.parametric_orchestrator` | `planned` | `INCOMPLETE_ANALYSIS` | WP5 |

`compiled` 和 `simulated` 能力来自历史可核对事实，不形成 current licensed PASS。

## Verification Evidence

TDD 在每个 production change 前先观察到目标失败。最终验证结果：

| Gate | Result |
| --- | --- |
| focused WP0 tests | `43 passed, 2 skipped`（首轮） |
| review-fix expanded tests | `138 passed, 3 skipped` |
| final full repository suite | `2162 passed, 45 skipped` |
| targeted Ruff | PASS |
| PowerShell AST parse | PASS |
| `git diff --check` | PASS |
| final licensed preflight | PASS |

独立 code review 首轮发现 1 个 Critical、3 个 Important：raw mapping transition、
evidence TOCTOU/reparse、partial attach cleanup、瞬态 PSCX 与外部 source 未纳入
immutability。修复提交为：

```text
41fd23187a1878b6588017fa0431b84e82a63255 indexed immutable evidence
9b12dd707d9ee07ff719d5819baa8ecb614045b6 cleanup and source checks
```

对应 adversarial/lifecycle tests、扩展回归、full suite 和修复后 licensed report
均已通过；没有遗留 Critical 或 Important finding。

## Explicit Exclusions

WP0 没有修改任何 LCC/MMC blueprint、catalog、companion library、planner、executor
或 electrical acceptance algorithm，也没有创建或运行 LCC/MMC 工程。

WP0 不证明：

- Master binding 在当前提交重新 compile；
- blank/native LCC 或 MMC 在当前提交通过；
- fixed autonomous 或 parametric LCC 可发布；
- detailed PWM、full-bridge AVM 或 half-bridge AVM 可运行；
- independent golden 存在；
- 任一 LCC/MMC scope 为 `accepted`。

`docs/acceptance-status.json` 的 topology scope 和既有语义保持不变。

## WP1 Unlock Decision

**Decision: UNLOCK AFTER MERGE.**

WP0 的 schema、current evidence inventory、environment preflight、shared run
metadata、offline/full regression 和 licensed environment gate 均已完成。合并本
分支后可创建 WP1 的独立设计与 implementation plan，并从
`lcc.master_bindings`、`lcc.blank_native`、`lcc.fixed_autonomous` 和
`lcc.parametric` 的当前非 PASS 状态开始。

WP1 不得继承任何 historical PASS；第一次 current scope 更新必须通过
`build_run_metadata()` 生成 report-owned metadata，写入 regular report，再把
report path 交给 `apply_scope_report()`。
