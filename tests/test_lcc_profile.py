from __future__ import annotations

from pscad_mcp.hvdc.profiles import load_profile


def test_cigre_lcc_profile_has_explicit_read_only_result_contract():
    profile = load_profile("cigre_lcc_monopole_v1")

    assert profile["profile_version"] == 2
    assert profile["required_assets"] == ["rectifier", "inverter", "controller", "pole", "dc_line"]
    assert profile["command_bindings"] == []
    assert profile["sequences"] == []
    paths = {item["path"]: item["units"] for item in profile["result_channels"]}
    assert paths == {
        "Main/VDC_RECT": "kV",
        "Main/VDC_INV": "kV",
        "Main/IDC": "kA",
        "Main/P_RECT": "MW",
        "Main/Q_RECT": "MVAr",
        "Main/P_INV": "MW",
        "Main/Q_INV": "MVAr",
        "Main/ALPHA_RECT": "deg",
        "Main/GAMMA_INV": "deg",
        "Main/MU_RECT": "deg",
        "Main/VAC_RECT_A": "kV",
    }
    assert all(item.get("call_id") is None or item["call_id"] > 0 for item in profile["result_channels"])
