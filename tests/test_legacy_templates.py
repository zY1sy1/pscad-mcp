from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from importlib.resources import as_file, files

from pscad_mcp.core.backend.legacy_support import project_kind


TEMPLATES = (
    ("empty_case.pscx", "empty_case", "case"),
    ("empty_library.pslx", "empty_library", "library"),
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class TestLegacyTemplates(unittest.TestCase):
    def _load_template(self, filename: str) -> tuple[bytes, ET.Element]:
        resource = (
            files("pscad_mcp")
            .joinpath("assets")
            .joinpath("templates")
            .joinpath(filename)
        )
        with as_file(resource) as template_path:
            self.assertTrue(template_path.is_file(), f"missing template: {filename}")
            payload = template_path.read_bytes()
            root = ET.parse(template_path).getroot()
        return payload, root

    def test_templates_are_packaged_parseable_pscad_projects(self):
        for filename, expected_name, expected_kind in TEMPLATES:
            with self.subTest(filename=filename):
                payload, root = self._load_template(filename)
                suffix = "." + filename.rsplit(".", 1)[-1]

                self.assertEqual(_local_name(root.tag), "project")
                self.assertEqual(root.get("name"), expected_name)
                self.assertEqual(root.get("version"), "4.6.2")
                self.assertEqual(project_kind(root, suffix), expected_kind)
                self.assertGreater(
                    len(payload),
                    3_000,
                    "PSCAD templates must be native saved projects, not minimal XML stubs",
                )
                self.assertEqual(
                    Counter(_local_name(element.tag) for element in root.iter()),
                    Counter(
                        {
                            "project": 1,
                            "paramlist": 7,
                            "param": 42,
                            "Layers": 1,
                            "List": 1,
                            "definitions": 1,
                            "Definition": 2,
                            "schematic": 2,
                            "Wire": 1,
                            "vertex": 4,
                            "User": 1,
                            "form": 1,
                            "svg": 1,
                            "rect": 1,
                            "text": 1,
                            "hierarchy": 1,
                            "call": 2,
                        }
                    ),
                    "PSCAD templates must retain exactly the native blank skeleton",
                )

    def test_templates_contain_no_model_or_simulation_artifacts(self):
        forbidden_tags = {
            "bus",
            "channel",
            "curve",
            "datafile",
            "dataset",
            "frame",
            "graph",
            "output",
            "overlay",
            "simulation",
            "trace",
        }

        expected_classids = Counter(
            {
                "Settings": 1,
                "StationCanvas": 1,
                "StationDefn": 1,
                "UserCanvas": 1,
                "UserCmp": 1,
                "UserCmpDefn": 1,
                "WireBranch": 1,
            }
        )

        for filename, expected_name, _ in TEMPLATES:
            with self.subTest(filename=filename):
                _, root = self._load_template(filename)
                tags = Counter(_local_name(element.tag).casefold() for element in root.iter())
                present = {tag: tags[tag] for tag in forbidden_tags if tags.get(tag)}
                self.assertEqual(
                    present,
                    {},
                    "blank templates must not contain buses, frames, graph/output objects, "
                    "channels, traces, or simulation data",
                )

                classids = Counter(
                    element.get("classid")
                    for element in root.iter()
                    if element.get("classid") is not None
                )
                self.assertEqual(
                    classids,
                    expected_classids,
                    "blank templates may contain only PSCAD's Station/Main skeleton objects",
                )

                definitions = root.findall("./definitions/Definition")
                self.assertEqual(
                    [(node.get("classid"), node.get("name")) for node in definitions],
                    [("StationDefn", "Station"), ("UserCmpDefn", "Main")],
                )

                wires = root.findall("./definitions/Definition/schematic/Wire")
                self.assertEqual(len(wires), 1)
                self.assertEqual(
                    (wires[0].get("classid"), wires[0].get("name"), wires[0].get("defn")),
                    ("WireBranch", "STUB", "STUB"),
                )

                users = root.findall("./definitions/Definition/schematic/Wire/User")
                self.assertEqual(len(users), 1)
                self.assertEqual(users[0].get("classid"), "UserCmp")
                self.assertEqual(users[0].get("name"), f"{expected_name}:Main")
                self.assertEqual(users[0].get("defn"), f"{expected_name}:Main")

                calls = root.findall("./hierarchy/call")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].get("name"), f"{expected_name}:Station")
                self.assertEqual(len(calls[0].findall("./call")), 1)
                self.assertEqual(
                    calls[0].find("./call").get("name"),
                    f"{expected_name}:Main",
                )

    def test_templates_do_not_embed_machine_identity_or_revision_time(self):
        for filename, _, _ in TEMPLATES:
            with self.subTest(filename=filename):
                _, root = self._load_template(filename)
                settings = {
                    node.get("name"): node.get("value")
                    for node in root.findall("./paramlist[@name='Settings']/param")
                }
                self.assertEqual(settings.get("creator"), "0,0")
                self.assertEqual(settings.get("revisor"), "0,0")
                self.assertNotIn("335", settings.get("creator", ""))
                self.assertNotIn("335", settings.get("revisor", ""))


if __name__ == "__main__":
    unittest.main()
