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
        "return_contract_assets",
        "return_asset_requirements",
    ):
        _object(value.get(field), field)
    _validate_authoritative_catalog_structure(value, provenance)
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


def _machine_contract(reference: Any, parameter: str) -> Mapping[str, Any]:
    entry = _provenance_entry(reference, parameter)
    return _object(entry.get("machine_contract"), f"provenance.{reference}.machine_contract")


def _require_machine_contract(
    reference: Any,
    observed: Mapping[str, Any],
    parameter: str,
    *,
    relationship: str | None = None,
) -> Mapping[str, Any]:
    expected = _machine_contract(reference, parameter)
    if dict(observed) != dict(expected):
        details: dict[str, Any] = {
            "parameter": parameter,
            "asset": reference,
            "observed_contract": dict(observed),
            "expected_contract": dict(expected),
        }
        if relationship is not None:
            details["relationship"] = relationship
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog declaration does not match versioned provenance semantics.",
            **details,
        )
    return expected


def _validate_authoritative_catalog_structure(
    catalog: Mapping[str, Any], provenance: Mapping[str, Any]
) -> None:
    structure_asset = provenance.get("catalog_structure_contract_asset")
    contract = _machine_contract(structure_asset, "catalog_structure")
    required_relationships = _object(
        contract.get("required_relationships"),
        f"provenance.{structure_asset}.required_relationships",
    )
    required_return_contracts = _object(
        contract.get("required_return_contracts"),
        f"provenance.{structure_asset}.required_return_contracts",
    )

    relationships = _object(
        catalog.get("feasibility_relationships"), "feasibility_relationships"
    )
    missing_relationships = sorted(set(required_relationships) - set(relationships))
    unexpected_relationships = sorted(set(relationships) - set(required_relationships))
    mismatched_relationship_assets = sorted(
        name
        for name in set(required_relationships) & set(relationships)
        if not isinstance(relationships[name], Mapping)
        or relationships[name].get("asset") != required_relationships[name]
    )
    if missing_relationships or unexpected_relationships or mismatched_relationship_assets:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog feasibility relationship inventory does not match versioned provenance.",
            asset=structure_asset,
            missing_relationships=missing_relationships,
            unexpected_relationships=unexpected_relationships,
            mismatched_relationship_assets=mismatched_relationship_assets,
        )

    contract_assets = _object(catalog.get("return_contract_assets"), "return_contract_assets")
    requirements = _object(catalog.get("return_asset_requirements"), "return_asset_requirements")
    expected_topologies = set(required_return_contracts)
    missing_contract_topologies = sorted(expected_topologies - set(contract_assets))
    missing_requirement_topologies = sorted(expected_topologies - set(requirements))
    missing_return_topologies = sorted(
        expected_topologies - (set(contract_assets) | set(requirements))
    )
    unexpected_contract_topologies = sorted(set(contract_assets) - expected_topologies)
    unexpected_requirement_topologies = sorted(set(requirements) - expected_topologies)
    mismatched_return_contracts = sorted(
        topology
        for topology in expected_topologies & set(contract_assets) & set(requirements)
        if contract_assets[topology] != required_return_contracts[topology]
        or not isinstance(requirements[topology], Mapping)
        or requirements[topology].get("asset") != required_return_contracts[topology]
    )
    if (
        missing_contract_topologies
        or missing_requirement_topologies
        or unexpected_contract_topologies
        or unexpected_requirement_topologies
        or mismatched_return_contracts
    ):
        single_missing = sorted(
            set(missing_contract_topologies) | set(missing_requirement_topologies)
        )
        missing_asset = (
            required_return_contracts.get(single_missing[0])
            if len(single_missing) == 1
            else structure_asset
        )
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog return-topology contract inventory does not match versioned provenance.",
            asset=missing_asset,
            missing_return_topologies=missing_return_topologies,
            missing_contract_topologies=missing_contract_topologies,
            missing_requirement_topologies=missing_requirement_topologies,
            unexpected_contract_topologies=unexpected_contract_topologies,
            unexpected_requirement_topologies=unexpected_requirement_topologies,
            mismatched_return_contracts=mismatched_return_contracts,
        )


def _resolve_provenance_multiplier(value: Any, parameter: str) -> float:
    if isinstance(value, Mapping):
        if dict(value) != {"expression": "180 / pi"}:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Provenance unit conversion expression is unsupported.",
                parameter=parameter,
            )
        return 180.0 / math.pi
    return _finite_number(value, parameter=parameter)


