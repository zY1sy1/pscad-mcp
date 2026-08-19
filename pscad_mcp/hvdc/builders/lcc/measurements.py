"""Strict observed and derived measurement contracts for LCC acceptance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError


def _error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "MEASUREMENT_CONTRACT_INVALID",
        message,
        "lcc",
        "validate_measurements",
        details,
    )


def validate_measurements(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise _error("'result_channels' must be a list.")
    normalized: list[dict[str, Any]] = []
    canonicals: set[str] = set()
    endpoints: set[tuple[str, int | None]] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise _error(f"result_channels[{index}] must be an object.")
        item = dict(raw)
        canonical = item.get("canonical")
        if not isinstance(canonical, str) or not canonical.strip():
            raise _error(
                f"result_channels[{index}] requires a non-empty canonical."
            )
        canonical = canonical.strip()
        if canonical in canonicals:
            raise _error(
                f"Canonical '{canonical}' is duplicated in 'result_channels'.",
                canonical=canonical,
            )
        canonicals.add(canonical)
        kind = item.get("kind", "observed")
        if kind not in {"observed", "derived"}:
            raise _error(
                f"Result '{canonical}' has invalid kind '{kind}'.",
                canonical=canonical,
            )
        item["canonical"] = canonical
        item["kind"] = kind
        if kind == "observed":
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                raise _error(f"Result '{canonical}' requires path.")
            call_id = item.get("call_id")
            if call_id is not None and (
                isinstance(call_id, bool)
                or not isinstance(call_id, int)
                or call_id < 1
            ):
                raise _error(f"Result '{canonical}' has invalid call_id.")
            if item.get("units") is not None and not isinstance(
                item.get("units"), str
            ):
                raise _error(f"Result '{canonical}' has invalid units.")
            if item.get("location") is not None and (
                not isinstance(item["location"], str)
                or not item["location"].strip()
            ):
                raise _error(f"Result '{canonical}' has invalid location.")
            endpoint = (path.strip().casefold(), call_id)
            if endpoint in endpoints:
                raise _error(
                    "Observed measurement endpoint is duplicated.",
                    endpoint={"path": path.strip(), "call_id": call_id},
                )
            endpoints.add(endpoint)
            item["path"] = path.strip()
        else:
            sources = item.get("sources")
            if (
                not isinstance(sources, Sequence)
                or isinstance(sources, (str, bytes, bytearray))
                or not sources
                or any(not isinstance(source, str) or not source.strip() for source in sources)
            ):
                raise _error(f"Derived result '{canonical}' requires sources.")
            expression = item.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                raise _error(f"Derived result '{canonical}' requires expression.")
            units = item.get("units")
            if not isinstance(units, str) or not units.strip():
                raise _error(f"Derived result '{canonical}' requires units.")
            time_domain = item.get("time_domain")
            if not isinstance(time_domain, str) or not time_domain.strip():
                raise _error(f"Derived result '{canonical}' requires time_domain.")
            item["sources"] = [source.strip() for source in sources]
            item["expression"] = expression.strip()
            item["units"] = units.strip()
            item["time_domain"] = time_domain.strip()
        normalized.append(item)

    by_canonical = {item["canonical"]: item for item in normalized}
    for item in normalized:
        if item["kind"] != "derived":
            continue
        missing = sorted(set(item["sources"]) - set(by_canonical))
        if missing or item["canonical"] in item["sources"]:
            raise _error(
                f"Derived result '{item['canonical']}' has invalid sources.",
                canonical=item["canonical"],
                missing=missing,
                self_reference=item["canonical"] in item["sources"],
            )
    return sorted(normalized, key=lambda item: item["canonical"])
