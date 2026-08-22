"""Deterministic, catalog-driven, fail-closed derivation of LCC values."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError
from .assets import load_parametric_catalog, load_parametric_provenance
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
    provenance = load_parametric_provenance()
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("identity"), str)
        or value.get("provenance_identity") != provenance.get("identity")
    ):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The parametric catalog identity or schema is invalid.",
            schema_version=value.get("schema_version"),
            identity=value.get("identity"),
            provenance_identity=value.get("provenance_identity"),
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


def _provenance_entry(reference: Any, parameter: str) -> Mapping[str, Any]:
    provenance = load_parametric_provenance()
    identity = provenance.get("identity")
    entries = _object(provenance.get("entries"), "provenance.entries")
    if not isinstance(reference, str) or ":" not in reference:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog provenance reference is invalid.",
            parameter=parameter,
            asset=reference,
        )
    prefix, entry_name = reference.split(":", 1)
    if prefix != identity or entry_name not in entries:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog provenance entry is not available.",
            parameter=parameter,
            asset=reference,
        )
    return _object(entries[entry_name], f"provenance.entries.{entry_name}")


def _declaration_contract(
    declaration: Mapping[str, Any], parameter: str
) -> tuple[str, str, tuple[Mapping[str, Any], ...]]:
    units = declaration.get("units")
    asset = declaration.get("asset")
    constraints_value = declaration.get("constraints")
    if (
        not isinstance(units, str)
        or not units
        or isinstance(constraints_value, (str, bytes, bytearray))
        or not isinstance(constraints_value, Sequence)
    ):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog parameter declaration is incomplete.",
            parameter=parameter,
        )
    _provenance_entry(asset, parameter)
    constraints: list[Mapping[str, Any]] = []
    for constraint in constraints_value:
        constraint_declaration = _object(constraint, f"{parameter}.constraints")
        _provenance_entry(constraint_declaration.get("asset"), parameter)
        constraints.append(constraint_declaration)
    return units, asset, tuple(constraints)


def _validate_constraints(
    value: float,
    declaration: Mapping[str, Any],
    parameter: str,
    *,
    code: str,
) -> tuple[str, ...]:
    units, _, constraints = _declaration_contract(declaration, parameter)
    evidence: list[str] = []
    for constraint in constraints:
        kind = constraint.get("kind")
        asset = constraint.get("asset")
        relationship = asset.split(":", 1)[1] if isinstance(asset, str) and ":" in asset else kind
        if kind == "exclusive_minimum":
            minimum = _finite_number(constraint.get("value"), parameter=parameter)
            valid = value > minimum
            statement = f"value > {minimum} {units}"
        elif kind == "open_interval":
            minimum = _finite_number(constraint.get("minimum"), parameter=parameter)
            maximum = _finite_number(constraint.get("maximum"), parameter=parameter)
            if minimum >= maximum:
                raise _error(
                    "LCC_PARAMETER_DERIVATION_FAILED",
                    "Catalog open interval is invalid.",
                    parameter=parameter,
                    relationship=relationship,
                )
            valid = minimum < value < maximum
            statement = f"{minimum} < value < {maximum} {units} (basic domain)"
        else:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Catalog constraint is unsupported.",
                parameter=parameter,
                relationship=relationship,
            )
        if not valid:
            raise _error(
                code,
                "Parameter violates a sourced physical or representation invariant.",
                parameter=parameter,
                value=value,
                units=units,
                relationship=relationship,
                asset=asset,
            )
        evidence.append(statement)
    return tuple(evidence)


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
        _provenance_entry(declaration.get("unit_asset"), name)
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
        if multiplier <= 0.0:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Catalog unit multiplier must be positive.",
                parameter=name,
                units=supplied_units,
            )
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
        constraints = _validate_constraints(normalized, declaration, name, code="LCC_RATING_INVALID")
        units, asset, _ = _declaration_contract(declaration, name)
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
    required_rating_names = {"rated_power_mw", "dc_voltage_kv", "dc_current_ka"}
    expected_dependencies = {"dc_voltage_kv", "dc_current_ka"}
    dependency_value = declaration.get("dependencies")
    dependencies = (
        set(dependency_value)
        if isinstance(dependency_value, Sequence) and not isinstance(dependency_value, (str, bytes, bytearray))
        else set()
    )
    rating_declarations = _object(catalog["rating_parameters"], "rating_parameters")
    missing_dependencies = sorted(
        (expected_dependencies - dependencies) | (required_rating_names - set(rating_declarations))
    )
    if missing_dependencies:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The dimensional power formula is missing declared catalog dependencies.",
            missing_catalog_dependencies=missing_dependencies,
        )
    if formula != "dc_voltage_kv * dc_current_ka" or not isinstance(units, str) or not isinstance(asset, str):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The sourced dimensional power formula is unavailable.",
            parameter="dc_power_mw",
        )
    _provenance_entry(asset, "dc_power_mw")
    calculated = ratings["dc_voltage_kv"] * ratings["dc_current_ka"]
    comparison_asset = declaration.get("comparison_asset")
    comparison_provenance = _provenance_entry(comparison_asset, "dc_power_mw")
    relative_tolerance = _finite_number(declaration.get("relative_tolerance"), parameter="dc_power_mw")
    absolute_tolerance = _finite_number(declaration.get("absolute_tolerance"), parameter="dc_power_mw")
    if comparison_provenance.get("values") != {
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance": absolute_tolerance,
    }:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Power comparison tolerances do not match versioned provenance.",
            parameter="dc_power_mw",
            asset=comparison_asset,
        )
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
        units, asset, _ = _declaration_contract(declaration, name)
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
                    "A catalog default requires formula evidence.",
                    parameter=name,
                )
            formula = formula_value
            source = "default"
            default_asset = declaration.get("default_asset")
            default_provenance = _provenance_entry(default_asset, name)
            observed_defaults = default_provenance.get("values")
            if not isinstance(observed_defaults, Mapping) or observed_defaults.get(name) != value:
                raise _error(
                    "LCC_PARAMETER_DERIVATION_FAILED",
                    "Catalog default does not match its versioned legacy provenance.",
                    parameter=name,
                    value=value,
                    asset=default_asset,
                )
            asset = default_asset
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
        constraints = _validate_constraints(value, declaration, name, code="LCC_PARAMETER_DERIVATION_FAILED")
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
            "Required engineering values lack a sourced default/formula and a user override.",
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
        _provenance_entry(declaration.get("asset"), name)
        if operator == "less_than":
            left_name = declaration.get("left")
            right_name = declaration.get("right")
            if left_name not in all_values or right_name not in all_values:
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
            valid = all_values[left_name] < all_values[right_name]
            observed = {str(left_name): all_values[left_name], str(right_name): all_values[right_name]}
        else:
            raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Catalog relationship operator is unsupported.", relationship=name, operator=operator)
        if not valid:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "The sourced structural relationship is not satisfied.",
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
    return_provenance = _provenance_entry(declaration.get("asset"), f"return_asset_requirements.{request.topology}")
    allowed_value = declaration.get("allowed")
    if isinstance(allowed_value, (str, bytes, bytearray)) or not isinstance(allowed_value, Sequence):
        raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Catalog allowed return assets are invalid.", topology=request.topology)
    allowed = set(allowed_value)
    provenance_allowed = return_provenance.get("allowed_assets")
    if (
        isinstance(provenance_allowed, (str, bytes, bytearray))
        or not isinstance(provenance_allowed, Sequence)
        or allowed != set(provenance_allowed)
    ):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog return assets do not match versioned provenance.",
            topology=request.topology,
        )
    unknown = sorted(set(request.return_path_assets) - allowed)
    if unknown:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Return-path asset evidence is not declared by the catalog.",
            unknown_return_assets=unknown,
            allowed_return_assets=sorted(allowed),
        )
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
    """Derive catalog-sourced values without accessing PSCAD or writing files."""
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
