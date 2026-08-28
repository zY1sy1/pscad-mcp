"""Shared FastMCP registration with stable PSCAD error serialization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
import inspect
import logging
import math
import re
import threading
import time
from typing import Any, ParamSpec, TypeVar, Union, get_args, get_type_hints

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic.fields import FieldInfo

from ..core.connection_manager import pscad_manager
from ..learning.models import InvocationOutcome
from ..learning.recorder import InvocationRecorder, learning_recorder
from .catalog import TOOL_SPECS
from .identifiers import (
    BACKEND_NAME_PATTERN,
    PSCAD_VERSION_PATTERN,
    bounded_identifier,
)


P = ParamSpec("P")
R = TypeVar("R")
_LOGGER = logging.getLogger("pscad-mcp.learning")
_WARNING_LOCK = threading.Lock()
_WARNING_EMITTED = False
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


def _record_safely(action: Callable[[], Any], fallback: Any = None) -> Any:
    try:
        return action()
    except Exception as error:
        global _WARNING_EMITTED
        with _WARNING_LOCK:
            if not _WARNING_EMITTED:
                _LOGGER.warning(
                    "Learning instrumentation failed after %s.",
                    type(error).__name__,
                )
                _WARNING_EMITTED = True
        return fallback


def _snapshot_metadata() -> dict[str, str | None]:
    def read_snapshot() -> dict[str, str | None]:
        snapshot = pscad_manager.learning_snapshot()
        if not isinstance(snapshot, Mapping):
            return {"backend": None, "pscad_version": None}
        return {
            "backend": bounded_identifier(
                snapshot.get("backend"),
                BACKEND_NAME_PATTERN,
            ),
            "pscad_version": bounded_identifier(
                snapshot.get("pscad_version"),
                PSCAD_VERSION_PATTERN,
            ),
        }

    return _record_safely(
        read_snapshot,
        fallback={"backend": None, "pscad_version": None},
    )


def _outcome_metadata(
    result: Any,
    snapshot: Mapping[str, str | None],
) -> tuple[InvocationOutcome, str | None, bool | None, str | None]:
    try:
        error = result.get("error") if isinstance(result, Mapping) else None
        if not isinstance(error, Mapping):
            return (
                InvocationOutcome.SUCCESS,
                None,
                None,
                snapshot.get("backend"),
            )
        error_code = bounded_identifier(error.get("code"), _ERROR_CODE)
        retryable = error.get("retryable")
        error_backend = bounded_identifier(
            error.get("backend"),
            BACKEND_NAME_PATTERN,
        )
    except Exception:
        return (
            InvocationOutcome.ERROR,
            "INTERNAL_ERROR",
            None,
            snapshot.get("backend"),
        )
    return (
        InvocationOutcome.ERROR,
        error_code or "INTERNAL_ERROR",
        retryable if isinstance(retryable, bool) else None,
        error_backend or snapshot.get("backend"),
    )


def _is_json_safe(value: Any, seen: set[int] | None = None) -> bool:
    if value is None or isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    seen = set() if seen is None else seen
    value_id = id(value)
    if value_id in seen:
        return False
    if isinstance(value, list):
        seen.add(value_id)
        try:
            return all(_is_json_safe(item, seen) for item in value)
        finally:
            seen.remove(value_id)
    if isinstance(value, dict):
        seen.add(value_id)
        try:
            return all(
                isinstance(key, str) and _is_json_safe(item, seen)
                for key, item in value.items()
            )
        finally:
            seen.remove(value_id)
    return False


def _json_safe_copy(value: Any, seen: set[int] | None = None) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    seen = set() if seen is None else seen
    value_id = id(value)
    if value_id in seen:
        return None
    if isinstance(value, list):
        seen.add(value_id)
        try:
            return [_json_safe_copy(item, seen) for item in value]
        finally:
            seen.remove(value_id)
    if isinstance(value, dict):
        seen.add(value_id)
        try:
            return {
                key: _json_safe_copy(item, seen)
                for key, item in value.items()
                if isinstance(key, str)
            }
        finally:
            seen.remove(value_id)
    return None


def _register_with_original_result(mcp: FastMCP, guarded: Callable[..., Any]) -> None:
    # FastMCP validates and then model-dumps structured output, which copies JSON-safe values.
    name = guarded.__name__
    spec = TOOL_SPECS[name]
    try:
        mcp.add_tool(
            guarded,
            description=spec.description,
            annotations=spec.annotations(),
        )
        tool = mcp._tool_manager.get_tool(name)
        if tool is None:
            raise RuntimeError(name)
        properties = tool.parameters.get("properties")
        if isinstance(properties, dict):
            for parameter in inspect.signature(guarded).parameters.values():
                description = _annotation_description(parameter.annotation)
                schema = properties.get(parameter.name)
                if description and isinstance(schema, dict):
                    schema.setdefault("description", description)
        convert_result = tool.fn_metadata.convert_result

        def preserve_result(result: Any) -> Any:
            converted = convert_result(result)
            if (
                tool.fn_metadata.output_schema is not None
                and isinstance(converted, tuple)
                and len(converted) == 2
            ):
                unstructured, structured = converted
                structured = _json_safe_copy(structured)
                if tool.fn_metadata.wrap_output:
                    if _is_json_safe(result):
                        structured["result"] = result
                elif _is_json_safe(result):
                    structured = result
                return unstructured, structured
            return converted

        object.__setattr__(tool.fn_metadata, "convert_result", preserve_result)
    except Exception:
        try:
            mcp.remove_tool(name)
        except Exception:
            pass
        raise


def _is_call_tool_result(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, CallToolResult)


def _annotation_description(annotation: Any) -> str | None:
    """Read a Field description from an Annotated parameter type."""
    for metadata in get_args(annotation)[1:]:
        if isinstance(metadata, FieldInfo) and isinstance(metadata.description, str):
            return metadata.description
    return None


def register_tool(
    mcp: FastMCP,
    function: Callable[P, Awaitable[R]],
    *,
    recorder: InvocationRecorder = learning_recorder,
    record_learning: bool = True,
    force: bool = False,
) -> None:
    """Register an async tool while preserving structured backend failures."""

    name = function.__name__
    if name not in TOOL_SPECS:
        raise ValueError(name)
    registered_names = getattr(mcp, "_pscad_registered_tool_names", None)
    privately_registered = registered_names is not None and name in registered_names
    manager_registered = mcp._tool_manager.get_tool(name) is not None
    if privately_registered or manager_registered:
        raise ValueError(name)
    profile = getattr(mcp, "_pscad_tool_profile", None)
    if not force and profile is not None and not profile.includes(name):
        return

    signature = inspect.signature(function)
    resolved_annotations = get_type_hints(function, include_extras=True)
    resolved_parameters = [
        parameter.replace(
            annotation=resolved_annotations.get(parameter.name, parameter.annotation)
        )
        for parameter in signature.parameters.values()
    ]
    return_annotation = resolved_annotations.get("return", Any)

    @wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> Any:
        if not record_learning:
            try:
                return await function(*args, **kwargs)
            except Exception as error:
                return pscad_manager.error_payload(error, function.__name__)

        snapshot = _snapshot_metadata()
        started = time.perf_counter()
        try:
            result = await function(*args, **kwargs)
        except Exception as error:
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            result = pscad_manager.error_payload(error, function.__name__)
            outcome, error_code, retryable, backend = _outcome_metadata(
                result,
                snapshot,
            )
            _record_safely(
                lambda: recorder.record(
                    tool_name=function.__name__,
                    duration_ms=duration_ms,
                    outcome=outcome,
                    error_code=error_code,
                    retryable=retryable,
                    backend=backend,
                    pscad_version=snapshot.get("pscad_version"),
                )
            )
            return result

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        outcome, error_code, retryable, backend = _outcome_metadata(
            result,
            snapshot,
        )
        _record_safely(
            lambda: recorder.record(
                tool_name=function.__name__,
                duration_ms=duration_ms,
                outcome=outcome,
                error_code=error_code,
                retryable=retryable,
                backend=backend,
                pscad_version=snapshot.get("pscad_version"),
            )
        )
        return result

    error_aware_return = (
        return_annotation
        if _is_call_tool_result(return_annotation)
        else Union[return_annotation, dict[str, Any]]
    )
    guarded.__signature__ = signature.replace(
        parameters=resolved_parameters,
        return_annotation=error_aware_return
    )
    guarded.__annotations__ = resolved_annotations
    guarded.__annotations__["return"] = error_aware_return
    _register_with_original_result(mcp, guarded)
    if registered_names is None:
        registered_names = set()
        setattr(mcp, "_pscad_registered_tool_names", registered_names)
    registered_names.add(name)
    if record_learning:
        learning_names = getattr(mcp, "_pscad_learning_tool_names", None)
        if learning_names is None:
            learning_names = set()
            setattr(mcp, "_pscad_learning_tool_names", learning_names)
        learning_names.add(name)
        _record_safely(lambda: recorder.register_tool_name(name))
