"""Finite-resistance auxiliary sources for cold-starting a blocked full bridge."""

from .avm_companion import _definition, _manual_sequence, _Writer, _PARAMETER_UNITS, _SOURCE_PARAMETERS

AUXILIARY_NAME = "MMCAuxPrecharge"


def append_auxiliary_precharge(root, master, defaults):
    _PARAMETER_UNITS.update({"Aux_Voltage_kV": "kV", "Aux_Resistance_ohm": "ohm"})
    definition = _definition(root, AUXILIARY_NAME,
        {"POS": (-90, 0, "Natural", "Electrical"), "NEG": (90, 0, "Natural", "Electrical"),
         "OPEN": (-90, 72, "Transfer", "Input"),
         "CURRENT": (144, -18, "Transfer", "Output"), "STATE": (144, 18, "Transfer", "Output")},
        {"Aux_Voltage_kV": 640.0, "Aux_Resistance_ohm": 4000.0})
    writer = _Writer(root, master, defaults)
    add = lambda role, name, values, ports: writer.add(definition, role, "master:" + name, values, ports)
    for name in ("POS", "NEG"):
        add("terminal_" + name, "xnode", {"Name": name}, {"N": name})
    add("open_command", "import", {"Name": "OPEN"}, {"N": "OPEN"})
    add("voltage_order", "const", {"Name": "", "Value": "Aux_Voltage_kV"}, {"OUT": "SUPPLY_V"})
    add("physical_supply", "source_1", _SOURCE_PARAMETERS,
        {"NA": "SUPPLY_POS", "NB": "NEG", "Mag": "SUPPLY_V"})
    add("current_limiter", "varrlc", {"RLC": "0", "R": "Aux_Resistance_ohm", "E": "0.0 [kV]", "dLdC": "0", "I": ""},
        {"A": "SUPPLY_POS", "B": "CONTACT_IN"})
    add("disconnect", "breaker1", {"NAME": "OPEN", "OPCUR": "1", "ENAB": "0", "ViewB": "0",
        "RON": "0.001 [ohm]", "ROFF": "1.0e8 [ohm]", "CLVL": "0.0 [kA]", "IBR": "", "SBR": "CONTACT_STATE", "VBR": ""},
        {"A": "CONTACT_IN", "B": "METER_IN"})
    add("current_meter", "ammeter", {"Name": "AUX_I"}, {"N1": "METER_IN", "N2": "POS"})
    add("current_output", "export", {"Name": "CURRENT"}, {"N": "AUX_I"})
    add("state_output", "export", {"Name": "STATE"}, {"N": "CONTACT_STATE"})
    _manual_sequence(definition, (("const", "import"), ("source_1", "varrlc", "breaker1", "ammeter"), ("export",)))
    writer.verify()
    return writer
