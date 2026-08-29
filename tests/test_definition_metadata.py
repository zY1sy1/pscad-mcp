import tempfile
import unittest
from pathlib import Path

from pscad_mcp.core import definition_metadata
from pscad_mcp.core.definition_metadata import read_definition_metadata

LIBRARY_XML = """<?xml version="1.0"?>
<project name="master">
  <Definitions>
    <Definition classid="UserCmpDefn" name="resistor">
      <form>
        <category>
          <parameter type="Real" name="R" min="0.0" max="100.0" />
          <parameter type="Real" name="OnlyMin" min="0.0" max="" />
          <parameter type="Choice" name="Mode">
            <choice>0 = Off</choice><choice>1 = On</choice>
          </parameter>
        </category>
      </form>
      <svg>
        <port model="Natural" name="A" x="0" y="0" dim="0" type="Removable" page="true" />
        <port model="Transfer" name="OUT" x="36" y="0" dim="1" type="Real" />
      </svg>
    </Definition>
  </Definitions>
</project>
"""


DUPLICATE_PORT_XML = """<?xml version="1.0"?>
<project name="master">
  <Definitions>
    <Definition classid="UserCmpDefn" name="multimeter">
      <paramlist><param name="Description" value="Multimeter" /></paramlist>
      <form>
        <category>
          <parameter type="Choice" name="MeasV" intent="Input">
            <value>0</value>
            <choice>0 = No</choice><choice>1 = Yes</choice>
          </parameter>
          <parameter type="Real" name="BaseV" unit="kV" min="0" max="1E+308" intent="Input">
            <value>230.0</value>
          </parameter>
        </category>
      </form>
      <svg>
        <port model="Natural" name="A" x="-18" y="0" dim="0" type="Removable">MeasV==0</port>
        <port model="Natural" name="A" x="-18" y="0" dim="0" type="NonRemovable" mode="Electrical">MeasV!=0</port>
      </svg>
    </Definition>
    <Definition classid="UserCmpDefn" name="multimeter">
      <svg><port model="Natural" name="OTHER" x="0" y="0" dim="1" type="NonRemovable" /></svg>
    </Definition>
  </Definitions>
</project>
"""


class TestDefinitionMetadata(unittest.TestCase):
    def test_reads_ports_and_parameter_ranges_from_pslx(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(LIBRARY_XML, encoding="utf-8")

            metadata = read_definition_metadata(path, "resistor")

        self.assertEqual([port.name for port in metadata.ports], ["A", "OUT"])
        self.assertEqual(metadata.ports[1].dim, 1)
        self.assertEqual(metadata.ports[1].type, "Real")
        self.assertEqual([port.page for port in metadata.ports], [True, False])
        self.assertEqual(metadata.parameter_ranges["R"], (0.0, 100.0))
        self.assertEqual(metadata.parameter_ranges["OnlyMin"], (0.0, None))
        self.assertEqual(metadata.parameter_ranges["Mode"], ["0", "1"])

    def test_missing_definition_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(LIBRARY_XML, encoding="utf-8")

            with self.assertRaisesRegex(KeyError, "ground"):
                read_definition_metadata(path, "ground")

    def test_preserves_duplicate_port_occurrences_and_parameter_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(DUPLICATE_PORT_XML, encoding="utf-8")

            matches = definition_metadata.read_definition_metadata_matches(
                path, "multimeter"
            )

        self.assertEqual(len(matches), 2)
        metadata = matches[0]
        self.assertEqual(metadata.name, "multimeter")
        self.assertEqual(metadata.description, "Multimeter")
        self.assertEqual(
            [(port.name, port.occurrence) for port in metadata.ports],
            [("A", 0), ("A", 1)],
        )
        self.assertEqual(metadata.ports[1].condition, "MeasV!=0")
        self.assertEqual(metadata.ports[1].model, "Natural")
        self.assertEqual(metadata.ports[1].mode, "Electrical")
        parameter = metadata.parameters["MeasV"]
        self.assertEqual(parameter.type, "Choice")
        self.assertIsNone(parameter.unit)
        self.assertEqual(parameter.choices, ("0", "1"))
        self.assertEqual(parameter.default, 0)
        self.assertEqual(parameter.intent, "Input")
        self.assertFalse(parameter.readonly)
        self.assertEqual(metadata.parameters["BaseV"].default, 230.0)

    def test_single_definition_wrapper_rejects_ambiguous_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(DUPLICATE_PORT_XML, encoding="utf-8")

            with self.assertRaisesRegex(KeyError, "ambiguous"):
                read_definition_metadata(path, "multimeter")


if __name__ == "__main__":
    unittest.main()
