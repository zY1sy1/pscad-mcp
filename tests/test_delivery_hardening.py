from __future__ import annotations

import importlib
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI
    import tomli as tomllib


ROOT = Path(__file__).parents[1]


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_package_metadata_declares_release_version_and_dev_dependencies():
    project = _read_toml(ROOT / "pyproject.toml")["project"]

    assert project["version"] == "0.2.0"
    assert project["requires-python"] == ">=3.10"
    requirements = project["optional-dependencies"]["dev"]
    assert any(item.startswith("pytest") for item in requirements)
    assert "ruff>=0.12,<1" in requirements
    assert any("tomli" in item for item in requirements)
    assert importlib.import_module("pscad_mcp").__version__ == "0.2.0"


def test_portable_config_example_describes_stdio_and_pscad_environment():
    config = _read_toml(ROOT / "config.example.toml")
    server = config["mcp_servers"]["pscad"]

    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "pscad_mcp.main"]
    assert server["command"]
    for key in (
        "PSCAD_MCP_BACKEND",
        "PSCAD_MCP_VERSION",
        "PSCAD_MCP_X64",
        "PSCAD_MCP_WORKSPACE",
        "PSCAD_MCP_LEARNING_ENABLED",
        "PSCAD_MCP_LEARNING_RETENTION_DAYS",
        "PSCAD_MCP_LEARNING_MAX_EVENTS",
    ):
        assert key in server["env"]


def test_release_notes_cover_all_approved_batches():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "0.2.0" in changelog
    for phrase in (
        "Delivery hardening",
        "NOT_LICENSED",
        "PSOUT",
        "parameter-grid",
    ):
        assert phrase in changelog


def test_readmes_describe_compatible_mcp_hardening_in_both_languages():
    required = (
        "get_pscad_capabilities",
        "PSCAD_MCP_TOOL_PROFILE",
        "PSCAD_MCP_DOCUMENTATION_DIR",
        "97",
        "offset",
        "limit",
        "pscad-docs://modules/",
        "PSCAD 5.x",
        "contract-tested",
    )

    for relative in ("README.md", "docs/zh-CN/README.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for value in required:
            assert value in text, f"{relative} is missing {value!r}"

    language_contracts = {
        "README.md": (
            "96 compatibility/domain tools plus one always-on capability tool",
            "`full` remains the unchanged default",
            "opt-in",
            "fail server startup",
            "optional",
            "local state",
            "absolute path",
            "contract-tested only",
        ),
        "docs/zh-CN/README.md": (
            "96 个兼容/领域工具 + 1 个始终注册的能力工具",
            "`full` 保持不变的默认值",
            "显式启用",
            "启动失败",
            "可选",
            "本地状态",
            "绝对路径",
            "contract-tested only",
        ),
    }
    for relative, phrases in language_contracts.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in text, f"{relative} is missing {phrase!r}"


def test_readmes_document_parametric_mmc_contract_and_limits():
    tools = (
        "audit_mmc_template", "derive_mmc_parameters", "plan_parametric_mmc_model",
        "build_parametric_mmc_model", "get_parametric_mmc_build_status",
        "recommend_mmc_simulation", "validate_mmc_model",
    )
    shared = (
        "97", "detailed_pwm", "average_value", "PSCAD 4.6.2",
        "intrinsic_dc_fault_blocking=false", "individual_cell_balance_not_modeled",
        "device_stress_not_modeled", "switching_harmonics_not_modeled",
        "thermal_not_modeled", "inspected", "designed", "planned", "built",
        "simulated", "accepted", "NOT_RUN_ON_INTEGRATED_COMMIT", "four",
        "H_MMC_Mono_DC.pscx", "intermediate.pslx", "_scenario_source.pscx",
        "derived_project",
    )
    for relative in ("README.md", "docs/zh-CN/README.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for tool in tools:
            assert tool in text, f"{relative} is missing {tool}"
        for phrase in shared:
            assert phrase in text, f"{relative} is missing {phrase}"
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")
    for phrase in ("read-only official template", "source immutability", "preplanned candidates", "ModelsInProgress"):
        assert phrase in english
    for phrase in ("官方模板只读", "源文件不可变", "预规划候选", "ModelsInProgress"):
        assert phrase in chinese