def _validate_unit_contract(declaration: Mapping[str, Any], parameter: str) -> None:
    multipliers_value = declaration.get("unit_multipliers")
    unit_asset = declaration.get("unit_asset")
    if multipliers_value is None and unit_asset is None:
        return
    multipliers = _object(multipliers_value, f"engineering_parameters.{parameter}.unit_multipliers")
    contract = _machine_contract(unit_asset, parameter)
    parameters = _object(contract.get("parameters"), f"provenance.{unit_asset}.parameters")
    expected_parameter = _object(parameters.get(parameter), f"provenance.{unit_asset}.{parameter}")
    expected_multipliers = _object(expected_parameter.get("multipliers"), f"provenance.{unit_asset}.{parameter}.multipliers")
    observed_units = declaration.get("units")
    if observed_units != expected_parameter.get("canonical_units") or set(multipliers) != set(expected_multipliers):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog unit declaration does not match versioned provenance.",
            parameter=parameter,
            asset=unit_asset,
        )
    for units, expected_value in expected_multipliers.items():
        observed = _finite_number(multipliers[units], parameter=parameter)
        expected = _resolve_provenance_multiplier(expected_value, parameter)
        if observed != expected:
            raise _error(
                "LCC_PARAMETER_DERIVATION_FAILED",
                "Catalog unit multiplier does not match versioned provenance.",
                parameter=parameter,
                units=units,
                observed=observed,
                expected=expected,
                asset=unit_asset,
            )


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
    _validate_unit_contract(declaration, parameter)
    constraints: list[Mapping[str, Any]] = []
    for constraint in constraints_value:
        constraint_declaration = _object(constraint, f"{parameter}.constraints")
        constraint_asset = constraint_declaration.get("asset")
        observed_contract = {key: value for key, value in constraint_declaration.items() if key != "asset"}
        _require_machine_contract(constraint_asset, observed_contract, parameter)
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


def _validate_rating_contract(catalog: Mapping[str, Any]) -> None:
    declarations = _object(catalog["rating_parameters"], "rating_parameters")
    required_for_power = {"rated_power_mw", "dc_voltage_kv", "dc_current_ka"}
    missing_power_inputs = sorted(required_for_power - set(declarations))
    if missing_power_inputs:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The dimensional power formula is missing declared catalog dependencies.",
            missing_catalog_dependencies=missing_power_inputs,
        )
    observed_parameters: dict[str, Any] = {}
    for name, declaration_value in declarations.items():
        declaration = _object(declaration_value, f"rating_parameters.{name}")
        observed_parameters[name] = {"required": declaration.get("required")}
    asset = catalog.get("rating_contract_asset")
    _require_machine_contract(
        asset,
        {"parameters": observed_parameters},
        "rating_parameters",
    )


