"""Verify recorded acceptance-file integrity without starting PSCAD or promoting status."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 64 * 1024 * 1024


def _sha256(path: Path) -> str:
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"evidence must be an existing absolute regular file: {path}")
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError(f"evidence cannot use linked paths: {path}")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f"evidence changed while reading: {path}")
    return digest.hexdigest()


def _verify(path_value: Any, expected: Any, files: set[str]) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("evidence path must be nonempty text")
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("evidence must declare a lowercase SHA-256")
    path = Path(path_value)
    if _sha256(path) != expected:
        raise ValueError(f"evidence hash mismatch: {path}")
    files.add(str(path.resolve()))
    return path


def _report(path_value: Any, expected: Any, files: set[str]) -> dict:
    path = _verify(path_value, expected, files)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"report exceeds JSON size limit: {path}")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"report changed while reading: {path}")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError("evidence report must contain an object")
    return value


def _pointer(value: Any, pointer: Any) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("evidence checks require an absolute JSON pointer")
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def audit_inventory(manifest_path: Path, *, checkout_commit: str | None = None) -> dict:
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    scopes = payload.get("scopes")
    if payload.get("schema_version") != 1 or not isinstance(scopes, list) or not scopes:
        raise ValueError("inventory requires schema_version 1 and nonempty scopes")
    results = []
    seen = set()
    for scope in scopes:
        name = scope["scope"]
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("inventory scope identities must be nonempty and unique")
        seen.add(name)
        evidence = scope.get("evidence") or {}
        result = {
            "scope": name,
            "recorded_licensed_status": scope.get("licensed_status"),
            "evidence_commit": evidence.get("commit"),
            "evidence_matches_checkout": bool(checkout_commit) and evidence.get("commit") == checkout_commit,
            "integrity_status": "VERIFIED",
            "verified_files": 0,
            "errors": [],
        }
        files: set[str] = set()
        try:
            if not evidence.get("report_path"):
                if scope.get("licensed_status") == "PASS":
                    raise ValueError("PASS requires a durable report")
                result["integrity_status"] = "NO_DURABLE_REPORT"
            else:
                checks = scope.get("evidence_checks")
                if not isinstance(checks, list) or not checks:
                    raise ValueError("recorded report requires explicit verdict checks")
                report = _report(evidence["report_path"], evidence.get("sha256"), files)
                for check in checks:
                    observed = _pointer(report, check["pointer"])
                    expected = check["equals"]
                    if type(observed) is not type(expected) or observed != expected:
                        raise ValueError(f"report claim mismatch: {check['pointer']}")
                report_commit = report.get("commit") or report.get("code_before", {}).get("commit")
                if report_commit and report_commit != evidence.get("commit"):
                    raise ValueError("report revision differs from recorded evidence commit")
                for child in report.get("reports", {}).values():
                    child_report = _report(child["path"], child["sha256"], files)
                    if child_report.get("status") != child.get("status"):
                        raise ValueError("child report status differs from suite record")
                    revision = child_report.get("code_before", {}).get("commit")
                    if revision and revision != evidence.get("commit"):
                        raise ValueError("child revision differs from recorded evidence commit")
                for path, digest in report.get("accepted_hashes", {}).items():
                    _verify(path, digest, files)
                for linked in scope.get("linked_evidence", []):
                    _verify(linked["path"], linked["sha256"], files)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            result["integrity_status"] = "INVALID"
            result["errors"].append(str(error))
        result["verified_files"] = len(files)
        results.append(result)
    statuses = {item["integrity_status"] for item in results}
    return {
        "schema_version": 1,
        "integrity_status": "INVALID" if "INVALID" in statuses else "INCOMPLETE" if "NO_DURABLE_REPORT" in statuses else "VERIFIED",
        "licensed_acceptance_run": False,
        "release_complete": False,
        "checkout_commit": checkout_commit,
        "note": "File integrity only. Historical evidence retains its original scope and revision; no physical checks were rerun.",
        "scopes": results,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=root / "docs/acceptance-status.json")
    args = parser.parse_args()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
    )
    try:
        result = audit_inventory(args.manifest, checkout_commit=revision.stdout.strip() if revision.returncode == 0 else None)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["integrity_status"] == "INVALID" else 2 if result["integrity_status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
