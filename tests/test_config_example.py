from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def _learning_section(text, heading):
    pattern = rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing learning section {heading!r}"
    return " ".join(match.group(1).split())


def test_codex_config_template_is_portable():
    path = Path(__file__).parents[1] / "config.example.toml"
    path_text = path.read_text(encoding="utf-8")
    config = tomllib.loads(path_text)
    server = config["mcp_servers"]["pscad"]

    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "pscad_mcp.main"]
    assert "tools" not in server
    assert "PSCAD_MCP_BACKEND" in server["env"]
    assert server["env"]["PSCAD_MCP_ALLOW_UNSCOPED_PATHS"] == "false"
    assert server["env"]["PSCAD_MCP_LEARNING_ENABLED"] == "true"
    assert server["env"]["PSCAD_MCP_LEARNING_RETENTION_DAYS"] == "90"
    assert server["env"]["PSCAD_MCP_LEARNING_MAX_EVENTS"] == "20000"
    assert "PSCAD_MCP_LEARNING_DB" not in server["env"]
    assert "PSCAD_MCP_LEARNING_BACKLOG" not in server["env"]
    assert r"D:\pscad-mcp" not in path_text
    assert r"D:\PSCAD-Workspace" not in path_text


def test_workspace_safety_is_documented_in_both_languages():
    root = Path(__file__).parents[1]
    for relative in ("README.md", "docs/zh-CN/README.md"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "PSCAD_MCP_ALLOW_UNSCOPED_PATHS" in text
        assert "WORKSPACE_NOT_CONFIGURED" in text


def test_readme_copilot_configuration_includes_workspace_environment():
    text = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert '"env": {' in text
    assert '"PSCAD_MCP_WORKSPACE": "C:\\\\path\\\\to\\\\PSCAD-Workspace"' in text
    assert '"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false"' in text
    assert '"PSCAD_MCP_LEARNING_ENABLED": "true"' in text


def test_learning_controls_and_inventory_are_documented_in_both_languages():
    root = Path(__file__).parents[1]
    required = (
        "PSCAD_MCP_LEARNING_ENABLED",
        "PSCAD_MCP_LEARNING_DB",
        "PSCAD_MCP_LEARNING_BACKLOG",
        "PSCAD_MCP_LEARNING_RETENTION_DAYS",
        "PSCAD_MCP_LEARNING_MAX_EVENTS",
        "improvement-backlog.md",
        "record_goal_failure",
        "review_improvement_backlog",
        "clear_learning_history",
        "90",
    )
    language_phrases = {
        "README.md": (
            "local-only",
            "scalar metadata",
            "parameters",
            "results",
            "project paths",
            "prompts",
            "exception text",
            "error details",
            "tracebacks",
            "generated",
            "improvement-backlog.md",
            "manual edits",
            "overwritten",
            "Successful operation",
            "remains silent",
            "critical",
            "correctness",
            "partial-mutation",
            "recovery",
            "reminder",
            "collapsed",
            "record_goal_failure",
            "audit entry",
            "separately created",
            "Codex desktop heartbeat",
            "Monday",
            "09:00",
            "Asia/Shanghai",
            "MCP server",
            "installer",
            "do not create",
            "implicitly",
            "machine",
            "Codex desktop app",
            "running",
            "explicit confirmation",
        ),
        "docs/zh-CN/README.md": (
            "本机",
            "有界标量元数据",
            "参数",
            "结果",
            "工程路径",
            "提示词",
            "异常文本",
            "错误详情",
            "traceback",
            "生成的 Markdown 投影",
            "improvement-backlog.md",
            "手工编辑",
            "被覆盖",
            "正常成功操作",
            "保持静默",
            "critical 提醒",
            "正确性",
            "部分变更",
            "恢复风险",
            "折叠的",
            "record_goal_failure",
            "审计条目",
            "必须单独创建",
            "Codex desktop heartbeat",
            "每周一",
            "09:00 Asia/Shanghai",
            "MCP server",
            "installer",
            "不会隐式创建",
            "机器开机",
            "Codex desktop app",
            "正在运行",
            "显式确认",
        ),
    }
    inventory_fields = {
        "README.md": (
            "90 = 60 generic tools",
            "10 HVDC tools",
            "3 learning tools",
            "7 parametric MMC tools",
        ),
        "docs/zh-CN/README.md": (
            "90 = 60 个通用工具 + 10 个 HVDC 工具 + 3 个学习工具 + 4 个固定 CIGRE LCC 工具 + 6 个参数化 LCC 工具 + 7 个参数化 MMC 工具",
        ),
    }
    headings = {
        "README.md": "Silent local learning",
        "docs/zh-CN/README.md": "静默本地学习",
    }
    for relative, phrases in language_phrases.items():
        text = (root / relative).read_text(encoding="utf-8")
        for value in required:
            assert value in text, f"{relative} is missing {value!r}"
        normalized_text = " ".join(text.split())
        for value in inventory_fields[relative]:
            assert value in normalized_text, (
                f"{relative} is missing inventory field {value!r}"
            )
        section = _learning_section(text, headings[relative])
        for value in phrases:
            assert value in section, f"{relative} learning section is missing {value!r}"