def _rating_parameters(request: ParametricLccRequest, catalog: Mapping[str, Any]) -> tuple[list[DerivedParameter], dict[str, float]]:
    declarations = _object(catalog["rating_parameters"], "rating_parameters")
    _validate_rating_contract(catalog)
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
    observed_power_contract = {
        "formula": formula,
        "dependencies": list(dependency_value),
        "compared_to": declaration.get("compared_to"),
    }
    _require_machine_contract(asset, observed_power_contract, "dc_power_mw")
    if formula != "dc_voltage_kv * dc_current_ka" or not isinstance(units, str) or not isinstance(asset, str):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "The sourced dimensional power formula is unavailable.",
            parameter="dc_power_mw",
        )
    calculated = ratings["dc_voltage_kv"] * ratings["dc_current_ka"]
    comparison_asset = declaration.get("comparison_asset")
    comparison_contract = _machine_contract(comparison_asset, "dc_power_mw")
    relative_tolerance = _finite_number(declaration.get("relative_tolerance"), parameter="dc_power_mw")
    absolute_tolerance = _finite_number(declaration.get("absolute_tolerance"), parameter="dc_power_mw")
    if comparison_contract.get("values") != {
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
            default_contract = _machine_contract(default_asset, name)
            observed_defaults = default_contract.get("values")
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


def _validate_relationships(
    ratings: Mapping[str, float], engineering: Mapping[str, float], catalog: Mapping[str, Any]
) -> list[DerivedParameter]:
    relationships = _object(catalog["feasibility_relationships"], "feasibility_relationships")
    all_values = {**ratings, **engineering}
    derived: list[DerivedParameter] = []
    for name in sorted(relationships):
        declaration = _object(relationships[name], f"feasibility_relationships.{name}")
        operator = declaration.get("operator")
        valid = False
        observed: dict[str, Any]
        asset = declaration.get("asset")
        observed_contract = {key: value for key, value in declaration.items() if key != "asset"}
        contract = _require_machine_contract(asset, observed_contract, name, relationship=name)
        if operator == "less_than":
            left_name = declaration.get("left")
            right_name = declaration.get("right")
            if left_name not in all_values or right_name not in all_values:
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
            valid = all_values[left_name] < all_values[right_name]
            observed = {str(left_name): all_values[left_name], str(right_name): all_values[right_name]}
        elif operator == "nonempty_upper_bounded_interval":
            subtract_names = contract.get("subtract")
            if isinstance(subtract_names, (str, bytes, bytearray)) or not isinstance(subtract_names, Sequence):
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Derived relationship operands are invalid.", relationship=name)
            minimum_name = contract.get("minimum")
            user_maximum_name = contract.get("user_maximum")
            required_names = [*subtract_names, minimum_name, user_maximum_name]
            if any(not isinstance(item, str) or item not in all_values for item in required_names):
                raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Relationship references a missing value.", relationship=name)
            constant = _finite_number(contract.get("constant_deg"), parameter=name)
            commutation_upper = constant - sum(all_values[item] for item in subtract_names)
            minimum = all_values[minimum_name]
            user_maximum = all_values[user_maximum_name]
            feasible_upper = min(user_maximum, commutation_upper)
            valid = minimum <= feasible_upper
            observed = {
                "commutation_upper": commutation_upper,
                "feasible_upper": feasible_upper,
                "minimum": minimum,
                "user_maximum": user_maximum,
                "subtract": {item: all_values[item] for item in subtract_names},
            }
            if valid:
                output = contract.get("output")
                formula = contract.get("formula")
                units = contract.get("units")
                if not isinstance(output, str) or not isinstance(formula, str) or not isinstance(units, str):
                    raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Derived relationship output is invalid.", relationship=name)
                derived.append(
                    DerivedParameter(
                        name=output,
                        value=feasible_upper,
                        source="derived",
                        formula=formula,
                        units=units,
                        constraints=(
                            f"{minimum} <= feasible firing angle <= {feasible_upper} {units}",
                        ),
                        asset=asset,
                    )
                )
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
    return derived


def _validate_return_assets(request: ParametricLccRequest, catalog: Mapping[str, Any]) -> None:
    requirements = _object(catalog["return_asset_requirements"], "return_asset_requirements")
    contract_assets = _object(catalog["return_contract_assets"], "return_contract_assets")
    authoritative_asset = contract_assets.get(request.topology)
    declaration_value = requirements.get(request.topology)
    if authoritative_asset is None and declaration_value is None:
        return
    if not isinstance(declaration_value, Mapping):
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Required topology return contract is missing.",
            topology=request.topology,
            asset=authoritative_asset,
        )
    declaration = _object(declaration_value, f"return_asset_requirements.{request.topology}")
    return_asset = declaration.get("asset")
    if return_asset != authoritative_asset:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Catalog return contract asset does not match the topology binding.",
            topology=request.topology,
            asset=authoritative_asset,
            observed_asset=return_asset,
        )
    observed_contract = {key: value for key, value in declaration.items() if key != "asset"}
    return_contract = _require_machine_contract(
        return_asset,
        observed_contract,
        f"return_asset_requirements.{request.topology}",
    )
    allowed_value = return_contract.get("allowed")
    if isinstance(allowed_value, (str, bytes, bytearray)) or not isinstance(allowed_value, Sequence):
        raise _error("LCC_PARAMETER_DERIVATION_FAILED", "Catalog allowed return assets are invalid.", topology=request.topology)
    allowed = set(allowed_value)
    unknown = sorted(set(request.return_path_assets) - allowed)
    if unknown:
        raise _error(
            "LCC_PARAMETER_DERIVATION_FAILED",
            "Return-path asset evidence is not declared by the catalog.",
            unknown_return_assets=unknown,
            allowed_return_assets=sorted(allowed),
        )
    required = set(return_contract.get("required", ()))
    mode_requirements = _object(return_contract.get("mode_requirements", {}), f"return_asset_requirements.{request.topology}.mode_requirements")
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
    relationship_parameters = _validate_relationships(ratings, engineering, catalog_data)
    _validate_return_assets(request, catalog_data)
    parameters = rating_parameters + [derived_power] + engineering_parameters + relationship_parameters
    return DerivedParameterReport(
        parameters=tuple(sorted(parameters, key=lambda item: item.name)),
        feasible=True,
        diagnostics=(),
    )
