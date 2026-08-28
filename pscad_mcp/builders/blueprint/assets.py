"""Hash-verified blueprint assets and read-only source package audits."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ...core.backend.base import BackendError
from ...core.path_policy import PathPolicy
from .models import Blueprint, FrozenDict, freeze
from .schema import parse_blueprint


_DEFAULT_ASSET_ROOT = Path(__file__).parents[2] / "assets" / "blueprints"
_PROJECT_SUFFIXES = frozenset({".pscx", ".pslx", ".pswx"})


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", operation, details)


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _error("BLUEPRINT_ASSET_INVALID", "Blueprint asset is not canonical JSON.", "load_blueprint_asset") from error


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_hash(manifest: Mapping[str, str]) -> str:
    return sha256_bytes(canonical_json(dict(sorted(manifest.items()))))


def hash_tree(root: str | Path) -> dict[str, str]:
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise _error("BLUEPRINT_SOURCE_INVALID", "Source package must be a directory.", "audit_source_package", path=str(directory))
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise _error("BLUEPRINT_SOURCE_INVALID", "Source packages cannot contain symbolic links.", "audit_source_package", path=str(path))
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = sha256_file(path)
    return result


@dataclass(frozen=True)
class BlueprintAsset:
    blueprint: Blueprint
    hashes: FrozenDict
    catalog: FrozenDict | None = None
    name: str | None = None


@dataclass(frozen=True)
class SourceAudit:
    root: str
    entry_point: str
    package_hashes: FrozenDict
    package_hash: str


def resolve_companion_project_files(
    blueprint: Blueprint,
    package_root: str | Path,
    path_policy: PathPolicy,
) -> tuple[Path, ...]:
    """Resolve declared PSCAD companion files in blueprint order."""

    root = path_policy.resolve(str(package_root), must_exist=True)
    entry_point = path_policy.resolve_child(
        str(root),
        blueprint.source_package["entry_point"],
    )
    resolved: list[Path] = []
    seen: set[Path] = {entry_point}
    for requirement in blueprint.source_package["required"]:
        if requirement["kind"] != "file":
            continue
        candidate = path_policy.resolve_child(str(root), requirement["path"])
        if candidate in seen or candidate.suffix.casefold() not in _PROJECT_SUFFIXES:
            continue
        try:
            candidate = path_policy.resolve_child(
                str(root),
                requirement["path"],
                suffixes=_PROJECT_SUFFIXES,
                must_exist=True,
            )
        except (OSError, ValueError) as error:
            raise _error(
                "BLUEPRINT_SOURCE_MISSING",
                "A declared companion project file is missing or invalid.",
                "resolve_companion_project_files",
                path=requirement["path"],
            ) from error
        if not candidate.is_file() or candidate.is_symlink():
            raise _error(
                "BLUEPRINT_SOURCE_INVALID",
                "A declared companion project must be a regular file.",
                "resolve_companion_project_files",
                path=requirement["path"],
            )
        seen.add(candidate)
        resolved.append(candidate)
    return tuple(resolved)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _error("BLUEPRINT_ASSET_INVALID", f"{label} is not readable JSON.", "load_blueprint_asset", path=str(path)) from error


def load_blueprint_asset(
    value: str | Mapping[str, Any],
    *,
    asset_root: str | Path | None = None,
) -> BlueprintAsset:
    if isinstance(value, Mapping):
        blueprint = parse_blueprint(value)
        digest = sha256_bytes(canonical_json(blueprint.to_dict()))
        return BlueprintAsset(blueprint, freeze({"blueprint.json": digest}), name=blueprint.identity.name)
    if not isinstance(value, str) or not value.strip() or Path(value).name != value:
        raise _error("BLUEPRINT_ASSET_NOT_FOUND", "Blueprint name must be a simple asset name.", "load_blueprint_asset", blueprint=value)
    root = (Path(asset_root) if asset_root is not None else _DEFAULT_ASSET_ROOT).resolve()
    candidate = root / value
    if candidate.is_symlink():
        raise _error("BLUEPRINT_ASSET_INVALID", "Blueprint asset directories cannot be links.", "load_blueprint_asset", blueprint=value)
    directory = candidate.resolve()
    if directory != root and root not in directory.parents:
        raise _error("BLUEPRINT_ASSET_INVALID", "Blueprint asset directory escapes the configured root.", "load_blueprint_asset", blueprint=value)
    blueprint_path = directory / "blueprint.json"
    if not blueprint_path.is_file():
        raise _error("BLUEPRINT_ASSET_NOT_FOUND", f"Blueprint asset '{value}' was not found.", "load_blueprint_asset", blueprint=value)
    blueprint = parse_blueprint(_read_json(blueprint_path, "blueprint.json"))
    if blueprint.identity.name != value:
        raise _error(
            "BLUEPRINT_ASSET_INVALID",
            "Blueprint identity does not match its asset directory.",
            "load_blueprint_asset",
            expected=value,
            observed=blueprint.identity.name,
        )
    hashes: dict[str, str] = {}
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise _error("BLUEPRINT_ASSET_INVALID", "Blueprint assets cannot contain links.", "load_blueprint_asset", path=str(path))
        if not path.is_file():
            continue
        hashes[path.relative_to(directory).as_posix()] = sha256_file(path)
    catalog_path = directory / "catalog.json"
    catalog_value = _read_json(catalog_path, "catalog.json") if catalog_path.is_file() else None
    if catalog_value is not None and not isinstance(catalog_value, Mapping):
        raise _error("BLUEPRINT_ASSET_INVALID", "catalog.json must contain an object.", "load_blueprint_asset")
    return BlueprintAsset(
        blueprint,
        freeze(hashes),
        freeze(catalog_value) if catalog_value is not None else None,
        value,
    )


def audit_source_package(blueprint: Blueprint, source_path: str, path_policy: PathPolicy) -> SourceAudit:
    try:
        root = path_policy.resolve(source_path, must_exist=True)
    except (OSError, ValueError) as error:
        raise _error("BLUEPRINT_SOURCE_INVALID", "Source package path is not permitted.", "audit_source_package", source_path=source_path) from error
    if not root.is_dir() or root.is_symlink():
        raise _error("BLUEPRINT_SOURCE_INVALID", "Source package must be a regular directory.", "audit_source_package", source_path=str(root))
    try:
        entry_point = path_policy.resolve_child(str(root), blueprint.source_package["entry_point"], suffixes={".pscx"}, must_exist=True)
    except (OSError, ValueError) as error:
        raise _error("BLUEPRINT_SOURCE_MISSING", "Blueprint source entry point is missing or invalid.", "audit_source_package") from error
    if not entry_point.is_file() or entry_point.is_symlink():
        raise _error("BLUEPRINT_SOURCE_INVALID", "Blueprint entry point must be a regular PSCX file.", "audit_source_package")
    for requirement in blueprint.source_package["required"]:
        try:
            candidate = path_policy.resolve_child(str(root), requirement["path"], must_exist=True)
        except (OSError, ValueError) as error:
            raise _error(
                "BLUEPRINT_SOURCE_MISSING",
                "A required source package dependency is missing.",
                "audit_source_package",
                path=requirement["path"],
            ) from error
        expected_kind = requirement["kind"]
        if candidate.is_symlink() or (expected_kind == "file" and not candidate.is_file()) or (expected_kind == "directory" and not candidate.is_dir()):
            raise _error("BLUEPRINT_SOURCE_INVALID", "A source package dependency has the wrong kind.", "audit_source_package", path=requirement["path"])
        expected_hash = requirement.get("sha256")
        if expected_hash is not None:
            observed_hash = sha256_file(candidate) if candidate.is_file() else manifest_hash(hash_tree(candidate))
            if observed_hash != expected_hash:
                raise _error(
                    "BLUEPRINT_SOURCE_HASH_MISMATCH",
                    "A source package dependency hash does not match the blueprint.",
                    "audit_source_package",
                    path=requirement["path"],
                    expected_sha256=expected_hash,
                    observed_sha256=observed_hash,
                )
    hashes = hash_tree(root)
    return SourceAudit(str(root), str(entry_point), freeze(hashes), manifest_hash(hashes))
