from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.corpus_models import CorpusSpec
from pscad_mcp.builders.blueprint.corpus_schema import parse_corpus_spec
from pscad_mcp.core.backend.base import BackendError

FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def valid_spec() -> dict:
    return {
        "schema_version": 1,
        "normalization_profile": "pscad-xml-v1",
        "name": "moxing_v1",
        "inclusion_policy": "explicit-entry-points-v1",
        "exclusion_policy": "no-backups-builds-results-v1",
        "entry_points": [
            {
                "project_id": "hvdc-bipolar-1000mw-500kv",
                "basename": "HVDC_Bipolar_1000MW_500kV.pscx",
                "byte_length": 348498,
                "sha256": "159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993",
                "pscad_versions": ["4.6.3"],
                "dependencies": [],
            }
        ],
    }


def assert_spec_error(value: object, code: str = "CORPUS_SPEC_INVALID") -> BackendError:
    with pytest.raises(BackendError) as raised:
        parse_corpus_spec(value)
    assert raised.value.code == code
    return raised.value


def test_parse_corpus_spec_returns_immutable_portable_contract():
    value = valid_spec()

    parsed = parse_corpus_spec(value)

    assert isinstance(parsed, CorpusSpec)
    assert parsed.name == "moxing_v1"
    assert parsed.entry_points[0].basename == "HVDC_Bipolar_1000MW_500kV.pscx"
    assert parsed.entry_points[0].byte_length == 348498
    assert parsed.entry_points[0].sha256 == "159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993"
    assert parsed.to_dict() == value
    assert json.loads(json.dumps(parsed.to_dict(), allow_nan=False)) == value
    with pytest.raises(TypeError):
        parsed.entry_points[0].pscad_versions[0] = "changed"


def test_parse_corpus_spec_copies_input_before_freezing():
    value = valid_spec()
    parsed = parse_corpus_spec(value)

    value["entry_points"][0]["pscad_versions"][0] = "changed"

    assert parsed.entry_points[0].pscad_versions == ("4.6.3",)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("top", "unexpected"),
        ("source", "absolute_path"),
        ("source", "generated_at"),
        ("dependency", "host"),
    ],
)
def test_parse_corpus_spec_rejects_unknown_fields_at_every_level(target, field):
    value = valid_spec()
    value["entry_points"][0]["dependencies"] = [
        {
            "basename": "companion.pslx",
            "byte_length": 17,
            "sha256": "a" * 64,
            "kind": "file",
        }
    ]
    selected = {
        "top": value,
        "source": value["entry_points"][0],
        "dependency": value["entry_points"][0]["dependencies"][0],
    }[target]
    selected[field] = "forbidden"

    assert_spec_error(value)


@pytest.mark.parametrize("schema_version", [0, 3, True, "1"])
def test_parse_corpus_spec_rejects_unknown_or_non_integer_schema_versions(schema_version):
    value = valid_spec()
    value["schema_version"] = schema_version

    code = "CORPUS_SPEC_UNSUPPORTED" if schema_version == 3 else "CORPUS_SPEC_INVALID"
    assert_spec_error(value, code)


def test_parse_v2_spec_binds_definition_sources_by_namespace_and_version():
    value = valid_v2_spec()

    parsed = parse_corpus_spec(value)

    assert parsed.schema_version == 2
    assert parsed.normalization_profile == "pscad-xml-v2"
    assert parsed.definition_sources[0].keys == (("master", "4.6.2"),)
    assert parsed.to_dict() == value


def valid_v2_spec() -> dict:
    value = valid_spec()
    value["schema_version"] = 2
    value["normalization_profile"] = "pscad-xml-v2"
    value["name"] = "fixture_v2"
    value["definition_sources"] = [
        {
            "namespace": "master",
            "basename": "master.pslx",
            "byte_length": 12,
            "sha256": "a" * 64,
            "pscad_versions": ["4.6.2"],
            "policy": "ports-and-classification-v1",
        }
    ]
    value["entry_points"][0].update(
        project_id="minimal", basename="minimal.pscx", byte_length=1, sha256="b" * 64, pscad_versions=["4.6.2"]
    )
    return value


