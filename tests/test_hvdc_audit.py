import hashlib
import asyncio

from pscad_mcp.hvdc.audit import file_evidence, profile_evidence
from pscad_mcp.hvdc.scenarios import _capture_outputs, _update_audit_runtime


def test_file_evidence_is_streamed_and_json_safe(tmp_path):
    path = tmp_path / "result.out"
    path.write_bytes(b"abc")
    evidence = file_evidence(path)
    assert evidence["path"] == str(path.resolve())
    assert evidence["size"] == 3
    assert evidence["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert isinstance(evidence["modified_ns"], int)


def test_profile_hash_is_stable_across_mapping_order():
    left = {"profile_version": 2, "metric_roles": {"b": "2", "a": "1"}}
    right = {"metric_roles": {"a": "1", "b": "2"}, "profile_version": 2}
    assert profile_evidence("case", left)["sha256"] == profile_evidence("case", right)["sha256"]


def test_profile_evidence_retains_profile_version():
    evidence = profile_evidence("case", {"profile_version": 2})
    assert evidence["version"] == 2


def test_audit_runtime_contains_results_metrics_and_run_settings():
    class Backend:
        name = "fake"
        version = "1.2"

    class Service:
        backend_service = Backend()

    record = {
        "audit": {},
        "timing_basis": {"mode": "native"},
        "containment": {"status": "terminal"},
        "pending_operations": [],
        "partial_completion": {},
        "project_status": {"status": "completed"},
        "preflight": {"resolved_commands": []},
        "resolved_channels": [{"canonical": "dc_voltage_breaker"}],
        "metrics": [{"name": "dc_power", "status": "derived"}],
        "run": {"timeout_s": 10},
        "warnings": [{"code": "example"}],
    }

    _update_audit_runtime(Service(), record)

    assert record["audit"]["result_bindings"] == [{"canonical": "dc_voltage_breaker"}]
    assert record["audit"]["metrics"] == [{"name": "dc_power", "status": "derived"}]
    assert record["audit"]["run"] == {"timeout_s": 10}
    assert record["audit"]["warnings"] == [{"code": "example"}]


def test_audit_runtime_preserves_hash_warnings_and_normalizes_tuples():
    class Backend:
        name = "fake"
        version = "1.2"

    class Service:
        backend_service = Backend()

    record = {
        "audit": {"warnings": [{"code": "HVDC_AUDIT_HASH_FAILED"}]},
        "timing_basis": {},
        "containment": {},
        "pending_operations": [],
        "partial_completion": {},
        "project_status": {},
        "preflight": {},
        "resolved_channels": [],
        "metrics": [{"source_channels": ("v", "i")}],
        "run": {},
        "warnings": [{"code": "SCENARIO_WARNING"}],
    }

    _update_audit_runtime(Service(), record)

    assert record["audit"]["warnings"] == [
        {"code": "HVDC_AUDIT_HASH_FAILED"},
        {"code": "SCENARIO_WARNING"},
    ]
    assert record["audit"]["metrics"][0]["source_channels"] == ["v", "i"]


def test_derived_hash_change_does_not_mark_source_audit_incomplete(tmp_path):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    source.write_text("source", encoding="utf-8")
    derived.write_text("before", encoding="utf-8")

    class Backend:
        pass

    class Service:
        backend_service = Backend()

        @staticmethod
        def _resolve_output_file(value, *, must_exist=False):
            return tmp_path / value

    record = {
        "audit": {
            "complete": True,
            "source": file_evidence(source),
            "derived": file_evidence(derived),
        },
        "output_files": [],
        "warnings": [],
        "pending_operations": [],
        "partial_completion": {},
        "timing_basis": {},
        "containment": {},
        "project_status": {},
        "preflight": {},
    }
    derived.write_text("after", encoding="utf-8")

    asyncio.run(_capture_outputs(Service(), record))

    assert record["audit"]["complete"] is True
    assert record["audit"]["derived_final"]["sha256"] == file_evidence(derived)["sha256"]
    assert not any(item.get("code") == "HVDC_AUDIT_SOURCE_CHANGED" for item in record["audit"].get("warnings", []))
