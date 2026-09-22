"""Native contact, reactor and MOV assemblies for external fault isolation.

The AC contact replaces the existing explicit grid resistor. The DC pole
contains a physical series reactor, a contact with preinsertion resistance,
and the installed Master nonlinear ZnO arrester. Arrester energy is in kJ,
as declared by the installed Master Energy parameter.
"""

from .avm_companion import _definition, _Writer, _PARAMETER_UNITS

AC_ISOLATION = "MMCACIsolationPhase"
DC_ISOLATION = "MMCDCIsolationPole"
ISOLATION_OUTPUTS = {"CONTACT_STATE": "1", "MOV_CURRENT": "kA", "MOV_ENERGY": "kJ"}


def append_native_isolation(root, master, defaults):
    _PARAMETER_UNITS.update({"Contact_On_ohm": "ohm", "Contact_Off_ohm": "ohm",
        "Arrester_Rating_kV": "kV", "Reactor_H": "H", "Preinsert_ohm": "ohm", "Preinsert_Time_s": "s"})
    definitions = []
    for name, dc in ((AC_ISOLATION, False), (DC_ISOLATION, True)):
        parameters = {"Contact_On_ohm": 0.001 if dc else 0.1, "Contact_Off_ohm": 1e8,
                      "Arrester_Rating_kV": 300.0 if dc else 210.0}
        if dc:
            parameters.update(Reactor_H=0.05, Preinsert_ohm=150.0, Preinsert_Time_s=0.02)
        ports = {"IN": (-90, 0, "Natural", "Electrical"), "OUT": (90, 0, "Natural", "Electrical"),
                 "OPEN": (-90, 72, "Transfer", "Input"),
                 **{n: (144, -54 + i * 36, "Transfer", "Output") for i, n in enumerate(ISOLATION_OUTPUTS)}}
        definitions.append((_definition(root, name, ports, parameters), parameters, dc))
    writer = _Writer(root, master, defaults)
    for definition, parameters, dc in definitions:
        add = lambda role, name, values, bindings: writer.add(definition, role, "master:" + name, values, bindings)
        for n in ("IN", "OUT"):
            add("terminal_" + n, "xnode", {"Name": n}, {"N": n})
        for n in ("OPEN", *parameters):
            add("input_" + n, "import", {"Name": n}, {"N": n})
        contact_in = "CONTACT_IN" if dc else "IN"
        if dc:
            add("series_reactor", "varrlc", {"RLC": "1", "L": "Reactor_H", "E": "0.0 [kV]", "dLdC": "0", "I": ""},
                {"A": "IN", "B": contact_in})
        values = {"NAME": "OPEN", "OPCUR": "1", "ENAB": "1" if dc else "0", "ViewB": "0",
                  "RON": "Contact_On_ohm", "ROFF": "Contact_Off_ohm", "CLVL": "0.0 [kA]",
                  "IBR": "", "SBR": "CONTACT_STATE_RAW", "VBR": ""}
        if dc:
            values.update(PRER="Preinsert_ohm", TDR="Preinsert_Time_s", TD="0.0 [s]", PostIns="0")
        add("contact", "breaker1", values, {"A": contact_in, "B": "OUT"})
        add("surge_arrester", "arrester", {"Name": "", "VSCAL": "Arrester_Rating_kV", "ISCAL": "1.0",
            "ENAB": "1", "Cnfg": "0", "Curr": "MOV_I", "Energy": "MOV_W_KJ"}, {"NF": contact_in, "NT": "OUT"})
        for port, signal in {"CONTACT_STATE": "CONTACT_STATE_RAW", "MOV_CURRENT": "MOV_I", "MOV_ENERGY": "MOV_W_KJ"}.items():
            add("output_" + port, "export", {"Name": port}, {"N": signal})
    writer.verify()
    return writer
