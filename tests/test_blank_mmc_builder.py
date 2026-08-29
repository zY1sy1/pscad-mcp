from pscad_mcp.hvdc.builders.mmc.acceptance import evaluate_dc_fault_blocking
from pscad_mcp.hvdc.builders.mmc.blank import BlankMmcRequest, plan_blank_mmc
from pscad_mcp.hvdc.builders.mmc.models import SubmoduleTopology


def test_full_bridge_declares_intrinsic_dc_fault_blocking():
    assert SubmoduleTopology.FULL_BRIDGE.value == "full_bridge"
    assert (
        SubmoduleTopology.capabilities(SubmoduleTopology.FULL_BRIDGE)[
            "intrinsic_dc_fault_blocking"
        ]
        is True
    )
    assert (
        SubmoduleTopology.capabilities(SubmoduleTopology.HALF_BRIDGE)[
            "intrinsic_dc_fault_blocking"
        ]
        is False
    )


def test_mmc_dc_fault_acceptance_requires_negative_insertion_block_and_recovery():
    result = evaluate_dc_fault_blocking(
        {
            "fault_applied": True,
            "negative_voltage_inserted": True,
            "fault_current_peak_ka": 1.5,
            "fault_current_limit_ka": 2.0,
            "blocked": True,
            "recovered": True,
        },
        topology=SubmoduleTopology.FULL_BRIDGE,
    )
    assert result["verdict"] == "PASS"


def test_blank_mmc_plan_records_full_bridge_contract(tmp_path):
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_BLANK",
            "folder": str(tmp_path),
            "submodule_topology": "full_bridge",
            "ratings": {"dc_voltage_kv": 320.0, "power_mw": 1000.0},
        }
    )
    planned = plan_blank_mmc(request, workspace_root=str(tmp_path))
    assert planned["capabilities"]["intrinsic_dc_fault_blocking"] is True
    assert planned["component_contract"]["arms"] == 6
    assert planned["component_contract"]["submodules_per_arm"] == 4


def test_blank_mmc_plan_records_native_template_capability(tmp_path, monkeypatch):
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.mmc.template_audit.audit_mmc_template",
        lambda *_args: {
            "compatible": True,
            "submodule_topology": {"declared": "full_bridge"},
            "template_native_controls": {"available": True},
        },
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_BLANK",
            "folder": str(tmp_path),
            "template_path": str(template),
            "library_path": str(library),
        }
    )

    planned = plan_blank_mmc(request, workspace_root=str(tmp_path))

    assert planned["capabilities"]["template_submodule_topology"] == "full_bridge"
    assert planned["capabilities"]["template_native_timing"] is True
