"""Deterministic, catalog-driven, fail-closed derivation of LCC values."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError
from .assets import load_parametric_catalog
from .parametric_models import DerivedParameter, DerivedParameterReport, ParametricLccRequest


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "derive_lcc_parameters", details)


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            f"The parameter catalog requires an object at '{name}'.",
            catalog_field=name,
        )
    return value


def _catalog_data(catalog: Any) -> Mapping[str, Any]:
    value = load_parametric_catalog() if catalog is None else catalog
    if not isinstance(value, Mapping):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "A raw versioned parametric catalog is required.",
            catalog_type=type(value).__name__,
        )
    if value.get("schema_version") != 1 or not isinstance(value.get("identity"), str):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The parametric catalog identity or schema is invalid.",
            schema_version=value.get("schema_version"),
            identity=value.get("identity"),
        )
    for field in (
        "rating_parameters",
        "derived_parameters",
        "engineering_parameters",
        "feasibility_relationships",
        "return_asset_requirements",
    ):
        _object(value.get(field), field)
    return value


def _finite_number(value: Any, *, parameter: str, code: str = "LCC_PARAMETER_DERIVATION_FAILED") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(code, "Parameter value must be numeric.", parameter=parameter, value=value)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _error(code, "Parameter value must be finite.", parameter=parameter, value=value) from None
    if not math.isfinite(result):
        raise _error(code, "Parameter value must be finite.", parameter=parameter, value=value)
    return result


def _declaration_bounds(declaration: Mapping[str, Any], parameter: str) -> tuple[float, float, str, str]:
    try:
        minimum = _finite_number(declaration["minimum"], parameter=parameter)
        maximum = _finite_number(declaration["maximum"], parameter=parameter)
        units = declaration["units"]
        asset = declaration["asset"]
    except KeyError as error:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog parameter declaration is incomplete.",
            parameter=parameter,
            missing_catalog_field=str(error.args[0]),
        ) from None
    if minimum > maximum or not isinstance(units, str) or not units or not isinstance(asset, str) or not asset:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog parameter declaration is invalid.",
            parameter=parameter,
        )
    return minimum, maximum, units, asset


def _validate_range(value: float, declaration: Mapping[str, Any], parameter: str, *, code: str) -> tuple[str, ...]:
    minimum, maximum, units, _ = _declaration_bounds(declaration, parameter)
    if value < minimum or value > maximum:
        raise _error(
            code,
            "Parameter is outside the reviewed catalog range.",
            parameter=parameter,
            value=value,
            units=units,
            minimum=minimum,
            maximum=maximum,
        )
    return (f"{minimum} <= value <= {maximum} {units}",)


def _normalize_override(name: str, raw: Any, declaration: Mapping[str, Any]) -> tuple[float, str]:
    canonical_units = declaration.get("units")
    if isinstance(raw, Mapping):
        unknown_fields = sorted(set(raw) - {"value", "units"})
        if unknown_fields or "value" not in raw or "units" not in raw:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Unit-bearing override must contain exactly value and units.",
                parameter=name,
                unknown_fields=unknown_fields,
            )
        supplied_units = raw["units"]
        multipliers = _object(declaration.get("unit_multipliers"), f"engineering_parameters.{name}.unit_multipliers")
        if not isinstance(supplied_units, str) or supplied_units not in multipliers:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Override units are not declared by the catalog.",
                parameter=name,
                units=supplied_units,
                supported_units=sorted(multipliers),
            )
        multiplier = _finite_number(multipliers[supplied_units], parameter=name)
        value = _finite_number(raw["value"], parameter=name) * multiplier
        formula = f"user value * {multiplier} {supplied_units}->{canonical_units}"
        return value, formula
    return _finite_number(raw, parameter=name), f"user value in catalog units ({canonical_units})"


def _rating_parameters(request: ParametricLccRequest, catalog: Mapping[str, Any]) -> tuple[list[DerivedParameter], dict[str, float]]:
    declarations = _object(catalog["rating_parameters"], "rating_parameters")
    values: list[DerivedParameter] = []
    numeric: dict[str, float] = {}
    for name, declaration_value in declarations.items():
        declaration = _object(declaration_value, f"rating_parameters.{name}")
        value = getattr(request.ratings, name, None)
        if value is None:
            if declaration.get("required") is True:
                raise _error("LCC_RATING_INVALID", "A required rating is missing.", parameter=name)
            continue
        normalized = _finite_number(value, parameter=name, code="LCC_RATING_INVALID")
        constraints = _validate_range(normalized, declaration, name, code="LCC_RATING_INVALID")
        _, _, units, asset = _declaration_bounds(declaration, name)
        numeric[name] = normalized
        values.append(
            DerivedParameter(
                name=name,
                value=normalized,
                source="user",
                formula=f"request.ratings.{name}",
                units=units,
                constraints=constraints,
                asset=asset,
            )
        )
    return values, numeric


def _derived_power(ratings: Mapping[str, float], catalog: Mapping[str, Any]) -> DerivedParameter:
    declarations = _object(catalog["derived_parameters"], "derived_parameters")
    declaration = _object(declarations.get("dc_power_mw"), "derived_parameters.dc_power_mw")
    formula = declaration.get("formula")
    units = declaration.get("units")
    asset = declaration.get("asset")
    if formula != "dc_voltage_kv * dc_current_ka" or not isinstance(units, str) or not isinstance(asset, str):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The reviewed dimensional power formula is unavailable.",
            parameter="dc_power_mw",
        )
    calculated = ratings["dc_voltage_kv"] * ratings["dc_current_ka"]
    relative_tolerance = _finite_number(declaration.get("relative_tolerance"), parameter="dc_power_mw")
    absolute_tolerance = _finite_number(declaration.get("absolute_tolerance"), parameter="dc_power_mw")
    if not math.isclose(ratings["rated_power_mw"], calculated, rel_tol=relative_tolerance, abs_tol=absolute_tolerance):
        raise _error(
            "LCC_RATING_INCONSISTENT",
            "rated_power_mw must equal dc_voltage_kv * dc_current_ka.",
            rated_power_mw=ratings["rated_power_mw"],
            calculated_power_mw=calculated,
            formula=formula,
            asset=asset,
        )
    return DerivedParameter(
        name="dc_power_mw",
        value=calculated,
        source="derived",
        formula=formula,
        units=units,
        constraints=(f"relative_tolerance={relative_tolerance}", f"absolute_tolerance={absolute_tolerance}"),
        asset=asset,
    )


def _engineering_parameters(request: ParametricLccRequest, catalog: Mapping[str, Any]) -> tuple[list[DerivedParameter], dict[str, float]]:
    declarations = _object(catalog["engineering_parameters"], "engineering_parameters")
    overrides = dict(request.engineering_overrides)
    unknown = sorted(set(overrides) - set(declarations))
    if unknown:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Unsupported engineering override.",
            unknown=unknown,
        )

    parameters: list[DerivedParameter] = []
    numeric: dict[str, float] = {}
    missing: list[str] = []
    for name in sorted(declarations):
        declaration = _object(declarations[name], f"engineering_parameters.{name}")
        minimum, maximum, units, asset = _declaration_bounds(declaration, name)
        if "required" not in declaration or "default" not in declaration or "formula" not in declaration:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Catalog engineering declaration is missing required/default/formula evidence.",
                parameter=name,
            )
        if name in overrides:
            value, formula = _normalize_override(name, overrides[name], declaration)
            source = "user"
        elif declaration["default"] is not None:
            value = _finite_number(declaration["default"], parameter=name)
            formula_value = declaration["formula"]
            if not isinstance(formula_value, str) or not formula_value:
                raise _error(
                    "LCC_PARAMETER_DERIVATION_FAILED",
                    "A reviewed default requires formula evidence.",
                    parameter=name,
                )
            formula = formula_value
            source = "default"
        elif declaration["formula"] is not None:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "The catalog declares an unsupported engineering formula.",
                parameter=name,
                formula=declaration["formula"],
            )
        elif declaration["required"] is True:
            missing.append(name)
            continue
        else:
            continue
        constraints = _validate_range(value, declaration, name, code="LCC_PARAMETER_DERIVATION_FAILED")
        numeric[name] = value
        parameters.append(
            DerivedParameter(
                name=name,
                value=value,
                source=source,
                formula=formula,
                units=units,
                constraints=constraints,
                asset=asset,
            )
        )
    if missing:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Required engineering values lack a reviewed default/formula and a user override.",
            missing=sorted(missing),
        )
    return parameters, numeric


def _validate_relationships(ratings: Mapping[str, float], engineering: Mapping[str, float], catalog: Mapping[str, Any]) -> None:
    relationships = _object(catalog["feasibility_relationships"], "feasibility_relationships")
    all_values = {**ratings, **engineering}
    for name in sorted(relationships):
        declaration = _object(relationships[name], f"feasibility_relationships.{name}")
        operator = declaration.get("operator")
        valid = False
        observed: dict[str, Any]
        if operator == "less_than_or_equal":
            left_name = declaration.get("left")
            right_name = declaration.get("right")
            if left_name not in all_values:
                continue
            if right_name not in all_values:
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
            valid = all_values[left_name] <= all_values[right_name]
            observed = {str(left_name): all_values[left_name], str(right_name): all_values[right_name]}
        elif operator in {"sum_less_than", "sum_less_than_parameter"}:
            parameter_names = declaration.get("parameters")
            if isinstance(parameter_names, (str, bytes, bytearray)) or not isinstance(parameter_names, Sequence):
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship parameter list is invalid.", relationship=name)
            if any(parameter not in all_values for parameter in parameter_names):
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
            total = sum(all_values[parameter] for parameter in parameter_names)
            if operator == "sum_less_than":
                limit = _finite_number(declaration.get("limit"), parameter=name)
            else:
                right_name = declaration.get("right")
                if right_name not in all_values:
                    raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
                limit = all_values[right_name]
            valid = total < limit
            observed = {"sum": total, "limit": limit, "parameters": list(parameter_names)}
        else:
            raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Catalog relationship operator is unsupported.", relationship=name, operator=operator)
        if not valid:
            raise _error(
                "LCC_RATING_INVALID" if name == "escr_not_greater_than_scr" else "LCC_PARAMETER_DERIVATION_FAILED",
                "The reviewed catalog feasibility relationship is not satisfied.",
                relationship=name,
                asset=declaration.get("asset"),
                observed=observed,
            )


def _validate_return_assets(request: ParametricLccRequest, catalog: Mapping[str, Any]) -> None:
    requirements = _object(catalog["return_asset_requirements"], "return_asset_requirements")
    declaration_value = requirements.get(request.topology)
    if declaration_value is None:
        return
    declaration = _object(declaration_value, f"return_asset_requirements.{request.topology}")
    required = set(declaration.get("required", ()))
    mode_requirements = _object(declaration.get("mode_requirements", {}), f"return_asset_requirements.{request.topology}.mode_requirements")
    for mode in request.operation_modes:
        mode_assets = mode_requirements.get(mode, ())
        if isinstance(mode_assets, (str, bytes, bytearray)) or not isinstance(mode_assets, Sequence):
            raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Catalog return asset requirement is invalid.", mode=mode)
        required.update(mode_assets)
    missing = sorted(required - set(request.return_path_assets))
    if missing:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Explicit bipolar return-path asset evidence is missing.",
            missing_return_assets=missing,
            declared_return_assets=sorted(request.return_path_assets),
            asset=declaration.get("asset"),
        )


def derive_lcc_parameters(request: ParametricLccRequest, catalog: Any = None) -> DerivedParameterReport:
    """Derive reviewed values without accessing PSCAD or writing any files."""
    if not isinstance(request, ParametricLccRequest):
        raise _error("LCC_PARAMETER_DERIVATION_FAILED", "request must be ParametricLccRequest")
    catalog_data = _catalog_data(catalog)
    rating_parameters, ratings = _rating_parameters(request, catalog_data)
    derived_power = _derived_power(ratings, catalog_data)
    engineering_parameters, engineering = _engineering_parameters(request, catalog_data)
    _validate_relationships(ratings, engineering, catalog_data)
    _validate_return_assets(request, catalog_data)
    parameters = rating_parameters + [derived_power] + engineering_parameters
    return DerivedParameterReport(
        parameters=tuple(sorted(parameters, key=lambda item: item.name)),
        feasible=True,
        diagnostics=(),
    )
