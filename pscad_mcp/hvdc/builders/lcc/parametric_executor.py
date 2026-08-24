"""Fail-closed execution boundary for audited PSCX template substitution.

The catalog currently contains no approved template parameter paths.  This
module therefore accepts bindings only when a plan carries an explicit,
deterministic selector and value; it never guesses paths from component names.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError


_MAX_BINDINGS = 128
_MAX_SELECTOR = 512
_ALLOWED_ATTRIBUTES = {"value", "text"}
_FORBIDDEN_XML_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _source_and_payload(plan: dict[str, Any]) -> tuple[Path, bytes]:
    try:
        template = plan["template"]
        source = Path(template["path"]).expanduser().resolve()
        expected = template["fingerprint"]
    except (KeyError, TypeError, ValueError) as error:
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The execution plan does not contain a valid source template.",
            "execute_parametric_lcc_build",
            reason="template_plan_invalid",
        ) from error
    if not source.is_absolute() or not source.is_file() or source.is_symlink():
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The source template must be an existing regular PSCX file.",
            "execute_parametric_lcc_build",
            reason="template_not_regular",
        )
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The source template could not be read.",
            "execute_parametric_lcc_build",
            reason="template_unreadable",
        ) from error
    observed = hashlib.sha256(payload).hexdigest()
    if not isinstance(expected, str) or observed != expected:
        raise _error(
            "LCC_PLAN_STALE",
            "The source template changed after planning.",
            "execute_parametric_lcc_build",
            reason="source_changed",
        )
    return source, payload


def _parse(payload: bytes) -> ET.Element:
    if _FORBIDDEN_XML_DECLARATION.search(payload.replace(b"\x00", b"")):
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The source template contains a forbidden XML declaration.",
            "execute_parametric_lcc_build",
            reason="forbidden_xml_declaration",
        )
    try:
        return ET.fromstring(payload)
    except ET.ParseError as error:
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The source template is not valid PSCX XML.",
            "execute_parametric_lcc_build",
            reason="invalid_xml",
        ) from error


def _matches(root: ET.Element, selector: str) -> list[ET.Element]:
    if (
        not isinstance(selector, str)
        or len(selector) > _MAX_SELECTOR
        or not selector.startswith("/project")
        or ".." in selector
        or "|" in selector
    ):
        raise _error(
            "LCC_PARAMETER_BINDING_UNAVAILABLE",
            "A template binding selector is not an approved absolute path.",
            "execute_parametric_lcc_build",
            reason="selector_invalid",
        )
    relative = "." + selector[len("/project") :]
    try:
        return list(root.findall(relative))
    except SyntaxError as error:
        raise _error(
            "LCC_PARAMETER_BINDING_UNAVAILABLE",
            "A template binding selector is not valid ElementTree XPath.",
            "execute_parametric_lcc_build",
            reason="selector_invalid",
        ) from error


def apply_template_bindings(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy a source PSCX and apply only explicit, unique XML bindings."""

    source, payload = _source_and_payload(plan)
    try:
        project = plan["project"]
        staging = Path(project["staging_path"]).expanduser().resolve()
        bindings = plan["bindings"]
    except (KeyError, TypeError, ValueError) as error:
        raise _error(
            "LCC_PARAMETER_BINDING_UNAVAILABLE",
            "The execution plan does not declare approved template bindings.",
            "execute_parametric_lcc_build",
            reason="bindings_missing",
        ) from error
    if not isinstance(bindings, list) or not bindings or len(bindings) > _MAX_BINDINGS:
        raise _error(
            "LCC_PARAMETER_BINDING_UNAVAILABLE",
            "Every parameterized build requires explicit approved template bindings.",
            "execute_parametric_lcc_build",
            reason="bindings_missing",
        )
    if not staging.is_absolute() or staging == source:
        raise _error(
            "LCC_LAYOUT_INVALID",
            "The staging path must be an absolute path distinct from the source.",
            "execute_parametric_lcc_build",
            reason="staging_path_invalid",
        )
    root = _parse(payload)
    modified: list[str] = []
    seen: set[tuple[str, str]] = set()
    seen_logical: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding must be an object.",
                "execute_parametric_lcc_build",
                reason="binding_invalid",
            )
        logical = binding.get("logical_parameter")
        selector = binding.get("selector")
        attribute = binding.get("attribute")
        units = binding.get("units")
        value = binding.get("value")
        if (
            not isinstance(logical, str)
            or not logical
            or not isinstance(units, str)
            or not units
            or attribute not in _ALLOWED_ATTRIBUTES
            or not isinstance(selector, str)
            or logical in seen_logical
            or (logical, selector) in seen
        ):
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding is missing an approved identity, unit, or attribute.",
                "execute_parametric_lcc_build",
                reason="binding_invalid",
            )
        seen.add((logical, selector))
        seen_logical.add(logical)
        if isinstance(value, bool) or isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding value is not finite.",
                "execute_parametric_lcc_build",
                reason="binding_value_invalid",
            )
        matches = _matches(root, selector)
        if len(matches) != 1:
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding must resolve to exactly one XML element.",
                "execute_parametric_lcc_build",
                reason="binding_not_unique",
                logical_parameter=logical,
                matches=len(matches),
            )
        element = matches[0]
        if attribute == "value":
            element.set("value", str(value))
            modified.append(f"{selector}/@value")
        else:
            element.text = str(value)
            modified.append(f"{selector}/text()")
    staging.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=staging.parent) as stream:
            temporary = Path(stream.name)
            tree = ET.ElementTree(root)
            tree.write(stream, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, staging)
    except OSError as error:
        raise _error(
            "LCC_BUILD_FAILED",
            "The parameterized staging project could not be written.",
            "execute_parametric_lcc_build",
            reason="staging_write_failed",
        ) from error
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)
    staged_payload = staging.read_bytes()
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "staging_path": str(staging),
        "staging_sha256": hashlib.sha256(staged_payload).hexdigest(),
        "modified_paths": modified,
    }


async def execute_parametric_template(
    plan: dict[str, Any],
    pscad_service: Any,
    workspace_root: str | Path,
    *,
    build_id: str = "lcc-parametric-build",
    journal: Any = None,
) -> dict[str, Any]:
    """Stage, load, and optionally run an explicitly bound PSCX template."""

    evidence = apply_template_bindings(plan)
    loader = getattr(pscad_service, "load_projects", None)
    if not callable(loader):
        raise _error(
            "LCC_BUILD_UNAVAILABLE",
            "The PSCAD service does not expose project loading.",
            "execute_parametric_lcc_build",
            reason="pscad_load_unavailable",
        )
    await loader([evidence["staging_path"]])
    record = {
        "build_id": build_id,
        "state": "validated",
        "workspace": str(Path(workspace_root).expanduser().resolve()),
        "result": {"template": evidence, "backend_loaded": True},
        "error": None,
    }
    if journal is not None:
        journal.write(record)
    return record


__all__ = ["apply_template_bindings", "execute_parametric_template"]
