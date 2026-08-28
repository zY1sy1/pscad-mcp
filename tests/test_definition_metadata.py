import tempfile
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
