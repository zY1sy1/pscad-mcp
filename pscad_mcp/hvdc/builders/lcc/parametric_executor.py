"""Fail-closed execution boundary for audited PSCX template substitution.

The catalog currently contains no approved template parameter paths.  This
module therefore accepts bindings only when a plan carries an explicit,
deterministic selector and value; it never guesses paths from component names.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import tempfile
import time
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


def _validated_binding_updates(
    plan: dict[str, Any],
) -> tuple[Path, bytes, Path, ET.Element, list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Validate source, binding declarations, and XML matches without writing."""
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
    read_back: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_elements: set[int] = set()
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
            or (logical, selector) in seen
        ):
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding is missing an approved identity, unit, or attribute.",
                "execute_parametric_lcc_build",
                reason="binding_invalid",
            )
        seen.add((logical, selector))
        if isinstance(value, bool) or isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding value is not finite.",
                "execute_parametric_lcc_build",
                reason="binding_value_invalid",
            )
        matches = _matches(root, selector)
        expected_matches = binding.get("expected_match_count", 1)
        if isinstance(expected_matches, bool) or not isinstance(expected_matches, int) or expected_matches <= 0:
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding expected match count must be a positive integer.",
                "execute_parametric_lcc_build",
                reason="expected_match_count_invalid",
            )
        if len(matches) != expected_matches or len(matches) != 1:
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "A template binding must resolve to exactly one XML element.",
                "execute_parametric_lcc_build",
                reason="binding_not_unique",
                logical_parameter=logical,
                matches=len(matches),
                expected_match_count=expected_matches,
            )
        element = matches[0]
        if id(element) in seen_elements:
            raise _error(
                "LCC_PARAMETER_BINDING_UNAVAILABLE",
                "Multiple bindings cannot target the same XML element.",
                "execute_parametric_lcc_build",
                reason="binding_not_unique",
                logical_parameter=logical,
            )
        seen_elements.add(id(element))
        if attribute == "value":
            element.set("value", str(value))
            modified.append(f"{selector}/@value")
            observed_value = element.get("value")
        else:
            element.text = str(value)
            modified.append(f"{selector}/text()")
            observed_value = element.text
        updates.append({"element": element, "selector": selector, "attribute": attribute, "value": value})
        read_back.append(
            {
                "logical_parameter": logical,
                "role": binding.get("role"),
                "selector": selector,
                "attribute": attribute,
                "units": units,
                "expected_match_count": expected_matches,
                "value": observed_value,
            }
        )
    return source, payload, staging, root, updates, modified, read_back


def validate_template_bindings(plan: dict[str, Any]) -> dict[str, Any]:
    """Perform all binding and XML checks without touching staging or PSCAD."""

    source, payload, staging, _root, _updates, modified, read_back = _validated_binding_updates(plan)
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "staging_path": str(staging),
        "modified_paths": modified,
        "read_back": read_back,
    }


