"""Collect static MMC mapping evidence without starting PSCAD or a compiler."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pscad_mcp.core.definition_metadata import read_definition_metadata_document
from pscad_mcp.core.master_bindings import _normalized_dimension, _normalized_kind
from pscad_mcp.hvdc.builders.mmc.template_audit import discover_official_mmc_template


ASSETS = REPO / "pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1"
MMC_CODE = REPO / "pscad_mcp/hvdc/builders/mmc"
CANDIDATES = {
    "master:dc_bus": ["nodelabel", "short", "nodeloop", "xnode"],
    "master:dc_cable": ["cable_interface", "tline_interface", "resistor", "dc_mac_2w"],
    "master:transformer": ["xfmr-3p2w", "umec-xfmr-6w5L"],
    "master:source3": ["source3"],
    "master:pi_controller": ["pi_ctlr"],
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_name(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def xml_paths(root: ET.Element) -> dict[ET.Element, str]:
    result = {}

    def visit(node: ET.Element, path: str) -> None:
        result[node] = path
        counts: Counter[str] = Counter()
        for child in node:
            counts[child.tag] += 1
            visit(child, f"{path}/{child.tag}[{counts[child.tag]}]")

    visit(root, f"/{root.tag}[1]")
    return result


def reference(element: ET.Element) -> str | None:
    value = element.get("defn") or element.get("definition")
    if value:
        return value
    if element.tag == "User" and element.get("classid") == "UserCmp":
        return element.get("name")
    return None


def parameter_values(element: ET.Element) -> dict[str, str | None]:
    return {
        item.attrib["name"]: item.get("value")
        for item in element.findall("./paramlist/param")
        if item.get("name")
    }


def native_inventory(roots: dict[Path, ET.Element]) -> dict:
    definitions: dict[str, list[tuple[Path, ET.Element]]] = defaultdict(list)
    scopes = {}
    locations = {}
    for path, root in roots.items():
        scopes[path] = root.attrib["name"]
        locations[path] = xml_paths(root)
        for definition in root.findall("./definitions/Definition"):
            definitions[f"{scopes[path]}:{definition.attrib['name']}"].append(
                (path, definition)
            )

    project_path = next(path for path in roots if path.suffix == ".pscx")
    root_name = f"{scopes[project_path]}:Main"
    pending = [root_name]
    reachable = set()
    missing = set()
    while pending:
        scoped = pending.pop()
        if scoped in reachable or scoped.startswith("master:"):
            continue
        matches = definitions.get(scoped, [])
        if len(matches) != 1:
            missing.add(scoped)
            continue
        reachable.add(scoped)
        path, definition = matches[0]
        for element in definition.iter():
            ref = reference(element)
            if ref and not ref.startswith("master:"):
                pending.append(ref if ":" in ref else f"{scopes[path]}:{ref}")

    uses = []
    special_objects = []
    for scoped, matches in sorted(definitions.items()):
        for path, definition in matches:
            for element in definition.iter():
                ref = reference(element)
                if element.tag == "Wire" and element.get("classid") in {
                    "TLine",
                    "Cable",
                    "Bus",
                }:
                    parameters = parameter_values(element)
                    nested_user = element.find("User")
                    if nested_user is not None:
                        parameters.update(parameter_values(nested_user))
                    special_objects.append(
                        {
                            "source": source_name(path),
                            "parent_definition": scoped,
                            "reachable_from_main": scoped in reachable,
                            "xpath": locations[path][element],
                            "classid": element.get("classid"),
                            "owner_id": element.get("id"),
                            "reference": ref,
                            "parameters": parameters,
                        }
                    )
                if ref and ref.startswith("master:"):
                    uses.append(
                        {
                            "reference": ref,
                            "source": source_name(path),
                            "parent_definition": scoped,
                            "reachable_from_main": scoped in reachable,
                            "xpath": locations[path][element],
                            "tag": element.tag,
                            "classid": element.get("classid"),
                            "owner_id": element.get("id"),
                            "parameters": parameter_values(element),
                        }
                    )
    grouped = []
    for ref in sorted({item["reference"] for item in uses}):
        selected = [item for item in uses if item["reference"] == ref]
        grouped.append(
            {
                "reference": ref,
                "all_definition_occurrences": len(selected),
                "reachable_definition_occurrences": sum(
                    item["reachable_from_main"] for item in selected
                ),
                "consumers": selected,
            }
        )
    raw_references = {
        value
        for root in roots.values()
        for element in root.iter()
        for value in element.attrib.values()
        if value.startswith("master:")
    }
    unrecorded = raw_references - {item["reference"] for item in grouped}
    assert not unrecorded, f"Unrecorded native Master references: {sorted(unrecorded)}"
    return {
        "root_definition": root_name,
        "reachability_semantics": "Static User/Wire definition graph, not expanded instance counts or evaluated conditional activity.",
        "reachable_definitions": sorted(reachable),
        "missing_or_ambiguous_dependencies": sorted(missing),
        "definition_counts": {
            scope: sum(key.startswith(scope + ":") for key in definitions)
            for scope in scopes.values()
        },
        "references": grouped,
        "special_wire_objects": special_objects,
        "unrecorded_master_attribute_references": sorted(unrecorded),
    }


def code_inventory(snapshots: dict[Path, bytes]) -> tuple[list[dict], list[dict]]:
    references = []
    avm_parameters = []
    for path in sorted(MMC_CODE.rglob("*.py")):
        tree = ast.parse(snapshots[path].decode("utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("master:") and node.value != "master:":
                    references.append(
                        {
                            "reference": node.value,
                            "source": source_name(path),
                            "line": node.lineno,
                        }
                    )
            if path.name != "avm.py" or not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
                continue
            comparator = test.comparators[0]
            if not isinstance(comparator, ast.Constant) or not str(
                comparator.value
            ).startswith("master:"):
                continue
            for statement in node.body:
                for child in ast.walk(statement):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "update"
                    ):
                        for argument in child.args:
                            if isinstance(argument, ast.Dict):
                                for key, value in zip(argument.keys, argument.values):
                                    if isinstance(key, ast.Constant):
                                        avm_parameters.append(
                                            {
                                                "reference": comparator.value,
                                                "parameter": key.value,
                                                "expression": ast.unparse(value),
                                                "source": source_name(path),
                                                "line": key.lineno,
                                            }
                                        )
    return sorted(
        references, key=lambda item: (item["source"], item["line"])
    ), avm_parameters


def definition_evidence(name: str, document: dict, master_root: ET.Element) -> dict:
    matches = document.get(name, ())
    raw_definitions = [
        item
        for item in master_root.findall("./definitions/Definition")
        if item.get("name") == name
    ]
    assert len(matches) == len(raw_definitions), (
        f"Metadata/XML definition count mismatch: {name}"
    )
    result = {
        "name": f"master:{name}",
        "exact_definition_count": len(matches),
        "matches": [],
    }
    for metadata, raw in zip(matches, raw_definitions):
        entry = asdict(metadata)
        raw_params = {
            item.attrib["name"]: item
            for item in raw.findall(".//form//parameter")
            if item.get("name")
        }
        for key, parameter in entry["parameters"].items():
            source = raw_params[key]
            parameter["description"] = source.get("desc")
            parameter["raw_attributes"] = dict(source.attrib)
            parameter["condition"] = (source.findtext("cond") or "").strip()
            parameter["choice_labels"] = [
                (item.text or "").strip() for item in source.findall("choice")
            ]
        for port, parsed_port in zip(entry["ports"], metadata.ports):
            port["interpreted_kind"] = _normalized_kind(parsed_port)
            port["interpreted_dimension"] = _normalized_dimension(parsed_port)
            port["interpretation_source"] = "pscad_mcp.core.master_bindings"
            port["activation_evaluated"] = False
        result["matches"].append(entry)
    return result


def collect(master: Path) -> dict:
    project, library = discover_official_mmc_template()
    sources = set(MMC_CODE.rglob("*.py")) | {
        path for path in ASSETS.rglob("*") if path.is_file()
    }
    sources.update(
        {
            master,
            project,
            library,
            Path(__file__).resolve(),
            REPO / "pscad_mcp/core/definition_metadata.py",
            REPO / "pscad_mcp/core/master_bindings.py",
            REPO / "pscad_mcp/core/backend/legacy.py",
            REPO / "pscad_mcp/hvdc/scenarios.py",
        }
    )
    snapshots = {path: path.read_bytes() for path in sorted(sources)}
    master_root = ET.fromstring(snapshots[master])
    metadata = read_definition_metadata_document(snapshots[master])
    blueprint = json.loads(snapshots[ASSETS / "blueprint.json"])
    catalog = json.loads(snapshots[ASSETS / "catalog-pscad-4.6.2.json"])
    companion = ET.fromstring(snapshots[ASSETS / "library/cigre_mmc_avm_v1.pslx"])
    native = native_inventory(
        {
            project: ET.fromstring(snapshots[project]),
            library: ET.fromstring(snapshots[library]),
        }
    )
    code_refs, parameter_overrides = code_inventory(snapshots)
    uses: dict[str, list[dict]] = defaultdict(list)
    for index, component in enumerate(blueprint["components"]):
        if not component["definition"].startswith("master:"):
            continue
        incident = [
            net
            for net in blueprint["nets"]
            if any(
                endpoint.rsplit(":", 1)[0] == component["logical_id"]
                for endpoint in net["endpoints"]
            )
        ]
        uses[component["definition"]].append(
            {
                "consumer": "fixed_avm_and_parametric_avm",
                "source": source_name(ASSETS / "blueprint.json"),
                "json_pointer": f"/components/{index}",
                "component": component,
                "incident_nets": incident,
                "port_dimension_declared": False,
            }
        )
    companion_paths = xml_paths(companion)
    for definition in companion.findall("./library/definition"):
        for element in definition.iter():
            ref = reference(element)
            if ref and ref.startswith("master:"):
                uses[ref].append(
                    {
                        "consumer": "packaged_companion_internal_contract",
                        "source": source_name(ASSETS / "library/cigre_mmc_avm_v1.pslx"),
                        "xpath": companion_paths[element],
                        "parent_definition": definition.attrib["name"],
                        "port_contract": None,
                        "parameter_contract": None,
                    }
                )
    for ref in code_refs:
        uses[ref["reference"]].append({"consumer": "python_literal", **ref})
    packaged = []
    for ref, consumers in sorted(uses.items()):
        local = ref.split(":", 1)[1]
        packaged.append(
            {
                "reference": ref,
                "installed_exact_count": len(metadata.get(local, ())),
                "packaged_catalog_entry": catalog["definitions"].get(ref),
                "consumers": consumers,
                "parametric_parameter_overrides": [
                    item for item in parameter_overrides if item["reference"] == ref
                ],
                "physical_candidates_for_review_only": CANDIDATES.get(ref, []),
                "binding_verified": False,
            }
        )
    requested = {
        ref["reference"].split(":", 1)[1] for ref in packaged + native["references"]
    }
    requested.update(name for names in CANDIDATES.values() for name in names)
    for ref in native["references"]:
        local = ref["reference"].split(":", 1)[1]
        ref["installed_exact_count"] = len(metadata.get(local, ()))
    all_endpoints = {
        endpoint for net in blueprint["nets"] for endpoint in net["endpoints"]
    }
    arms = [
        component
        for component in blueprint["components"]
        if component["definition"].endswith(":MMCAverageArm")
    ]
    evidence = {
        "schema_version": 1,
        "audit_kind": "read_only_mmc_master_offline_pre_audit",
        "baseline_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "pscad_started": False,
        "compiler_started": False,
        "licensed_acceptance": "NOT_RUN",
        "mapping_status": "CANDIDATES_ONLY",
        "installed_master": {
            "path": source_name(master),
            "root_attributes": dict(master_root.attrib),
            "unique_definition_count": len(metadata),
        },
        "sources": [
            {
                "path": source_name(path),
                "size_bytes": len(payload),
                "sha256_before": sha256(payload),
                "sha256_after": sha256(path.read_bytes()),
            }
            for path, payload in sorted(snapshots.items())
        ],
        "coverage": {
            "fixed_avm_and_catalog": "All Master component entries, net endpoints, and catalog coverage in the packaged asset set.",
            "parametric_avm": "All Python Master literals and parameter update dictionaries in the AVM adapter.",
            "blank_recipe": "Semantic roles only; the executable blank/native path clones the official template pair.",
            "blank_native_and_pwm": "All Master occurrences in the official project and sibling library, separated by static reachability from Main; native TLine/Cable/Bus objects are recorded separately.",
            "scenario_control": "Existing template control components are included through the native graph; native scenario code edits parameters, not new Master definitions. Future WP3 insertion is undefined.",
            "packaged_companion": "All internal Master references in the repository contract XML. This is not native PSCAD Definition XML.",
            "limitations": [
                "Port conditions and parent parameter expressions are retained without evaluation.",
                "Definition occurrences are not expanded runtime instance counts.",
                "Static presence does not prove physical behavior, compilation, or simulation.",
                "No arbitrary user template or future generated companion is covered.",
            ],
        },
        "packaged_master_references": packaged,
        "native_template": native,
        "physical_definition_metadata": {
            name: definition_evidence(name, metadata, master_root)
            for name in sorted(requested)
        },
        "topology_observations": {
            "component_count": len(blueprint["components"]),
            "arm_count": len(arms),
            "nets": blueprint["nets"],
            "arm_net_membership": {
                arm["logical_id"]: sorted(
                    endpoint
                    for endpoint in all_endpoints
                    if endpoint.rsplit(":", 1)[0] == arm["logical_id"]
                )
                for arm in arms
            },
            "companion_root_tag": companion.tag,
            "companion_native_definition_count": len(
                companion.findall(".//Definition")
            ),
            "companion_contract_definition_count": len(
                companion.findall(".//definition")
            ),
            "catalog_master_definition_count": sum(
                name.startswith("master:") for name in catalog["definitions"]
            ),
        },
    }
    assert all(
        item["sha256_before"] == item["sha256_after"] for item in evidence["sources"]
    ), "An audited source changed during collection."
    return evidence


def inventory_markdown(evidence: dict) -> str:
    lines = [
        "# MMC Master Reference Inventory",
        "",
        f"Baseline commit: `{evidence['baseline_commit']}`.",
        "",
        "Generated by `collect_evidence.py`. Physical candidates are not verified bindings.",
        "",
        "## Packaged Fixed / Parametric AVM",
        "",
        "| Logical reference | Exact installed count | Catalog contract present | Candidate names for review |",
        "| --- | ---: | --- | --- |",
    ]
    for item in evidence["packaged_master_references"]:
        candidates = ", ".join(
            f"`{name}`" for name in item["physical_candidates_for_review_only"]
        )
        lines.append(
            f"| `{item['reference']}` | {item['installed_exact_count']} | {item['packaged_catalog_entry'] is not None} | {candidates} |"
        )
    lines += [
        "",
        "## Official Template / Library",
        "",
        "Reachable counts are definition-level occurrences reachable from Main, not expanded runtime instance counts.",
        "All counts include unused definitions in the sibling library. Conditional activation is not evaluated.",
        "Per-consumer XPath, owner ID and parameter values, and every conditional port and parameter contract are in `evidence.json`.",
        "",
        "| Master reference | Reachable occurrences | All occurrences | Exact installed count | Description |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for item in evidence["native_template"]["references"]:
        metadata = evidence["physical_definition_metadata"][
            item["reference"].split(":", 1)[1]
        ]
        description = (
            "; ".join(record["description"] or "" for record in metadata["matches"])
            .replace("|", "\\|")
            .replace("\n", " ")
        )
        lines.append(
            f"| `{item['reference']}` | {item['reachable_definition_occurrences']} | {item['all_definition_occurrences']} | {item['installed_exact_count']} | {description} |"
        )
    lines += [
        "",
        "## Native Wire Objects",
        "",
        "| Parent definition | Class | Owner ID | Name | Reference |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in evidence["native_template"]["special_wire_objects"]:
        lines.append(
            f"| `{item['parent_definition']}` | `{item['classid']}` | `{item['owner_id']}` | `{item['parameters'].get('Name', '')}` | `{item['reference'] or ''}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master",
        type=Path,
        default=Path(r"C:\Program Files (x86)\PSCAD46\master.pslx"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("evidence.json")
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Recollect and compare with the saved evidence; write nothing.",
    )
    args = parser.parse_args()
    evidence = collect(args.master.resolve())
    encoded = json.dumps(evidence, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    inventory = inventory_markdown(evidence)
    inventory_path = args.output.with_suffix(".md")
    if args.verify:
        assert json.loads(args.output.read_text(encoding="utf-8")) == json.loads(
            encoded
        ), "Saved evidence differs from current sources or extraction."
        assert inventory_path.read_text(encoding="utf-8") == inventory, (
            "Saved inventory differs from the evidence."
        )
    else:
        if args.output.exists() or inventory_path.exists():
            raise FileExistsError(
                "Evidence or inventory exists; use --verify or a new --output path."
            )
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
        with inventory_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(inventory)
    native = evidence["native_template"]["references"]
    print(
        json.dumps(
            {
                "verification": "MATCH" if args.verify else "COLLECTED",
                "output": str(args.output.resolve()),
                "sources": len(evidence["sources"]),
                "packaged_references": len(evidence["packaged_master_references"]),
                "native_references_all": len(native),
                "native_references_reachable": sum(
                    item["reachable_definition_occurrences"] > 0 for item in native
                ),
                "native_missing_reachable_master": [
                    item["reference"]
                    for item in native
                    if item["reachable_definition_occurrences"]
                    and item["installed_exact_count"] != 1
                ],
                "native_missing_dependencies": evidence["native_template"][
                    "missing_or_ambiguous_dependencies"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
