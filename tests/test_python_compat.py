from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_python_3_10_dev_environment_declares_tomli_fallback():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    dependencies = document["project"]["optional-dependencies"]["dev"]

    assert any(
        dependency.startswith("tomli>=2,<3")
        and "python_version < '3.11'" in dependency
        for dependency in dependencies
    )
