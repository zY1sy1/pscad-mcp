# Breaker 工程包自动构图工作文档

**日期：** 2026-08-25
**状态更新：** 2026-08-27
**范围：** 以现有 Breaker 工程包为只读种子，实施可验证的自动修改与自动构图。

## 目标和边界

目标流程保持为：

```text
只读工程包 -> 依赖与实时 inventory 审计 -> 确定性 plan_hash
-> build-ID staging -> 元件/参数/连接操作与逐项读回
-> 保存和重新加载 -> 编译 -> 仿真 -> INF/OUT 验收 -> 受控发布
```

画布上出现元件不等于自动构图完成。结构、参数、保存重载、编译、仿真、消息、
输出和源文件完整性全部通过，才可标记 `run_through_acceptance=true`。只有物理规则
的阈值来源全部受信任时，才可标记 `physical_acceptance=true`。

## 工程包事实

参考 Breaker 包由 `difforder_new.pscx`、`BreakerArc.pslx` 和同级 `lib` 目录组成，
必须作为不可拆分的源包处理。工程内部 Definition、Master Library Definition 和
`BreakerArc:Breaker_arc` 伴随库元件必须分别取得实时证据；随包 catalog 不能代替
当前 PSCAD 安装的 live inventory。源目录永远是只读输入，不能作为 staging 或发布
目标。

## 通用 Blueprint Builder 实施状态

本分支已经实现四个通用工具：

- `plan_pscad_project_build`
- `build_pscad_project`
- `get_pscad_project_build_status`
- `validate_pscad_project_build`

当前状态必须分开记录：

| 状态 | 结果 | 说明 |
|---|---|---|
| `implemented` | `true` | schema、source audit、inventory、planner、executor、validator、service 和 MCP wrapper 已实现 |
| `test_verified` | `true` | 默认离线、fake service、状态机、发布闸门和回归测试已通过 |
| `staging_verified` | `false` | 尚未针对真实 Breaker 包生成许可 PSCAD staging 证据 |
| `live_verified` | `false` | 尚未完成 Breaker 实机验收 |
| `published` | `false` | 没有可发布的 Breaker 实机通过包 |

通用实现支持 `clone_component`、`create_component`、位置、旋转、参数、正交导线、
端口连接、工程设置和输出通道声明。每个操作都有稳定 operation ID，并把 requested /
observed 值写入 append-only journal。源包、blueprint、catalog、依赖、inventory、
selector、单位、override 与 PSCAD 版本共同绑定到 `plan_hash`；执行要求同一组输入、
精确 hash 和 `confirm=true`。

## Breaker 专项待办

- [ ] 确认 `difforder_new.pscx` 与用户逻辑工程名的映射。
- [ ] 在批准的 `PSCAD_MCP_WORKSPACE` 中对完整源包记录 SHA-256 manifest。
- [ ] 用受管 PSCAD 同时加载 PSCX、`BreakerArc.pslx` 和编译依赖。
- [ ] 获取工程内部、伴随库和 Master Library 的实时 Definition/端口/参数/单位。
- [ ] 为 Breaker、换流器、平波电抗器、滤波器、回流路径和输出建立唯一 logical ID。
- [ ] 编写并审核 Breaker 专用 schema-version-1 blueprint。
- [ ] 运行 `plan_pscad_project_build` 并人工审查 operations、warnings 和 `plan_hash`。
- [ ] 在独立 staging 执行，核对每项 mutation 的即时读回和保存重载结果。
- [ ] 完成真实编译、仿真、项目消息、INF/OUT 单位和规则验收。
- [ ] 生成 licensed acceptance 报告和哈希后，再决定发布范围。

## 完成判定

Breaker 第一阶段只有在完整工程包可加载、live inventory 唯一、源 manifest 始终不变、
staging 保存重载和编译通过、仿真达到终态、输出规则通过，并生成可追溯报告后才完成。
当前只可声明通用 Blueprint Builder 已 `implemented` 和 `test_verified`；尚未完成
Breaker 实机验收，不得把默认测试或 fake service 结果描述为 `live_verified`、物理验收
或已发布工程。
