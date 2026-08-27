from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "topology_truth.py"
SEED = ROOT / "pscad_mcp" / "assets" / "templates" / "empty_case.pscx"
SPEC = importlib.util.spec_from_file_location("topology_truth", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
topology_truth = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = topology_truth
SPEC.loader.exec_module(topology_truth)


def test_truth_module_has_no_topology_implementation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith("pscad_mcp.topology") for name in imported)


def test_case_recipes_are_complete_and_have_exact_scale_counts():
    cases = topology_truth.case_recipes()
    assert [case.name for case in cases] == [
        "ordinary",
        "seeded-defects",
        "custom-library",
        "hierarchy-uncertain",
        "scale-500",
        "scale-2000",
    ]
    by_name = {case.name: case for case in cases}
    assert by_name["scale-500"].object_count == 500
    assert by_name["scale-2000"].object_count == 2000
    assert by_name["seeded-defects"].expected_error_codes == (
        "LABEL_CONFLICT",
        "PORT_DIMENSION_MISMATCH",
        "PORT_KIND_MISMATCH",
        "REQUIRED_PORT_UNCONNECTED",
        "WIRE_DANGLING_ENDPOINT",
    )
    assert by_name["hierarchy-uncertain"].expected_unresolved_codes == (
        "hierarchy_boundary_unresolved:Main:410:IN->Main/410:Child:IN",
    )


def test_manifest_is_projected_only_from_declared_truth(tmp_path):
    cases = topology_truth.case_recipes()
    sources = {}
    for case in cases:
        path = tmp_path / case.name / f"{case.name}.pscx"
        path.parent.mkdir()
        path.write_text(f'<project name="{case.name}"/>', encoding="utf-8")
        sources[case.name] = path

    manifest = topology_truth.manifest_from_recipes(cases, sources)

    assert manifest["schema_version"] == 1
    assert [item["name"] for item in manifest["cases"]] == [
        case.name for case in cases
    ]
    scale = next(
        item for item in manifest["cases"] if item["name"] == "scale-2000"
    )
    assert scale["minimum_object_count"] == 2000
    assert Path(scale["source_project"]).is_absolute()
    assert scale["expected_confirmed_edges"] == sorted(
        scale["expected_confirmed_edges"]
    )
    json.dumps(manifest, allow_nan=False)


def test_generation_uses_native_seed_and_audits_every_declared_record(tmp_path):
    cases = topology_truth.case_recipes()
    generated = topology_truth.generate_cases(SEED, tmp_path / "generated", cases)
    assert set(generated) == {case.name for case in cases}
    for case in cases:
        path = generated[case.name]
        root = ET.parse(path).getroot()
        assert root.get("name") == case.name
        assert path.name == f"{case.name}.pscx"
        audit = topology_truth.audit_case(path, case)
        assert audit["object_count"] == case.object_count
        assert audit["confirmed_edges"] == sorted(net.text() for net in case.nets)
        assert len(audit["sha256"]) == 64


def test_audit_rejects_pscad_normalization_drift(tmp_path):
    case = topology_truth.case_recipes()[0]
    path = topology_truth.generate_cases(
        SEED, tmp_path / "generated", (case,)
    )[case.name]
    tree = ET.parse(path)
    wire = next(node for node in tree.getroot().iter() if node.get("id") == "201")
    wire.set("id", "999")
    tree.write(path, encoding="utf-8", xml_declaration=True)

    with pytest.raises(ValueError, match="conductor identities"):
        topology_truth.audit_case(path, case)


def test_generation_is_byte_deterministic(tmp_path):
    cases = topology_truth.case_recipes()
    first = topology_truth.generate_cases(SEED, tmp_path / "first", cases)
    second = topology_truth.generate_cases(SEED, tmp_path / "second", cases)
    assert {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in first.items()
    } == {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in second.items()
    }
