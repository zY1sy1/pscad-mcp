"""Hash-verified packaged assets for the fixed Stage A MMC builder."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ....core.backend.base import BackendError
from .planner import MmcAssetSet
from .schema import parse_blueprint


_SUPPORTED_NAME = "cigre_b4_p2p_avm_v1"
_SUPPORTED_PSCAD_VERSION = "4.6.2"


def _asset_error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise _asset_error("MMC_ASSET_MISMATCH", "MMC asset path is not a regular file.", "load_mmc_asset_set", path=str(path))
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise _asset_error("MMC_ASSET_MISMATCH", "MMC asset could not be read.", "load_mmc_asset_set", path=str(path)) from error
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset manifest is not valid JSON.", "load_mmc_asset_set", path=str(path)) from error
    if not isinstance(value, dict):
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset manifest must be an object.", "load_mmc_asset_set")
    return value


def _relative_child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative == "manifest.json" or "\\" in relative:
        raise _asset_error("MMC_ASSET_MISMATCH", "Manifest paths must be canonical relative paths.", "load_mmc_asset_set", path=repr(relative))
    posix = PurePosixPath(relative)
    if posix.is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in posix.parts:
        raise _asset_error("MMC_ASSET_MISMATCH", "Manifest path escapes the asset root.", "load_mmc_asset_set", path=relative)
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise _asset_error("MMC_ASSET_MISMATCH", "Manifest path escapes the asset root.", "load_mmc_asset_set", path=relative) from error
    return candidate


def _json_record(files: dict[str, bytes], relative: str) -> dict[str, Any]:
    try:
        value = json.loads(files[relative].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error("MMC_ASSET_MISMATCH", f"MMC asset '{relative}' is not a JSON object.", "load_mmc_asset_set", path=relative) from error
    if not isinstance(value, dict):
        raise _asset_error("MMC_ASSET_MISMATCH", f"MMC asset '{relative}' must be an object.", "load_mmc_asset_set", path=relative)
    return value


def load_asset_set(asset_root: str | Path) -> MmcAssetSet:
    """Load only an exact, hash-verified MMC asset directory."""

    root = Path(asset_root).expanduser().resolve()
    if not root.is_dir():
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset root is not a directory.", "load_mmc_asset_set", root=str(root))
    manifest = _manifest(root)
    if manifest.get("schema_version") != 1:
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset manifest schema version must be 1.", "load_mmc_asset_set")
    pscad_version = manifest.get("pscad_version")
    if pscad_version != _SUPPORTED_PSCAD_VERSION:
        raise _asset_error("MMC_VERSION_UNSUPPORTED", "MMC assets require PSCAD 4.6.2.", "load_mmc_asset_set", observed_version=pscad_version)
    hashes = manifest.get("files")
    if not isinstance(hashes, dict) or not hashes or any(not isinstance(key, str) or not isinstance(value, str) or len(value) != 64 for key, value in hashes.items()):
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset manifest files must be a relative-path to SHA-256 mapping.", "load_mmc_asset_set")
    for relative in hashes:
        _relative_child(root, relative)
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and not path.is_symlink() and path.name != "manifest.json"}
    if actual_files != set(hashes):
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset files do not exactly match the manifest.", "load_mmc_asset_set", missing=sorted(set(hashes) - actual_files), unexpected=sorted(actual_files - set(hashes)))
    files: dict[str, bytes] = {}
    for relative, expected in hashes.items():
        path = _relative_child(root, relative)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset could not be read.", "load_mmc_asset_set", path=relative) from error
        observed = hashlib.sha256(payload).hexdigest()
        if observed != expected:
            raise _asset_error("MMC_ASSET_MISMATCH", "The MMC asset hash does not match the manifest.", "load_mmc_asset_set", path=relative, expected=expected, observed=observed)
        files[relative] = payload
    library_paths = sorted(path for path in files if path.startswith("library/") and path.casefold().endswith(".pslx"))
    if len(library_paths) != 1:
        raise _asset_error("MMC_ASSET_MISMATCH", "The fixed MMC asset must contain exactly one companion library.", "load_mmc_asset_set", libraries=library_paths)
    required = {"PROVENANCE.md", "blueprint.json", "catalog-pscad-4.6.2.json", "acceptance.json", "golden.json", library_paths[0]}
    missing = sorted(required - set(files))
    if missing:
        raise _asset_error("MMC_ASSET_MISMATCH", "The fixed MMC asset is missing required files.", "load_mmc_asset_set", missing=missing)
    try:
        provenance = files["PROVENANCE.md"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise _asset_error("MMC_ASSET_MISMATCH", "MMC provenance must be UTF-8 text.", "load_mmc_asset_set") from error
    blueprint_value = _json_record(files, "blueprint.json")
    blueprint = parse_blueprint(blueprint_value)
    if blueprint.name != _SUPPORTED_NAME:
        raise _asset_error("MMC_BLUEPRINT_NOT_FOUND", "The packaged MMC blueprint has an unsupported identity.", "load_mmc_asset_set", blueprint=blueprint.name)
    return MmcAssetSet(
        name=blueprint.name,
        schema_version=1,
        pscad_version=pscad_version,
        companion_library=library_paths[0],
        blueprint=blueprint,
        catalog=_json_record(files, "catalog-pscad-4.6.2.json"),
        acceptance=_json_record(files, "acceptance.json"),
        golden=_json_record(files, "golden.json"),
        provenance=provenance,
        hashes=dict(hashes),
        library_bytes=bytes(files[library_paths[0]]),
        files=dict(files),
        root=root,
    )


def load_packaged_asset_set(name: str = _SUPPORTED_NAME) -> MmcAssetSet:
    if name != _SUPPORTED_NAME:
        raise _asset_error("MMC_BLUEPRINT_NOT_FOUND", f"MMC blueprint '{name}' was not found.", "load_packaged_mmc_assets", blueprint=name)
    resource = resources.files("pscad_mcp").joinpath("assets", "mmc", name)
    if not resource.is_dir():
        raise _asset_error("MMC_BLUEPRINT_NOT_FOUND", f"Packaged MMC blueprint '{name}' is not available.", "load_packaged_mmc_assets", blueprint=name)
    with resources.as_file(resource) as materialized:
        return load_asset_set(materialized)


def materialize_library(asset_set: MmcAssetSet, workspace_root: str | Path) -> Path:
    """Install the verified companion library without replacing a concurrent target."""

    workspace = Path(workspace_root).expanduser().resolve()
    expected = asset_set.hashes.get(asset_set.companion_library)
    if expected is None:
        raise _asset_error("MMC_ASSET_MISMATCH", "The companion library is not covered by the MMC manifest.", "materialize_mmc_library")
    target = workspace / ".pscad-mcp" / "mmc-libraries" / Path(asset_set.companion_library).name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC workspace library target is not a regular file.", "materialize_mmc_library", path=str(target))
    if target.is_file():
        observed = sha256_file(target)
        if observed == expected:
            return target
        raise _asset_error("MMC_ASSET_MISMATCH", "The MMC workspace library differs from the verified asset.", "materialize_mmc_library", path=str(target), expected=expected, observed=observed)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(asset_set.library_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_file(temporary) != expected:
            raise _asset_error("MMC_ASSET_MISMATCH", "The materialized MMC library failed hash verification.", "materialize_mmc_library", path=str(temporary))
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or sha256_file(target) != expected:
                raise _asset_error("MMC_ASSET_MISMATCH", "A concurrent MMC library target differs from the verified asset.", "materialize_mmc_library", path=str(target))
        else:
            temporary.unlink()
            temporary = None
        return target
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


__all__ = ["load_asset_set", "load_packaged_asset_set", "materialize_library", "sha256_file"]
