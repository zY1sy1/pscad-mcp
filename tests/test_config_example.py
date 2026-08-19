from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


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
        "73",
    )
    language_phrases = {
        "README.md": (
            "Silent learning is enabled by default and stores local-only scalar metadata.",
            "It never persists parameters, results, project paths, prompts, exception text, error details, or tracebacks.",
            "The Markdown file is a generated projection: it is atomically replaced and manual edits are overwritten.",
            "Successful operation remains silent. Ordinary improvement evidence waits for review; only narrowly defined critical correctness, partial-mutation, or recovery risks may produce one concise reminder",
            "collapsed `record_goal_failure` audit entry",
            "A separately created Codex desktop heartbeat reviews the backlog every Monday at 09:00 in `Asia/Shanghai`.",
            "The MCP server and installer do not create that heartbeat implicitly.",
            "Scheduled work requires the machine and Codex desktop app to be running",
            "Clearing requires explicit confirmation",
            "The complete inventory is 73 = 60 generic tools, 10 HVDC tools, and 3 learning tools.",
        ),
        "docs/zh-CN/README.md": (
            "学习默认开启，只保存本机的有界标量元数据。",
            "不会持久化参数、结果、工程路径、提示词、异常文本、错误详情或 traceback，也不会上传遥测或训练模型。",
            "`improvement-backlog.md` 是生成的 Markdown 投影。该文件会原子替换，手工编辑会被覆盖",
            "正常成功操作保持静默。普通失败证据等待后续审查；只有定义明确的正确性、部分变更或恢复风险才可能产生一次简短 critical 提醒",
            "折叠的 `record_goal_failure` 审计条目",
            "每周一 `09:00 Asia/Shanghai` 的 Codex desktop heartbeat 必须单独创建",
            "MCP server 和 installer 不会隐式创建它",
            "定时工作要求机器开机、Codex desktop app 正在运行",
            "清除历史必须显式确认",
            "完整工具库存为 73 = 60 个通用工具 + 10 个 HVDC 工具 + 3 个学习工具；",
        ),
    }
    for relative, phrases in language_phrases.items():
        text = (root / relative).read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        for value in (*required, *phrases):
            assert value in normalized, f"{relative} is missing {value!r}"
