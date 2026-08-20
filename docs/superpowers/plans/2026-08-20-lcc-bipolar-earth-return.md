# LCC 双极带大地回线理解能力 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 为 LCC 双极 PSCAD 工程增加可审计的正负极、接地极、地回线/金属回线和回流模式识别与只读验证能力。

**Architecture:** 在现有 HVDC scanner/classifier/profile/mapping/service 边界内增加显式回流路径模型。扫描器提供组件、端口和连接证据；分类器生成候选极性和回流路径；独立的 LCC earth-return profile 声明所需资产和测点；service 将验证结果序列化为现有 inspect/validate 契约。第一阶段不修改工程，不增加 scenario 写入能力。

**Tech Stack:** Python 3.10+, dataclasses, XML ElementTree, pytest, 现有 FastMCP/HVDC domain service。

---

## 文件地图

- Modify: pscad_mcp/hvdc/models.py — 增加连接证据、回流路径和拓扑摘要字段。
- Modify: pscad_mcp/hvdc/scanner.py — 提取跨 canvas/definition 的端口连接证据。
- Create: pscad_mcp/hvdc/return_paths.py — 负责回流路径构图、闭合判断和模式判定，避免继续膨胀 classifier.py。
- Modify: pscad_mcp/hvdc/classifier.py — 调用回流路径分析并增加 LCC 极性/资产分类。
- Modify: pscad_mcp/hvdc/profiles.py — 注册独立的 lcc_bipolar_earth_return_v1 profile。
- Modify: pscad_mcp/hvdc/mappings.py — 支持新 profile 的 canonical 测点和方向/单位证据。
- Modify: pscad_mcp/hvdc/service.py — 将回流路径和模式验证接入 inspect/validate。
- Modify: pscad_mcp/core/service.py — 增加 HVDC_RETURN_PATH_UNRESOLVED 错误文案。
- Modify: pscad_mcp/hvdc/metrics.py — 增加回流闭合和极间不平衡指标。
- Create: tests/fixtures/hvdc/lcc_earth_return/*.pscx — 五个最小结构 fixture。
- Create: tests/test_hvdc_return_path_model.py
- Create: tests/test_hvdc_lcc_earth_return_classifier.py
- Create: tests/test_hvdc_lcc_earth_return_profile.py
- Create: tests/test_hvdc_return_path_validation.py
- Create: tests/test_hvdc_lcc_earth_return_fixture.py
- Modify: tests/test_hvdc_metrics.py — 增加回流指标测试。
- Modify: tests/test_hvdc_tools.py — 保证新 profile 不改变现有工具登记和 JSON 安全性。

---

### Task 1: 扩展 JSON-safe 领域契约和错误码

**Files:**
- Modify: pscad_mcp/hvdc/models.py
- Modify: pscad_mcp/core/service.py
- Test: tests/test_hvdc_return_path_model.py

- [ ] **Step 1: Write the failing model serialization tests**

~~~python
import json
from dataclasses import asdict

from pscad_mcp.hvdc.models import (
    HvdcReturnPath,
    HvdcSourceRef,
    HvdcTopologySummary,
)


def test_return_path_and_topology_summary_are_json_safe():
    source = HvdcSourceRef(
        project_path="case.pscx",
        canvas_name="Main",
        component_id="42",
        definition="EarthElectrode",
    )
    path = HvdcReturnPath(
        mode="earth_return",
        segments=(source,),
        endpoints=(source,),
        closed=True,
        confidence=1.0,
        evidence=("EarthElectrode", "GroundReturn"),
        unresolved_questions=(),
    )
    summary = HvdcTopologySummary(
        family="lcc",
        polarity="bipolar",
        terminal_count=2,
        breaker_protection_present=False,
        dc_line_present=True,
        confidence=1.0,
        return_mode="earth_return",
        return_path_status="verified",
        return_path=(path,),
        pole_roles={"positive": source},
        neutral_assets=(source,),
        mode_evidence=("closed return graph",),
        evidence=("Rectifier",),
        unresolved_questions=(),
    )

    encoded = json.dumps(asdict(summary))
    assert "earth_return" in encoded
    assert asdict(path)["closed"] is True
~~~

- [ ] **Step 2: Run the focused test and observe the failure**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_model.py -q
~~~

Expected: FAIL because HvdcReturnPath is not defined and HvdcTopologySummary has no return fields.

- [ ] **Step 3: Add the minimal immutable records**

在 pscad_mcp/hvdc/models.py 中，在 HvdcAsset 前后保持现有 dataclass 风格，加入：

~~~python
@dataclass(frozen=True)
class HvdcReturnPath:
    mode: str
    segments: tuple[HvdcSourceRef, ...] = ()
    endpoints: tuple[HvdcSourceRef, ...] = ()
    closed: bool = False
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
~~~

将 HvdcTopologySummary 扩展为：

~~~python
@dataclass(frozen=True)
class HvdcTopologySummary:
    family: str
    polarity: str
    terminal_count: int | None
    breaker_protection_present: bool
    dc_line_present: bool
    confidence: float
    return_mode: str = "unknown"
    return_path_status: str = "incomplete"
    return_path: tuple[HvdcReturnPath, ...] = ()
    pole_roles: dict[str, HvdcSourceRef] = field(default_factory=dict)
    neutral_assets: tuple[HvdcSourceRef, ...] = ()
    mode_evidence: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
~~~

默认值保证现有 classifier 调用保持兼容。

- [ ] **Step 4: Add the stable error message**

在 pscad_mcp/core/service.py 的 HVDC 错误文案映射中加入 HVDC_RETURN_PATH_UNRESOLVED：

~~~python
"HVDC_RETURN_PATH_UNRESOLVED": (
    "The LCC return path is missing, open, or supported by conflicting evidence.",
    "Inspect the return-path evidence and provide a project-qualified profile.",
),
~~~

- [ ] **Step 5: Run the focused test and existing model tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_model.py tests/test_hvdc_serialization.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit the contract change**

~~~powershell
git add pscad_mcp/hvdc/models.py pscad_mcp/core/service.py tests/test_hvdc_return_path_model.py
git commit -m "feat: add HVDC return path domain contracts"
~~~

---

### Task 2: 提取端口和连接证据

**Files:**
- Modify: pscad_mcp/hvdc/models.py
- Modify: pscad_mcp/hvdc/scanner.py
- Test: tests/test_hvdc_return_path_model.py
- Test: tests/test_hvdc_lcc_earth_return_classifier.py

- [ ] **Step 1: Write the failing connection extraction test**

追加：

~~~python
from pathlib import Path

from pscad_mcp.hvdc.scanner import scan_project


def test_scanner_preserves_connection_evidence(tmp_path: Path):
    source = tmp_path / "case.pscx"
    source.write_text(
        """<project version='4.6.2'>
          <canvas name='Main'>
            <component id='1' name='Neutral' definition='NeutralBus'>
              <port id='n1' name='N'/>
            </component>
            <component id='2' name='Electrode' definition='EarthElectrode'>
              <port id='e1' name='E'/>
            </component>
            <connection id='c1' from_component='1' from_port='n1'
                        to_component='2' to_port='e1'/>
          </canvas>
        </project>""",
        encoding="utf-8",
    )

    evidence = scan_project(source)
    assert len(evidence.connections) == 1
    connection = evidence.connections[0]
    assert connection.source_component_id == "1"
    assert connection.target_component_id == "2"
    assert connection.source_port == "n1"
    assert connection.target_port == "e1"
~~~

- [ ] **Step 2: Run the test and observe the missing field**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_model.py::test_scanner_preserves_connection_evidence -q
~~~

Expected: FAIL because the evidence model has no connections field.

- [ ] **Step 3: Add the connection record**

在 models.py 中增加：

~~~python
@dataclass(frozen=True)
class HvdcConnectionRecord:
    connection_id: str
    source_component_id: str
    source_port: str
    target_component_id: str
    target_port: str
    source: HvdcSourceRef
    evidence: tuple[str, ...] = ()
~~~

在 HvdcProjectEvidence 增加：

~~~python
connections: tuple[HvdcConnectionRecord, ...] = ()
~~~

- [ ] **Step 4: Parse explicit connection elements without breaking tolerant scanning**

在 scanner.py 新增一个只读 helper：

~~~python
def _connection_records(
    root: ET.Element,
    project_path: Path,
    default_canvas: str,
) -> tuple[HvdcConnectionRecord, ...]:
    records = []
    for index, element in enumerate(root.iter()):
        if _local_name(element.tag) not in {"connection", "wire", "link"}:
            continue
        source_component = _text(
            element.attrib.get("from_component")
            or element.attrib.get("source_component")
            or element.attrib.get("from")
        )
        target_component = _text(
            element.attrib.get("to_component")
            or element.attrib.get("target_component")
            or element.attrib.get("to")
        )
        source_port = _text(
            element.attrib.get("from_port")
            or element.attrib.get("source_port")
        )
        target_port = _text(
            element.attrib.get("to_port")
            or element.attrib.get("target_port")
        )
        if not source_component or not target_component:
            continue
        records.append(
            HvdcConnectionRecord(
                connection_id=_text(element.attrib.get("id")) or f"connection-{index}",
                source_component_id=source_component,
                source_port=source_port,
                target_component_id=target_component,
                target_port=target_port,
                source=HvdcSourceRef(str(project_path), default_canvas),
                evidence=(element.tag,),
            )
        )
    return tuple(records)
~~~

在 scan_project() 返回 HvdcProjectEvidence 时填充 connections=_connection_records(... )。若 PSCX 没有显式 connection 元素，返回空 tuple 并保留原有组件/标签扫描结果。

- [ ] **Step 5: Run scanner regressions**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_model.py tests/test_hvdc_breaker_fixture.py -q
~~~

Expected: PASS, including all pre-existing breaker fixture checks.

- [ ] **Step 6: Commit scanner evidence**

~~~powershell
git add pscad_mcp/hvdc/models.py pscad_mcp/hvdc/scanner.py tests/test_hvdc_return_path_model.py tests/test_hvdc_lcc_earth_return_classifier.py
git commit -m "feat: preserve HVDC return connection evidence"
~~~

---

### Task 3: 实现回流路径图和 LCC 分类

**Files:**
- Create: pscad_mcp/hvdc/return_paths.py
- Modify: pscad_mcp/hvdc/classifier.py
- Test: tests/test_hvdc_lcc_earth_return_classifier.py

- [ ] **Step 1: Write failing path classification tests**

写入四个规则测试：

~~~python
from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.hvdc.scanner import scan_project


def test_classifies_verified_earth_return():
    summary = classify_topology(scan_project(FIXTURE_DIR / "bipolar_earth_return.pscx"))
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.return_mode == "earth_return"
    assert summary.return_path_status == "verified"


def test_classifies_verified_metallic_return():
    summary = classify_topology(scan_project(FIXTURE_DIR / "bipolar_metallic_return.pscx"))
    assert summary.return_mode == "metallic_return"
    assert summary.return_path_status == "verified"


def test_classifies_single_pole_earth_return():
    summary = classify_topology(
        scan_project(FIXTURE_DIR / "positive_pole_outage_earth_return.pscx")
    )
    assert summary.polarity == "bipolar"
    assert summary.return_mode == "earth_return"
    assert "positive" in summary.pole_roles


def test_does_not_guess_when_return_path_is_ambiguous():
    summary = classify_topology(scan_project(FIXTURE_DIR / "ambiguous_return_mode.pscx"))
    assert summary.return_mode == "unknown"
    assert summary.return_path_status == "ambiguous"
    assert summary.unresolved_questions
~~~

- [ ] **Step 2: Run the tests and observe fixture/module failures**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_lcc_earth_return_classifier.py -q
~~~

Expected: FAIL because the fixtures and analyze_return_paths implementation do not exist.

- [ ] **Step 3: Add deterministic return-path analysis**

在 return_paths.py 定义：

~~~python
RETURN_MODES = {"earth_return", "metallic_return", "mixed_transition", "unknown"}
RETURN_STATUSES = {"verified", "incomplete", "ambiguous"}


def analyze_return_paths(evidence: HvdcProjectEvidence) -> tuple[HvdcReturnPath, ...]:
    """Build candidate return paths from explicit connections and named assets.

    Only paths with both endpoint evidence and a closed connection chain are
    verified. Label-only evidence produces an ambiguous or incomplete path.
    """
~~~

实现要求：

- 建立 component id 到 HvdcComponentRecord 的索引；
- 建立无向端口图，保留连接来源；
- 通过 definition/name/label token 分类候选 positive/negative/neutral/electrode/earth/metallic；
- 对 earth path 和 metallic path 分别寻找从整流端 neutral 到逆变端 neutral 的闭合链；
- 只有存在明确端点、完整连接链和足够模式证据时返回 verified；
- 同时存在两个可用模式但缺少开关状态时返回 ambiguous；
- 缺少中间段时返回 incomplete；
- 不使用单一标签直接升级为 verified；
- 返回的每个 segment 和 endpoint 必须引用原始 HvdcSourceRef。

- [ ] **Step 4: Extend classifier without removing generic family detection**

在 classifier.py 保留现有 LCC/VSC/MMC score 逻辑；新增：

~~~python
from .return_paths import analyze_return_paths


def _pole_roles(evidence: HvdcProjectEvidence) -> dict[str, HvdcSourceRef]:
    # Match explicit positive/negative/pole-1/pole-2 tokens, returning only
    # source-backed roles; unresolved roles remain absent.
~~~

将 classify_topology() 的返回值填充：

- return_path 为 analyze_return_paths(evidence)；
- return_mode 为唯一 verified path 的 mode，否则 unknown；
- return_path_status 按 verified/incomplete/ambiguous 汇总；
- pole_roles 只包含证据确认的角色；
- neutral_assets 只包含中性点/中性母线来源；
- mode_evidence 聚合路径和开关证据；
- 缺少正负极、接地极或闭合路径时添加明确 unresolved question。

- [ ] **Step 5: Run classifier and legacy HVDC tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_lcc_earth_return_classifier.py tests/test_hvdc_breaker_fixture.py tests/test_hvdc_tools.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit classifier and path graph**

~~~powershell
git add pscad_mcp/hvdc/return_paths.py pscad_mcp/hvdc/classifier.py tests/test_hvdc_lcc_earth_return_classifier.py
git commit -m "feat: classify LCC return paths from evidence graphs"
~~~

---

### Task 4: 注册独立 LCC earth-return profile

**Files:**
- Modify: pscad_mcp/hvdc/profiles.py
- Create: tests/test_hvdc_lcc_earth_return_profile.py

- [ ] **Step 1: Write profile contract tests**

~~~python
from pscad_mcp.hvdc.profiles import load_profile


def test_lcc_earth_return_profile_is_standalone_and_scoped():
    profile = load_profile("lcc_bipolar_earth_return_v1")
    assert profile["profile_version"] == 2
    assert profile.get("extends") is None
    assert profile["topology_constraints"] == {
        "family": "lcc",
        "polarity": "bipolar",
        "return_mode": "earth_return",
    }
    assert {
        "positive_pole_voltage",
        "negative_pole_voltage",
        "positive_pole_current",
        "negative_pole_current",
        "earth_return_current",
        "earth_return_switch_status",
    } <= set(profile["metric_roles"])
~~~

- [ ] **Step 2: Run the test and observe missing profile failure**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_lcc_earth_return_profile.py -q
~~~

Expected: FAIL with HVDC_PROFILE_NOT_FOUND.

- [ ] **Step 3: Add the standalone v1 profile**

在 _BUILTIN_PROFILES 中增加 lcc_bipolar_earth_return_v1，内容必须：

- profile_version: 2；
- 不设置 extends；
- required_assets 至少包含 positive_pole, negative_pole, neutral_bus, earth_electrode, earth_return；
- topology_constraints 如测试所示；
- mappings 为 14 个 canonical signals；
- command_bindings: []；
- result_channels 仅包含第一阶段需要的 read-only channels；
- 每个结果 selector 明确 units；
- metric_roles 只引用本 profile 的 channels；
- return_path_rules 和 mode_rules 使用可验证的字符串/列表结构，并通过现有 profile schema 校验。

- [ ] **Step 4: Extend profile validation for topology constraints**

在 _validate_profile() 或 v2 validator 中增加：

~~~python
constraints = profile.get("topology_constraints", {})
if not isinstance(constraints, dict):
    raise _invalid("'topology_constraints' must be an object.", name)
for key in ("family", "polarity", "return_mode"):
    value = constraints.get(key)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _invalid(f"topology_constraints.{key} must be a non-empty string.", name)
~~~

对 required_assets 保持现有非空字符串校验，不放宽 profile 安全边界。

- [ ] **Step 5: Run profile compatibility tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_lcc_earth_return_profile.py tests/test_hvdc_profiles_v2.py tests/test_hvdc_profile.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit profile**

~~~powershell
git add pscad_mcp/hvdc/profiles.py tests/test_hvdc_lcc_earth_return_profile.py
git commit -m "feat: add scoped LCC earth-return profile"
~~~

---

### Task 5: 接入 mapping 和 inspect/validate

**Files:**
- Modify: pscad_mcp/hvdc/mappings.py
- Modify: pscad_mcp/hvdc/service.py
- Modify: tests/test_hvdc_return_path_validation.py
- Modify: tests/test_hvdc_tools.py

- [ ] **Step 1: Write failing validation tests**

~~~python
def test_validate_lcc_earth_return_accepts_verified_fixture():
    result = HvdcDomainService().validate_project(
        str(FIXTURE_DIR / "bipolar_earth_return.pscx"),
        profile="lcc_bipolar_earth_return_v1",
    )
    assert result["valid"] is True
    assert result["topology"]["return_mode"] == "earth_return"
    assert result["topology"]["return_path_status"] == "verified"


def test_validate_lcc_earth_return_reports_unresolved_path():
    result = HvdcDomainService().validate_project(
        str(FIXTURE_DIR / "incomplete_return_path.pscx"),
        profile="lcc_bipolar_earth_return_v1",
    )
    assert result["valid"] is False
    assert any(
        error["code"] == "HVDC_RETURN_PATH_UNRESOLVED"
        for error in result["errors"]
    )
~~~

- [ ] **Step 2: Run the tests and observe missing integration**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_validation.py -q
~~~

Expected: FAIL because validation does not inspect return_path_status or profile topology constraints.

- [ ] **Step 3: Make mapping resolution recognize source-backed roles**

在 mappings.py 保留现有 alias matching；增加 profile-aware checks：

- source kind 必须满足 mapping 的 source_kinds；
- units 与 profile selector 不一致时产生 status="conflict"；
- direction 缺失时产生 status="unresolved"；
- 对 earth_return_current 和 metallic_return_current 保留来源及位置；
- 不为缺失 channel 生成零值或虚构来源。

- [ ] **Step 4: Add topology-aware service validation**

在 HvdcDomainService.validate_project() 中，在现有 required assets/mappings 检查之后增加：

~~~python
constraints = profile.get("topology_constraints", {})
topology = classify_topology(evidence)
if constraints.get("family") and topology.family != constraints["family"]:
    errors.append({
        "code": "HVDC_TOPOLOGY_AMBIGUOUS",
        "message": "Project family does not satisfy the selected LCC earth-return profile.",
    })
if constraints.get("polarity") and topology.polarity != constraints["polarity"]:
    errors.append({
        "code": "HVDC_TOPOLOGY_AMBIGUOUS",
        "message": "Project polarity does not satisfy the selected profile.",
    })
if constraints.get("return_mode") == "earth_return":
    if topology.return_path_status == "ambiguous":
        errors.append({
            "code": "HVDC_TOPOLOGY_AMBIGUOUS",
            "message": "Earth-return and metallic-return evidence conflict.",
        })
    elif topology.return_path_status != "verified":
        errors.append({
            "code": "HVDC_RETURN_PATH_UNRESOLVED",
            "message": "The earth-return path is not verified.",
        })
~~~

在 inspect_project() 返回的 topology 中通过 asdict(topology) 自动输出新字段，不改变现有外层 keys。

- [ ] **Step 5: Add JSON-safe inspect regression**

在 tests/test_hvdc_tools.py 增加一个调用新 fixture 的测试，验证：

~~~python
result = service.inspect_project(str(path))
json.dumps(result)
assert result["topology"]["return_mode"] in {
    "earth_return", "metallic_return", "mixed_transition", "unknown"
}
~~~

- [ ] **Step 6: Run integration tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_return_path_validation.py tests/test_hvdc_tools.py tests/test_hvdc_breaker_fixture.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit mapping and service integration**

~~~powershell
git add pscad_mcp/hvdc/mappings.py pscad_mcp/hvdc/service.py tests/test_hvdc_return_path_validation.py tests/test_hvdc_tools.py
git commit -m "feat: validate LCC earth-return topology in HVDC service"
~~~

---

### Task 6: 增加回流和极间指标

**Files:**
- Modify: pscad_mcp/hvdc/metrics.py
- Modify: tests/test_hvdc_metrics.py

- [ ] **Step 1: Write failing metric tests**

~~~python
def test_earth_return_metrics_are_unit_aware():
    result = calculate_metrics(
        {
            "time": [0.0, 1.0, 2.0],
            "channels": {
                "positive_pole_current": [1.0, 2.0, 1.0],
                "negative_pole_current": [1.0, 1.0, 1.0],
                "earth_return_current": [0.0, 1.0, 0.5],
            },
        },
        ["earth_return_current_peak", "pole_current_imbalance"],
    )
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["earth_return_current_peak"]["value"] == 1.0
    assert by_name["earth_return_current_peak"]["units"] == "kA"
    assert by_name["pole_current_imbalance"]["value"] == 1.0


def test_return_closure_requires_explicit_directional_channels():
    result = calculate_metrics(
        {
            "time": [0.0, 1.0],
            "channels": {
                "positive_pole_current": [1.0, 1.0],
                "negative_pole_current": [1.0, 1.0],
            },
        },
        ["return_current_closure_error"],
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
~~~

- [ ] **Step 2: Run the tests and observe unsupported metrics**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_metrics.py -k "earth_return or closure" -q
~~~

Expected: FAIL because requested metrics are currently treated as missing channels.

- [ ] **Step 3: Add explicit metric implementations**

在 calculate_metrics() 的 metric dispatch 中加入：

- earth_return_current_peak：最大绝对值，units kA；
- earth_return_current_rms：RMS，units kA；
- metallic_return_current_peak：最大绝对值，units kA；
- pole_current_imbalance：max(abs(abs(Ip)-abs(In)))，units kA；
- pole_voltage_imbalance：max(abs(abs(Vp)-abs(Vn)))，units kV；
- return_current_closure_error：要求 profile 提供 return_current_signs，按显式方向求逐点代数和的最大绝对值；
- return_mode_consistency：要求 profile 提供模式开关与回流通道，验证模式状态和非零回流通道是否一致。

所有实现必须通过现有 _normalize()，因此时间轴、长度、数值和有限性校验继续有效。缺少通道或方向配置时调用 unavailable() 或 _invalid()，不得推断符号。

- [ ] **Step 4: Run all metric regressions**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_metrics.py tests/test_hvdc_vsc_mmc_profiles.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit metrics**

~~~powershell
git add pscad_mcp/hvdc/metrics.py tests/test_hvdc_metrics.py
git commit -m "feat: add LCC return-path metrics"
~~~

---

### Task 7: 建立五个结构 fixture 和完整回归

**Files:**
- Create: tests/fixtures/hvdc/lcc_earth_return/bipolar_earth_return.pscx
- Create: tests/fixtures/hvdc/lcc_earth_return/bipolar_metallic_return.pscx
- Create: tests/fixtures/hvdc/lcc_earth_return/positive_pole_outage_earth_return.pscx
- Create: tests/fixtures/hvdc/lcc_earth_return/incomplete_return_path.pscx
- Create: tests/fixtures/hvdc/lcc_earth_return/ambiguous_return_mode.pscx
- Create: tests/test_hvdc_lcc_earth_return_fixture.py

- [ ] **Step 1: Create the minimal verified earth-return fixture**

使用显式 canvas、component、port、connection 元素，包含：

- Rectifier、Inverter；
- PositivePole、NegativePole；
- RectifierNeutral、InverterNeutral；
- RectifierEarthElectrode、InverterEarthElectrode；
- EarthReturnLine；
- EarthReturnSwitch 状态 closed；
- 14 个 canonical signal label/measurement 组件；
- 从整流中性点到逆变中性点的完整 earth path connection chain。

- [ ] **Step 2: Create the metallic-return, single-pole, incomplete, and ambiguous fixtures**

具体差异必须可由结构证据表达：

- metallic fixture：使用 MetallicReturnLine 和 closed metallic switch，earth switch open；
- single-pole fixture：positive pole status open，negative pole and earth path active；
- incomplete fixture：缺少一段 earth path connection；
- ambiguous fixture：earth and metallic paths both present，两个 switch 都缺少可确认状态。

- [ ] **Step 3: Add table-driven fixture tests**

~~~python
import pytest

@pytest.mark.parametrize(
    ("filename", "mode", "status"),
    [
        ("bipolar_earth_return.pscx", "earth_return", "verified"),
        ("bipolar_metallic_return.pscx", "metallic_return", "verified"),
        ("positive_pole_outage_earth_return.pscx", "earth_return", "verified"),
        ("incomplete_return_path.pscx", "unknown", "incomplete"),
        ("ambiguous_return_mode.pscx", "unknown", "ambiguous"),
    ],
)
def test_lcc_earth_return_fixture_matrix(filename, mode, status):
    summary = classify_topology(scan_project(FIXTURE_DIR / filename))
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.return_mode == mode
    assert summary.return_path_status == status
~~~

- [ ] **Step 4: Verify exact source retention**

对 verified earth-return fixture 断言每个 return path segment 的 source.project_path、canvas_name 和 component_id 非空，且 JSON 序列化成功。

- [ ] **Step 5: Run the fixture matrix**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_hvdc_lcc_earth_return_fixture.py tests/test_hvdc_lcc_earth_return_classifier.py tests/test_hvdc_return_path_validation.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit fixtures and fixture tests**

~~~powershell
git add tests/fixtures/hvdc/lcc_earth_return tests/test_hvdc_lcc_earth_return_fixture.py
git commit -m "test: add LCC bipolar return-path fixtures"
~~~

---

### Task 8: 兼容性验证、文档和交付检查

**Files:**
- Modify: README.md
- Modify: docs/zh-CN/README.md
- Modify: tests/test_tool_inventory.py only if the new profile changes no tool count; do not change expected count otherwise.

- [ ] **Step 1: Document the read-only profile and its limits**

在 README 的 HVDC profile 部分加入：

- lcc_bipolar_earth_return_v1 是只读 inspect/validate profile；
- 它不提供 command bindings；
- 它不执行回流方式切换；
- 证据不足时返回 HVDC_RETURN_PATH_UNRESOLVED 或 INCOMPLETE_ANALYSIS；
- 第一阶段仅支持 LCC 双极，不代表 VSC/MMC 支持。

- [ ] **Step 2: Run focused and compatibility test suites**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest `
  tests/test_hvdc_tools.py `
  tests/test_hvdc_metrics.py `
  tests/test_hvdc_vsc_mmc_profiles.py `
  tests/test_hvdc_timing.py `
  tests/test_hvdc_preflight.py `
  tests/test_hvdc_serialization.py `
  tests/test_hvdc_breaker_fixture.py `
  tests/test_hvdc_return_path_model.py `
  tests/test_hvdc_lcc_earth_return_classifier.py `
  tests/test_hvdc_lcc_earth_return_profile.py `
  tests/test_hvdc_return_path_validation.py `
  tests/test_hvdc_lcc_earth_return_fixture.py `
  tests/test_tool_inventory.py `
  tests/test_tool_backend_matrix.py -q
~~~

Expected: all selected tests pass; tool count remains 77.

- [ ] **Step 3: Run package syntax and diff checks**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m compileall pscad_mcp
git diff --check
~~~

Expected: compileall completes without errors and diff check produces no output.

- [ ] **Step 4: Run the full suite and record unrelated collection blockers**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q
~~~

Expected: all collected tests pass, or any pre-existing collection blockers are recorded exactly. Do not claim repository-wide green if imports such as lcc_builder_fakes or test_lcc_real_acceptance remain unavailable.

- [ ] **Step 5: Update the implementation summary**

Record:

- profile name and version;
- supported modes and fixture names;
- new error code;
- selected test command and result;
- explicit statement that no scenario mutation was added;
- any full-suite collection blockers.

- [ ] **Step 6: Commit documentation and final verification**

~~~powershell
git add README.md docs/zh-CN/README.md
git commit -m "docs: describe LCC bipolar earth-return inspection"
git status --short --branch
~~~

Expected: working tree clean except for unrelated user changes, and all commits remain isolated by root cause.

## Self-review checklist

- **Spec coverage:** Tasks 1–3 cover the domain model, scanner evidence, return-path graph, pole roles, and ambiguity handling. Task 4 covers the standalone scoped profile. Task 5 covers mappings and inspect/validate. Task 6 covers the specified metrics. Tasks 7–8 cover fixtures, errors, compatibility, documentation, and verification.
- **Placeholder scan:** Task steps contain concrete paths, commands, expected outcomes, and no deferred implementation instructions.
- **Type consistency:** HvdcReturnPath, HvdcConnectionRecord, and the extended HvdcTopologySummary are defined in Task 1/2 before consumers use them. analyze_return_paths() is defined in Task 3 before classifier integration. The profile name is identical in Tasks 4–8.
- **Scope:** The plan is limited to LCC bipolar earth/metallic return inspection and validation. Scenario mutation and VSC/MMC work remain explicitly outside this plan.