def test_frozen_v1_spec_keeps_v1_shape():
    fixture_path = FIXTURES / "v1_compat" / "source-spec.json"
    value = json.loads(fixture_path.read_text(encoding="ascii"))

    parsed = parse_corpus_spec(value)

    assert parsed.schema_version == 1
    assert parsed.definition_sources == ()
    assert parsed.to_dict() == value


@pytest.mark.parametrize("field", ["namespace", "basename", "byte_length", "sha256", "pscad_versions", "policy"])
def test_parse_v2_spec_rejects_unknown_definition_source_fields(field):
    value = valid_v2_spec()
    value["definition_sources"][0][field + "_extra"] = "forbidden"

    assert_spec_error(value)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("namespace", "../master"),
        ("basename", "folder/master.pslx"),
        ("basename", "master.psmx"),
        ("byte_length", 0),
        ("sha256", "A" * 64),
        ("pscad_versions", []),
        ("pscad_versions", ["4.6.2", "4.6.2"]),
        ("policy", "other-policy"),
    ],
)
def test_parse_v2_spec_rejects_unsafe_definition_source_fields(field, invalid):
    value = valid_v2_spec()
    value["definition_sources"][0][field] = invalid

    assert_spec_error(value)


def test_parse_v2_spec_rejects_duplicate_namespace_version_keys_and_wrong_profile():
    value = valid_v2_spec()
    duplicate = copy.deepcopy(value["definition_sources"][0])
    duplicate["basename"] = "other.pslx"
    value["definition_sources"].append(duplicate)
    assert_spec_error(value)

    value = valid_v2_spec()
    value["normalization_profile"] = "pscad-xml-v1"
    assert_spec_error(value)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("project_id", "../project"),
        ("project_id", ""),
        ("basename", "folder/source.pscx"),
        ("basename", "source.bakx"),
        ("byte_length", 0),
        ("byte_length", True),
        ("sha256", "A" * 64),
        ("sha256", "0" * 63),
        ("pscad_versions", []),
        ("pscad_versions", [""]),
        ("dependencies", {}),
    ],
)
def test_parse_corpus_spec_rejects_unsafe_source_fields(field, invalid):
    value = valid_spec()
    value["entry_points"][0][field] = invalid

    assert_spec_error(value)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("basename", "../companion.pslx"),
        ("basename", "companion.exe"),
        ("byte_length", -1),
        ("sha256", "not-a-hash"),
        ("kind", "directory"),
    ],
)
def test_parse_corpus_spec_rejects_unsafe_dependency_fields(field, invalid):
    value = valid_spec()
    value["entry_points"][0]["dependencies"] = [
        {
            "basename": "companion.pslx",
            "byte_length": 17,
            "sha256": "a" * 64,
            "kind": "file",
        }
    ]
    value["entry_points"][0]["dependencies"][0][field] = invalid

    assert_spec_error(value)


@pytest.mark.parametrize("duplicate", ["project_id", "basename"])
def test_parse_corpus_spec_rejects_duplicate_entry_point_identity(duplicate):
    value = valid_spec()
    second = copy.deepcopy(value["entry_points"][0])
    second["project_id"] = "second-project"
    second["basename"] = "second.pscx"
    second[duplicate] = value["entry_points"][0][duplicate]
    value["entry_points"].append(second)

    assert_spec_error(value)


def test_parse_corpus_spec_rejects_duplicate_versions_and_dependencies():
    value = valid_spec()
    value["entry_points"][0]["pscad_versions"] = ["4.6.2", "4.6.2"]
    assert_spec_error(value)

    value = valid_spec()
    dependency = {
        "basename": "companion.pslx",
        "byte_length": 17,
        "sha256": "a" * 64,
        "kind": "file",
    }
    value["entry_points"][0]["dependencies"] = [dependency, copy.deepcopy(dependency)]
    assert_spec_error(value)
