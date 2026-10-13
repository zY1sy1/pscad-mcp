"""Hash-bound snapshots, atomic checkpoints and an OS-held workspace lease."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any

import psutil

from ...core.backend.base import BackendError
from ...core.path_policy import PathPolicy
from .models import SweepSpec


def sweep_error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "sweep", "parameter_sweep", details)


def digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def checkpoint_hash(checkpoint: dict[str, Any]) -> str:
    payload = {
        key: value for key, value in checkpoint.items() if key != "checkpoint_hash"
    }
    # Parameter snapshot IDs become string keys when persisted as JSON.
    try:
        normalized = json.loads(json.dumps(payload, allow_nan=False))
        return digest(normalized)
    except (ValueError, TypeError) as error:
        raise sweep_error(
            "SWEEP_EVIDENCE_CHANGED", "A checkpoint contains invalid JSON data."
        ) from error


def reject_link(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise sweep_error(
            "SWEEP_UNSAFE_PATH", "Links and reparse points are not sweep inputs."
        )


def contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    raw = Path(relative)
    if (
        raw.is_absolute()
        or PureWindowsPath(relative).is_absolute()
        or ".." in raw.parts
    ):
        raise sweep_error(
            "SWEEP_UNSAFE_PATH", "An artifact path must be relative and contained."
        )
    candidate = root / raw
    for part in (root, *candidate.relative_to(root).parents):
        check = part if part.is_absolute() else root / part
        if check.exists():
            reject_link(check)
    if candidate.exists():
        reject_link(candidate)
    resolved = candidate.resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise sweep_error(
            "SWEEP_UNSAFE_PATH", "An artifact escapes its managed directory."
        )
    if must_exist and not resolved.is_file():
        raise sweep_error(
            "SWEEP_OUTPUT_MISSING",
            "A required artifact is missing.",
            relative_path=relative,
        )
    return resolved


def tree_inventory(root: Path, exclude: Path | None = None) -> dict[str, str]:
    reject_link(root)
    inventory: dict[str, str] = {}
    names: set[str] = set()
    for parent, directories, files in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        kept = []
        for name in sorted(directories):
            path = parent_path / name
            if exclude is not None and path == exclude:
                continue
            reject_link(path)
            kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            path = parent_path / name
            reject_link(path)
            if not path.is_file():
                raise sweep_error(
                    "SWEEP_UNSAFE_PATH", "Only regular source files are supported."
                )
            relative = path.relative_to(root).as_posix()
            if relative.casefold() in names:
                raise sweep_error(
                    "SWEEP_UNSAFE_PATH", "Source filenames collide on Windows."
                )
            names.add(relative.casefold())
            inventory[relative] = file_hash(path)
            if len(inventory) > 10000:
                raise sweep_error(
                    "SWEEP_INVALID_SPEC", "A source snapshot is limited to 10000 files."
                )
    return dict(sorted(inventory.items()))


def validate_dependencies(root: Path, inventory: dict[str, str]) -> None:
    suffixes = re.compile(r".+\.(?:pscx|pslx|pswx|tlo|csv|dat|txt)$", re.IGNORECASE)
    for relative in inventory:
        path = contained(root, relative, must_exist=True)
        if path.suffix.casefold() not in {".pscx", ".pslx", ".pswx"}:
            continue
        try:
            tree = ET.parse(path)
        except ET.ParseError as error:
            raise sweep_error(
                "SWEEP_INVALID_SPEC",
                "A source project is not valid XML.",
                relative_path=relative,
            ) from error
        for element in tree.iter():
            values = list(element.attrib.values())
            if element.text and element.text.strip():
                values.append(element.text.strip())
            for value in values:
                value = value.strip().strip('"').replace("\\", "/")
                if not suffixes.fullmatch(value):
                    continue
                reference = Path(value)
                if reference.is_absolute() or PureWindowsPath(value).is_absolute():
                    raise sweep_error(
                        "SWEEP_INVALID_SPEC",
                        "Absolute source dependencies must be made relative in an approved copy.",
                        relative_path=relative,
                    )
                dependency = (path.parent / reference).resolve()
                if root.resolve() not in dependency.parents or not dependency.is_file():
                    raise sweep_error(
                        "SWEEP_INVALID_SPEC",
                        "A source dependency is missing or escapes the snapshot.",
                        relative_path=relative,
                        dependency=value,
                    )
                if dependency.relative_to(root.resolve()).as_posix() not in inventory:
                    raise sweep_error(
                        "SWEEP_INVALID_SPEC",
                        "A dependency is excluded from the source snapshot.",
                    )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_link(path.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".sweep-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=True, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    reject_link(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise sweep_error(
            "SWEEP_EVIDENCE_CHANGED", "A sweep record cannot be read."
        ) from error


def process_alive(identity: dict[str, Any] | None) -> bool:
    if not identity:
        return False
    try:
        return (
            abs(psutil.Process(identity["pid"]).create_time() - identity["create_time"])
            < 0.01
        )
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, KeyError, TypeError, ValueError):
        return True  # Unknown ownership is never permission to start another instance.


class WorkspaceLease:
    def __init__(self, root: Path, alive: Callable[..., bool] = process_alive):
        self.root = root
        self.alive = alive
        self.stream = None
        self.owner: dict[str, Any] = {}

    def acquire(self, campaign_id: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.stream = contained(self.root, "active-sweep.lock").open("a+b")
        if os.fstat(self.stream.fileno()).st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            self.stream = None
            raise sweep_error(
                "SWEEP_BUSY", "Another campaign owns this workspace."
            ) from error
        previous_path = contained(self.root, "active-sweep.json")
        try:
            previous = read_json(previous_path) if previous_path.exists() else {}
            if previous.get("ownership_unknown") or self.alive(
                previous.get("owned_session")
            ):
                raise sweep_error(
                    "SWEEP_NEEDS_REVIEW",
                    "An earlier owned PSCAD process has not been verified absent.",
                    campaign_id=previous.get("campaign_id"),
                )
            self.owner = {
                "campaign_id": campaign_id,
                "pid": os.getpid(),
                "create_time": psutil.Process().create_time(),
                "nonce": uuid.uuid4().hex,
                "owned_session": None,
                "active": True,
            }
            atomic_json(previous_path, self.owner)
        except BaseException:
            self.release(preserve_owner=True)
            raise

    def record_session(
        self, identity: dict[str, Any] | None, *, unknown: bool = False
    ) -> None:
        self.owner["owned_session"] = identity
        self.owner["ownership_unknown"] = unknown
        atomic_json(contained(self.root, "active-sweep.json"), self.owner)

    def release(self, *, preserve_owner: bool = False) -> None:
        if self.stream is None:
            return
        try:
            if not preserve_owner:
                self.owner["active"] = False
                self.owner["owned_session"] = None
                self.owner["ownership_unknown"] = False
                atomic_json(contained(self.root, "active-sweep.json"), self.owner)
        finally:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


class SweepStore:
    def __init__(self, policy: PathPolicy):
        if policy.workspace_root is None:
            raise sweep_error(
                "WORKSPACE_NOT_CONFIGURED", "PSCAD_MCP_WORKSPACE is required."
            )
        self.workspace = policy.workspace_root
        self.root = contained(self.workspace, ".pscad-mcp/sweeps")

    def campaign_path(self, campaign_id: str) -> Path:
        if not isinstance(campaign_id, str) or not re.fullmatch(
            r"sweep-[0-9a-f]{32}", campaign_id
        ):
            raise sweep_error("SWEEP_INVALID_ID", "Unknown or invalid campaign ID.")
        if contained(self.workspace, ".pscad-mcp/sweeps") != self.root:
            raise sweep_error(
                "SWEEP_UNSAFE_PATH", "The managed state directory changed."
            )
        return contained(self.root, campaign_id)

    def plan(self, spec: SweepSpec) -> dict[str, Any]:
        exclude = self.workspace / ".pscad-mcp"
        inventory = tree_inventory(spec.source_root, exclude)
        validate_dependencies(spec.source_root, inventory)
        payload = {"spec": spec.to_dict(), "source_inventory": inventory}
        return {
            "plan_hash": digest(payload),
            "source_hash": digest(inventory),
            "scenario_count": len(spec.scenarios),
            "source_file_count": len(inventory),
            "spec": spec.to_dict(),
            "source_inventory": inventory,
        }

    def create(self, spec: SweepSpec, plan: dict[str, Any]) -> str:
        cid = "sweep-" + uuid.uuid4().hex
        root = self.campaign_path(cid)
        root.mkdir(parents=True, exist_ok=False)
        baseline = root / "baseline"
        self.copy_snapshot(spec.source_root, baseline, plan["source_inventory"])
        if (
            tree_inventory(spec.source_root, self.workspace / ".pscad-mcp")
            != plan["source_inventory"]
        ):
            raise sweep_error(
                "SWEEP_SOURCE_CHANGED", "The source changed while it was being copied."
            )
        manifest = {"schema_version": 1, "campaign_id": cid, **plan}
        atomic_json(root / "manifest.json", manifest)
        checkpoint = {
            "schema_version": 1,
            "campaign_id": cid,
            "manifest_hash": digest(manifest),
            "state": "ready",
            "revision": 0,
            "active_attempt": None,
            "scenarios": [
                {
                    "name": s.name,
                    "directory_key": s.directory_key,
                    "state": "pending",
                    "attempt_count": 0,
                    "results": [],
                }
                for s in spec.scenarios
            ],
        }
        self.save(cid, checkpoint)
        return cid

    @staticmethod
    def copy_snapshot(source: Path, target: Path, inventory: dict[str, str]) -> None:
        target.mkdir(parents=True, exist_ok=False)
        for relative in inventory:
            origin = contained(source, relative, must_exist=True)
            destination = contained(target, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, destination)
        if tree_inventory(target) != inventory:
            raise sweep_error(
                "SWEEP_SOURCE_CHANGED",
                "A source copy does not match its reviewed hashes.",
            )

    def load(self, cid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        root = self.campaign_path(cid)
        if not (root / "manifest.json").is_file():
            raise sweep_error("SWEEP_NOT_FOUND", "The campaign does not exist.")
        manifest = read_json(contained(root, "manifest.json", must_exist=True))
        checkpoint = read_json(contained(root, "checkpoint.json", must_exist=True))
        if (
            not isinstance(manifest, dict)
            or not isinstance(checkpoint, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("campaign_id") != cid
            or checkpoint.get("campaign_id") != cid
            or checkpoint.get("manifest_hash") != digest(manifest)
            or checkpoint.get("checkpoint_hash") != checkpoint_hash(checkpoint)
        ):
            raise sweep_error(
                "SWEEP_EVIDENCE_CHANGED",
                "The manifest no longer matches the checkpoint.",
            )
        return manifest, checkpoint

    def verify_inputs(self, manifest: dict[str, Any]) -> None:
        root = self.campaign_path(manifest["campaign_id"])
        expected = manifest["source_inventory"]
        if tree_inventory(root / "baseline") != expected:
            raise sweep_error(
                "SWEEP_EVIDENCE_CHANGED", "The immutable baseline has changed."
            )
        if (
            tree_inventory(
                Path(manifest["spec"]["source_root"]), self.workspace / ".pscad-mcp"
            )
            != expected
        ):
            raise sweep_error(
                "SWEEP_SOURCE_CHANGED", "The reviewed source has changed."
            )

    def save(self, cid: str, checkpoint: dict[str, Any]) -> None:
        checkpoint["revision"] += 1
        checkpoint["checkpoint_hash"] = checkpoint_hash(checkpoint)
        atomic_json(contained(self.campaign_path(cid), "checkpoint.json"), checkpoint)

    def result(self, cid: str, reference: dict[str, str]) -> dict[str, Any]:
        root = self.campaign_path(cid)
        path = contained(root, reference["path"], must_exist=True)
        if file_hash(path) != reference["sha256"]:
            raise sweep_error(
                "SWEEP_EVIDENCE_CHANGED", "An attempt result has changed."
            )
        result = read_json(path)
        for artifact in result.get("artifacts", []):
            artifact_path = contained(root, artifact["relative_path"], must_exist=True)
            if (
                str(artifact_path) != artifact["path"]
                or file_hash(artifact_path) != artifact["sha256"]
            ):
                raise sweep_error(
                    "SWEEP_EVIDENCE_CHANGED", "A retained output artifact has changed."
                )
        return result