def apply_template_bindings(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy a source PSCX and apply only explicit, unique XML bindings."""

    source, payload, staging, root, _updates, modified, read_back = _validated_binding_updates(plan)
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
        "read_back": read_back,
    }


def _lifecycle_config(plan: dict[str, Any]) -> dict[str, Any]:
    """Return bounded lifecycle options without allowing arbitrary backend calls."""
    value = plan.get("lifecycle", plan.get("pscad", {}))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(
            "LCC_BUILD_UNAVAILABLE",
            "The parametric plan lifecycle configuration is invalid.",
            "execute_parametric_lcc_build",
            reason="lifecycle_config_invalid",
        )
    return value


def _timeout(value: Any, default: float, *, field: str) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise _error(
            "LCC_BUILD_UNAVAILABLE",
            f"The lifecycle {field} must be a finite positive number.",
            "execute_parametric_lcc_build",
            reason="lifecycle_timeout_invalid",
            field=field,
        )
    return min(float(value), 86_400.0)


def _status_value(response: Any) -> str | None:
    if isinstance(response, dict):
        for key in ("status", "state", "result"):
            value = response.get(key)
            if isinstance(value, str):
                return value.casefold()
    if isinstance(response, str):
        value = response.casefold()
        if any(token in value for token in ("failed", "failure", "error", "compile")):
            return "failed"
        if any(token in value for token in ("running", "started", "queued")):
            return "running"
        if any(token in value for token in ("complete", "success", "built")):
            return "completed"
    return None


def _output_candidates(staging: Path, explicit: Any) -> list[Path]:
    values: list[Any] = []
    if explicit is not None:
        values.append(explicit)
    # PSCAD writes $(Namespace).out beside the loaded project.  Restrict
    # discovery to the builder-owned staging directory and bounded suffixes.
    values.extend(sorted(staging.parent.glob("*.out"), key=lambda path: str(path).casefold()))
    values.extend(sorted(staging.parent.glob("*.psout"), key=lambda path: str(path).casefold()))
    candidates: list[Path] = []
    root = staging.parent.resolve()
    for value in values:
        if not isinstance(value, (str, Path)) or not str(value):
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink():
            continue
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_file() or resolved.suffix.casefold() not in {".out", ".psout"}:
            continue
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


async def execute_parametric_template(
    plan: dict[str, Any],
    pscad_service: Any,
    workspace_root: str | Path,
    *,
    build_id: str = "lcc-parametric-build",
    journal: Any = None,
) -> dict[str, Any]:
    """Execute an explicitly bound template through the PscadService boundary.

    This function intentionally does not access a backend implementation.  It
    only uses the public service methods needed for a real project lifecycle;
    absent a licensed service or a terminal output file it returns a structured
    failure and leaves the staging evidence in place.
    """

    evidence = apply_template_bindings(plan)
    config = _lifecycle_config(plan)
    loader = getattr(pscad_service, "load_projects", None)
    settings_writer = getattr(pscad_service, "set_project_settings", None)
    saver = getattr(pscad_service, "save_project_as", None)
    runner = getattr(pscad_service, "run_simulation_set", None)
    run_project = getattr(pscad_service, "run_project", None)
    reader = getattr(pscad_service, "read_output_file", None)
    if not callable(loader) or not callable(settings_writer) or not callable(saver) or not callable(reader) or not (callable(runner) or callable(run_project)):
        raise _error(
            "LCC_BUILD_UNAVAILABLE",
            "The PSCAD service does not expose the required project lifecycle APIs.",
            "execute_parametric_lcc_build",
            reason="pscad_lifecycle_unavailable",
        )
    staging = Path(evidence["staging_path"]).resolve()
    project = plan.get("project", {}) if isinstance(plan.get("project", {}), dict) else {}
    project_name = config.get("project_name") or project.get("name") or staging.stem
    if not isinstance(project_name, str) or not project_name:
        raise _error("LCC_BUILD_UNAVAILABLE", "The staged project name is invalid.", "execute_parametric_lcc_build", reason="project_name_invalid")
    settings = config.get("settings", config.get("project_settings", {}))
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise _error("LCC_BUILD_UNAVAILABLE", "The project settings payload is invalid.", "execute_parametric_lcc_build", reason="project_settings_invalid")
    simulation_set = config.get("simulation_set")
    explicit_output = config.get("output_file", config.get("output_path"))
    run_timeout = _timeout(config.get("run_timeout_s", config.get("timeout_s")), 900.0, field="run_timeout_s")
    poll_interval = _timeout(config.get("poll_interval_s"), 0.25, field="poll_interval_s")
    await loader([evidence["staging_path"]])
    await settings_writer(project_name, settings)
    # Save-as is the public persistence boundary.  The destination is the
    # already-created staging file; no final target is touched here.
    await saver(project_name, staging.name, str(staging.parent), confirm=True)
    started = time.monotonic()
    try:
        response = (
            await runner(project_name, simulation_set)
            if isinstance(simulation_set, str) and simulation_set and callable(runner)
            else await run_project(project_name)
        )
    except BaseException as error:
        raise _error(
            "LCC_COMPILE_FAILED",
            "PSCAD failed to compile or start the staged project.",
            "execute_parametric_lcc_build",
            reason="compile_or_start_failed",
            exception=type(error).__name__,
        ) from error
    status = _status_value(response)
    if status == "failed":
        raise _error("LCC_COMPILE_FAILED", "PSCAD reported a compile or run failure.", "execute_parametric_lcc_build", reason="compile_failed")
    if status == "completed" and not _output_candidates(staging, explicit_output):
        raise _error("LCC_OUTPUT_MISSING", "PSCAD completed without producing an output file.", "execute_parametric_lcc_build", reason="output_missing")
    while True:
        candidates = _output_candidates(staging, explicit_output)
        if candidates:
            break
        if time.monotonic() - started >= run_timeout:
            raise _error("LCC_RUN_TIMED_OUT", "The PSCAD run did not produce output before the timeout.", "execute_parametric_lcc_build", reason="run_timeout", timeout_s=run_timeout)
        await asyncio.sleep(min(poll_interval, 1.0))
    if len(candidates) != 1:
        raise _error("LCC_OUTPUT_MISSING", "The staged PSCAD run did not produce one unambiguous output file.", "execute_parametric_lcc_build", reason="output_ambiguous", candidates=[str(path) for path in candidates])
    output_file = candidates[0]
    try:
        output = await reader(str(output_file), max_samples=1_000_000, summary_only=False)
    except BaseException as error:
        raise _error("LCC_OUTPUT_MISSING", "The staged PSCAD output file could not be read.", "execute_parametric_lcc_build", reason="output_read_failed", path=str(output_file), exception=type(error).__name__) from error
    record = {
        "build_id": build_id,
        "state": "validated",
        "workspace": str(Path(workspace_root).expanduser().resolve()),
        "result": {"template": evidence, "backend_loaded": True, "project_name": project_name, "output_file": str(output_file), "output": output, "run_response": response},
        "error": None,
    }
    if journal is not None:
        journal.write(record)
    return record


__all__ = ["apply_template_bindings", "execute_parametric_template", "validate_template_bindings"]
