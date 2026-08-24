import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.parametric_executor import (
    apply_template_bindings,
    execute_parametric_template,
)


TEMPLATE = """<project name=\"Fixture\"><definitions><Definition name=\"Main\"><form><parameter name=\"Freq\" value=\"50.0 Hz\" /></form></Definition></definitions></project>"""


def _plan(tmp_path: Path, *, bindings):
    source = tmp_path / "source.pscx"
    source.write_text(TEMPLATE, encoding="utf-8")
    staging = tmp_path / "workspace" / "stage.pscx"
    return {
        "template": {"path": str(source), "fingerprint": hashlib.sha256(source.read_bytes()).hexdigest()},
        "project": {"staging_path": str(staging), "target_path": str(tmp_path / "final.pscx")},
        "bindings": bindings,
    }, source, staging


def test_apply_template_bindings_replaces_one_explicit_attribute_and_preserves_source(tmp_path):
    plan, source, staging = _plan(
        tmp_path,
        bindings=[
            {
                "logical_parameter": "frequency_hz",
                "selector": "/project/definitions/Definition/form/parameter[@name='Freq']",
                "attribute": "value",
                "value": "60.0 Hz",
                "units": "Hz",
            }
        ],
    )

    evidence = apply_template_bindings(plan)

    assert source.read_text(encoding="utf-8") == TEMPLATE
    assert staging.read_text(encoding="utf-8").find('value="60.0 Hz"') >= 0
    assert evidence["source_sha256"] == plan["template"]["fingerprint"]
    assert evidence["staging_sha256"] == hashlib.sha256(staging.read_bytes()).hexdigest()
    assert evidence["modified_paths"] == [
        "/project/definitions/Definition/form/parameter[@name='Freq']/@value"
    ]
    assert evidence["read_back"] == [
        {
            "logical_parameter": "frequency_hz",
            "role": None,
            "selector": "/project/definitions/Definition/form/parameter[@name='Freq']",
            "attribute": "value",
            "units": "Hz",
            "expected_match_count": 1,
            "value": "60.0 Hz",
        }
    ]


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        [{"logical_parameter": "frequency_hz", "selector": "/missing", "attribute": "value", "value": "60 Hz", "units": "Hz"}],
        [
            {"logical_parameter": "frequency_hz", "selector": "/project/definitions/Definition/form/parameter", "attribute": "value", "value": "60 Hz", "units": "Hz"},
            {"logical_parameter": "frequency_hz", "selector": "/project/definitions/Definition/form/parameter[@name='Freq']", "attribute": "value", "value": "60 Hz", "units": "Hz"},
        ],
    ],
)
def test_apply_template_bindings_rejects_missing_ambiguous_or_duplicate_bindings(tmp_path, bindings):
    plan, source, staging = _plan(tmp_path, bindings=bindings)

    with pytest.raises(BackendError) as raised:
        apply_template_bindings(plan)

    assert raised.value.code == "LCC_PARAMETER_BINDING_UNAVAILABLE"
    assert not staging.exists()
    assert source.read_text(encoding="utf-8") == TEMPLATE


def test_executor_validates_bindings_before_calling_pscad(tmp_path):
    plan, source, staging = _plan(
        tmp_path,
        bindings=[
            {"logical_parameter": "frequency_hz", "selector": "/missing", "attribute": "value", "value": "60 Hz", "units": "Hz"}
        ],
    )

    class Service:
        def __init__(self):
            self.calls = []

        async def load_projects(self, filenames):
            self.calls.append(("load_projects", filenames))

    service = Service()
    with pytest.raises(BackendError) as raised:
        __import__("asyncio").run(
            execute_parametric_template(plan, service, tmp_path, build_id="b1")
        )

    assert raised.value.code == "LCC_PARAMETER_BINDING_UNAVAILABLE"
    assert service.calls == []
    assert not staging.exists()
