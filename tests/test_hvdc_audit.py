import hashlib

from pscad_mcp.hvdc.audit import file_evidence, profile_evidence


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
