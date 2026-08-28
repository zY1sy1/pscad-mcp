from pscad_mcp.hvdc.profiles import bind_profile_project, load_profile


def test_mmc_v2_profiles_use_project_qualified_exact_bindings() -> None:
    for name, project in (
        ("mmc_detailed_pwm_v2", "MMC_CASE_pwm"),
        ("mmc_average_value_v2", "MMC_CASE_avm"),
    ):
        profile = load_profile(name)
        assert profile["profile_version"] == 2
        assert profile["project_fingerprints"] == [
            {"project_stem": project, "pscad_version": "4.6.2"}
        ]
        assert profile["command_bindings"]
        assert all(binding["component"] for binding in profile["command_bindings"])
        assert all(binding["parameter_name"] for binding in profile["command_bindings"])
        assert all(
            channel["path"].startswith(f"{project}/")
            for channel in profile["result_channels"]
        )
        command_canonicals = {
            binding["canonical"] for binding in profile["command_bindings"]
        }
        assert not command_canonicals & {
            mapping["canonical"] for mapping in profile["mappings"]
        }


def test_detailed_pwm_profile_uses_audited_official_component_parameters() -> None:
    profile = load_profile("mmc_detailed_pwm_v2")
    bindings = {item["canonical"]: item for item in profile["command_bindings"]}

    assert bindings["active_power_order"]["component"] == {"component_id": "800413106"}
    assert bindings["active_power_order"]["parameter_name"] == "Pref"
    assert bindings["ac_breaker_command"]["parameter_name"] == "ACBrkCtrl"
    assert bindings["ac_fault_command"]["component"] == {"component_id": "326579344"}


def test_mmc_v2_profiles_bind_exact_custom_derived_project() -> None:
    original = load_profile("mmc_average_value_v2")

    bound = bind_profile_project(original, "D:/workspace/CUSTOM_CASE_avm.pscx")

    assert bound["project_fingerprints"] == [
        {"project_stem": "CUSTOM_CASE_avm", "pscad_version": "4.6.2"}
    ]
    assert all(
        channel["path"].startswith("CUSTOM_CASE_avm/")
        for channel in bound["result_channels"]
    )
    assert original == load_profile("mmc_average_value_v2")
