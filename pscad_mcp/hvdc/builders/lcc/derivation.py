"""Deterministic, fail-closed derivation of parametric LCC values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ....core.backend.base import BackendError
from .catalog import LccCatalog
from .parametric_models import DerivedParameter, DerivedParameterReport, ParametricLccRequest


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "derive_lcc_parameters", details)


def _catalog_defaults(catalog: Any) -> Mapping[str, Any]:
    if catalog is None:
        return {}
    if isinstance(catalog, Mapping):
        return catalog.get("derived_parameters", catalog.get("defaults", {}))
    definitions = getattr(catalog, "definitions", {})
    values: dict[str, Any] = {}
    for definition in definitions.values():
        metadata = getattr(definition, "metadata", {})
        derived = metadata.get("derived_parameters", {}) if isinstance(metadata, Mapping) else {}
        if isinstance(derived, Mapping):
            values.update(derived)
    return values


def derive_lcc_parameters(request: ParametricLccRequest, catalog: Any = None) -> DerivedParameterReport:
    """Derive ratings and reviewed defaults without filesystem or backend writes."""
    if not isinstance(request, ParametricLccRequest):
        raise _error("LCC_PARAMETER_DERIVATION_FAILED", "request must be ParametricLccRequest")
    ratings = request.ratings
    calculated_power = float(ratings.dc_voltage_kv) * float(ratings.dc_current_ka)
    if not math.isclose(float(ratings.rated_power_mw), calculated_power, rel_tol=1e-6, abs_tol=1e-6):
        raise _error(
            "LCC_RATING_INCONSISTENT",
            "rated_power_mw must equal dc_voltage_kv * dc_current_ka.",
            rated_power_mw=ratings.rated_power_mw,
            calculated_power_mw=calculated_power,
        )
    if ratings.scr <= 0 or (ratings.escr is not None and ratings.escr <= 0):
        raise _error("LCC_RATING_INVALID", "SCR values must be positive.")

    defaults = _catalog_defaults(catalog)
    overrides = dict(request.engineering_overrides)
    supported = {"smoothing_reactor_mh", "overlap_angle_deg", "filter_capacitance_uf", "min_extinction_angle_deg"}
    unknown = sorted(set(overrides) - supported)
    if unknown:
        raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Unsupported engineering override.", unknown=unknown)

    values: list[DerivedParameter] = [
        DerivedParameter("dc_power_mw", calculated_power, "derived", "dc_voltage_kv * dc_current_ka", "MW", asset="ratings"),
        DerivedParameter("dc_voltage_kv", ratings.dc_voltage_kv, "user", "request.ratings.dc_voltage_kv", "kV", asset="ratings"),
        DerivedParameter("dc_current_ka", ratings.dc_current_ka, "user", "request.ratings.dc_current_ka", "kA", asset="ratings"),
        DerivedParameter("ac_voltage_kv", ratings.ac_voltage_kv, "user", "request.ratings.ac_voltage_kv", "kV", asset="ratings"),
        DerivedParameter("frequency_hz", ratings.frequency_hz, "user", "request.ratings.frequency_hz", "Hz", asset="ratings"),
        DerivedParameter("scr", ratings.scr, "user", "request.ratings.scr", "1", asset="ratings"),
    ]
    for name, value in overrides.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Engineering override must be a finite positive number.", parameter=name)
        values.append(DerivedParameter(name, value, "user", f"request.engineering_overrides[{name!r}]", None, asset="request"))

    for name, declaration in defaults.items():
        if name in overrides:
            continue
        if isinstance(declaration, Mapping) and "default" in declaration:
            values.append(DerivedParameter(name, declaration["default"], "derived", str(declaration.get("formula", "catalog.default")), declaration.get("units"), asset=str(declaration.get("asset", "catalog"))))
    return DerivedParameterReport(parameters=tuple(sorted(values, key=lambda item: item.name)), feasible=True, diagnostics=())
