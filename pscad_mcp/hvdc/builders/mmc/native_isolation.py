"""Native contact, reactor and MOV assemblies for external fault isolation.

The AC contact replaces the existing explicit grid resistor. The DC pole
contains a physical series reactor, a contact with preinsertion resistance,
and the installed Master nonlinear ZnO arrester. Arrester energy is in kJ,
as declared by the installed Master Energy parameter.
"""

from .avm_companion import _definition, _script, _manual_sequence, _Writer, _PARAMETER_UNITS

AC_ISOLATION = "MMCACIsolationPhase"
DC_ISOLATION = "MMCDCIsolationPole"
PREINSERT_LOGIC = "MMCPreinsertContacts"
CONTACT_STATUS = "MMCContactStatus"
NEUTRAL_GROUNDING = "MMCNeutralGrounding"
ISOLATION_OUTPUTS = {"CONTACT_STATE": "1", "MOV_CURRENT": "kA", "MOV_ENERGY": "kJ"}


def append_native_isolation(root, master, defaults):
    _PARAMETER_UNITS.update({"Contact_On_ohm": "ohm", "Contact_Off_ohm": "ohm",
        "Arrester_Rating_kV": "kV", "Reactor_H": "H", "Preinsert_ohm": "ohm", "Preinsert_Time_s": "s",
        "Neutral_L_H": "H", "Neutral_R_ohm": "ohm"})
    logic = _definition(root, PREINSERT_LOGIC,
        {"OPEN": (-72, 0, "Transfer", "Input"), "MAIN_OPEN": (72, -18, "Transfer", "Output"),
         "AUX_OPEN": (72, 18, "Transfer", "Output")}, {"Preinsert_Time_s": 0.02})
    _script(logic, "Dsdyn", """#STORAGE REAL:1
      IF (TIMEZERO) STORF(NSTORF) = 0.0
      $MAIN_OPEN = 1.0
      $AUX_OPEN = 1.0
      IF ($OPEN .GE. 0.5) THEN
        STORF(NSTORF) = 0.0
      ELSE
        STORF(NSTORF) = STORF(NSTORF) + DELT
        IF (STORF(NSTORF) .LT. $Preinsert_Time_s) THEN
          $AUX_OPEN = 0.0
        ELSE
          $MAIN_OPEN = 0.0
        ENDIF
      ENDIF
      NSTORF = NSTORF + 1
""")
    status = _definition(root, CONTACT_STATUS,
        {"MAIN_STATE": (-72, -18, "Transfer", "Input"), "AUX_STATE": (-72, 18, "Transfer", "Input"),
         "STATE": (72, 0, "Transfer", "Output")}, {})
    _script(status, "Dsdyn", "      $STATE = MIN($MAIN_STATE, $AUX_STATE)\n")
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
    neutral = _definition(root, NEUTRAL_GROUNDING,
        {**{p: (-90, -36 + i * 36, "Natural", "Electrical") for i, p in enumerate("ABC")},
         "G": (90, 0, "Natural", "Electrical"),
         **{f"I_{p}": (144, -36 + i * 36, "Transfer", "Output") for i, p in enumerate("ABC")}},
        {"Neutral_L_H": 10.0, "Neutral_R_ohm": 350.0})
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
        values = {"NAME": "MAIN_OPEN" if dc else "OPEN", "OPCUR": "1", "ENAB": "0", "ViewB": "0",
                  "RON": "Contact_On_ohm", "ROFF": "Contact_Off_ohm", "CLVL": "0.0 [kA]",
                  "IBR": "", "SBR": "MAIN_STATE_RAW" if dc else "CONTACT_STATE_RAW", "VBR": ""}
        if dc:
            writer.add(definition, "preinsert_control", root.get("name") + ":" + PREINSERT_LOGIC,
                       {"Preinsert_Time_s": "Preinsert_Time_s"}, {"OPEN": "OPEN", "MAIN_OPEN": "MAIN_OPEN", "AUX_OPEN": "AUX_OPEN"})
            add("preinsert_contact", "breaker1", {**values, "NAME": "AUX_OPEN", "RON": "Preinsert_ohm", "SBR": "AUX_STATE_RAW"},
                {"A": contact_in, "B": "OUT"})
            writer.add(definition, "contact_feedback", root.get("name") + ":" + CONTACT_STATUS, {},
                       {"MAIN_STATE": "MAIN_STATE_RAW", "AUX_STATE": "AUX_STATE_RAW", "STATE": "CONTACT_STATE_RAW"})
        add("contact", "breaker1", values, {"A": contact_in, "B": "OUT"})
        add("surge_arrester", "arrester", {"Name": "", "VSCAL": "Arrester_Rating_kV", "ISCAL": "1.0",
            "ENAB": "1", "Cnfg": "0", "Curr": "MOV_I", "Energy": "MOV_W_KJ"}, {"NF": contact_in, "NT": "OUT"})
        for port, signal in {"CONTACT_STATE": "CONTACT_STATE_RAW", "MOV_CURRENT": "MOV_I", "MOV_ENERGY": "MOV_W_KJ"}.items():
            add("output_" + port, "export", {"Name": port}, {"N": signal})
        if dc:
            _manual_sequence(definition, ((PREINSERT_LOGIC,), ("breaker1", "arrester", "varrlc"), (CONTACT_STATUS,), ("export",)))
    for name in ("A", "B", "C", "G"):
        writer.add(neutral, "terminal_" + name, "master:xnode", {"Name": name}, {"N": name})
    for name in ("Neutral_L_H", "Neutral_R_ohm"):
        writer.add(neutral, "input_" + name, "master:import", {"Name": name}, {"N": name})
    for phase in "ABC":
        writer.add(neutral, "reactor_" + phase, "master:varrlc",
                   {"RLC": "1", "L": "Neutral_L_H", "E": "0.0 [kV]", "dLdC": "0", "I": "CURRENT_" + phase},
                   {"A": phase, "B": "STAR"})
        writer.add(neutral, "output_" + phase, "master:export", {"Name": "I_" + phase}, {"N": "CURRENT_" + phase})
    writer.add(neutral, "neutral_resistor", "master:varrlc",
               {"RLC": "0", "R": "Neutral_R_ohm", "E": "0.0 [kV]", "dLdC": "0", "I": ""}, {"A": "STAR", "B": "G"})
    writer.verify()
    return writer
