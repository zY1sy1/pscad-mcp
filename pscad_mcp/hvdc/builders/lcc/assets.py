"""Hash-verified packaged assets for the CIGRE LCC builder."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ....core.backend.base import BackendError
from .models import LccBlueprint
from .schema import parse_blueprint


_SUPPORTED_NAME = "cigre_lcc_monopole_v1"
_SUPPORTED_PSCAD_VERSION = "4.6.2"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class LccAssetSet:
    name: str
    schema_version: int
    pscad_version: str
    companion_library: str
    blueprint: LccBlueprint
    catalog: dict[str, Any]
    acceptance: dict[str, Any]
    golden: dict[str, Any]
    provenance: str
    hashes: dict[str, str]
    library_bytes: bytes
    files: dict[str, bytes]
    root: None = None


def _asset_error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Unable to read asset '{path}'.",
            "load_lcc_asset_set",
            path=str(path),
        ) from error
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _manifest_object(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest is missing.",
            "load_lcc_asset_set",
            path=str(path),
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest is not valid JSON.",
            "load_lcc_asset_set",
            path=str(path),
        ) from error
    if not isinstance(value, dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest must be a JSON object.",
            "load_lcc_asset_set",
        )
    return value


def _relative_child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "Manifest paths must be non-empty strings.",
            "load_lcc_asset_set",
            path=repr(relative),
        )
    if relative == "manifest.json" or "\\" in relative:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' is not a canonical relative path.",
            "load_lcc_asset_set",
            path=relative,
        )
    posix = PurePosixPath(relative)
    if posix.is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in posix.parts:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' escapes the asset root.",
            "load_lcc_asset_set",
            path=relative,
        )
    root_resolved = root.resolve()
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' escapes the asset root.",
            "load_lcc_asset_set",
            path=relative,
        ) from error
    return candidate


def _manifest_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    configured = [key for key in ("hashes", "files") if key in manifest]
    if len(configured) != 1 or not isinstance(manifest[configured[0]], dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The manifest must contain exactly one hashes object.",
            "load_lcc_asset_set",
        )
    hashes: dict[str, str] = {}
    for relative, digest in manifest[configured[0]].items():
        if not isinstance(relative, str) or not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "Manifest hashes must be lowercase SHA-256 strings.",
                "load_lcc_asset_set",
                path=repr(relative),
            )
        _relative_child(Path(manifest["__root__"]), relative)
        hashes[relative] = digest
    return hashes


def _json_record(files: dict[str, bytes], relative: str) -> dict[str, Any]:
    try:
        value = json.loads(files[relative].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset '{relative}' is not valid UTF-8 JSON.",
            "load_lcc_asset_set",
            path=relative,
        ) from error
    if not isinstance(value, dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset '{relative}' must contain a JSON object.",
            "load_lcc_asset_set",
            path=relative,
        )
    return value


def load_asset_set(asset_root: str | Path) -> LccAssetSet:
    """Load an asset directory only after its complete manifest is verified."""

    root = Path(asset_root).expanduser().resolve()
    if not root.is_dir():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset root is not a directory.",
            "load_lcc_asset_set",
            root=str(root),
        )
    manifest = _manifest_object(root)
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest schema version must be 1.",
            "load_lcc_asset_set",
            schema_version=schema_version,
        )
    name = manifest.get("name")
    pscad_version = manifest.get("pscad_version")
    companion_library = manifest.get("companion_library")
    if not all(isinstance(value, str) and value.strip() for value in (name, pscad_version, companion_library)):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The manifest name, PSCAD version, and companion library are required.",
            "load_lcc_asset_set",
        )
    if pscad_version != _SUPPORTED_PSCAD_VERSION:
        raise _asset_error(
            "LCC_VERSION_UNSUPPORTED",
            f"LCC assets require PSCAD {_SUPPORTED_PSCAD_VERSION}.",
            "load_lcc_asset_set",
            requested_version=pscad_version,
            supported_version=_SUPPORTED_PSCAD_VERSION,
        )

    manifest["__root__"] = str(root)
    hashes = _manifest_hashes(manifest)
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != "manifest.json"
    }
    if actual_files != set(hashes):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The asset files do not exactly match the manifest.",
            "load_lcc_asset_set",
            missing=sorted(set(hashes) - actual_files),
            unexpected=sorted(actual_files - set(hashes)),
        )

    files: dict[str, bytes] = {}
    for relative, expected in hashes.items():
        path = _relative_child(root, relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                f"Asset '{relative}' does not match its manifest hash.",
                "load_lcc_asset_set",
                path=relative,
                expected=expected,
                observed=sha256_file(path) if path.is_file() else None,
            )
        files[relative] = path.read_bytes()

    required = {
        "blueprint.json",
        "catalog-pscad-4.6.2.json",
        "acceptance.json",
        "golden.json",
        "PROVENANCE.md",
        companion_library,
    }
    missing_required = sorted(required - set(files))
    if missing_required:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The asset set is missing required files.",
            "load_lcc_asset_set",
            missing=missing_required,
        )
    try:
        provenance = files["PROVENANCE.md"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "PROVENANCE.md must be UTF-8 text.",
            "load_lcc_asset_set",
        ) from error
    blueprint_value = _json_record(files, "blueprint.json")
    blueprint = parse_blueprint(blueprint_value)
    if blueprint.name != name:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The blueprint name does not match the manifest.",
            "load_lcc_asset_set",
            manifest_name=name,
            blueprint_name=blueprint.name,
        )
    return LccAssetSet(
        name=name,
        schema_version=schema_version,
        pscad_version=pscad_version,
        companion_library=companion_library,
        blueprint=blueprint,
        catalog=_json_record(files, "catalog-pscad-4.6.2.json"),
        acceptance=_json_record(files, "acceptance.json"),
        golden=_json_record(files, "golden.json"),
        provenance=provenance,
        hashes=dict(hashes),
        library_bytes=bytes(files[companion_library]),
        files=dict(files),
    )


def load_packaged_asset_set(name: str = _SUPPORTED_NAME) -> LccAssetSet:
    if name != _SUPPORTED_NAME:
        raise _asset_error(
            "LCC_BLUEPRINT_NOT_FOUND",
            f"LCC blueprint '{name}' was not found.",
            "load_packaged_lcc_assets",
            blueprint=name,
        )
    resource = resources.files("pscad_mcp").joinpath("assets", "lcc", name)
    if not resource.is_dir():
        raise _asset_error(
            "LCC_BLUEPRINT_NOT_FOUND",
            f"Packaged LCC blueprint '{name}' is not available.",
            "load_packaged_lcc_assets",
            blueprint=name,
        )
    with resources.as_file(resource) as materialized:
        return load_asset_set(materialized)


def materialize_library(asset_set: LccAssetSet, workspace_root: str | Path) -> Path:
    """Atomically copy the verified companion library into a workspace."""

    workspace = Path(workspace_root).expanduser().resolve()
    library_relative = asset_set.companion_library
    expected = asset_set.hashes.get(library_relative)
    if expected is None:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The companion library is not covered by the asset manifest.",
            "materialize_lcc_library",
            library=library_relative,
        )
    target = workspace / ".pscad-mcp" / "libraries" / Path(library_relative).name
    if target.is_file():
        observed = sha256_file(target)
        if observed == expected:
            return target
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Workspace library '{target}' differs from the verified asset.",
            "materialize_lcc_library",
            path=str(target),
            expected=expected,
            observed=observed,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(asset_set.library_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_file(temporary) != expected:
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "The materialized library failed hash verification.",
                "materialize_lcc_library",
                path=str(temporary),
            )
        temporary.replace(target)
        return target
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

