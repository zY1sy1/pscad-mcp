import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy_support import (
    Rect,
    candidate_rectangles,
    project_kind,
    require_success,
    response_payload,
    rewrite_project_identity,
    snap_to_grid,
)


class TestLegacyResponses(unittest.TestCase):
    def test_require_success_returns_original_true_response(self):
        response = ET.fromstring('<response success="TrUe" />')

        self.assertIs(
            require_success(response, "save-as", {"project": "case"}), response
        )

    def test_require_success_rejects_false_missing_and_non_xml_responses(self):
        for response in (
            ET.fromstring('<response success="false"><message>denied</message></response>'),
            ET.fromstring("<response />"),
            None,
            object(),
        ):
            with self.subTest(response_type=type(response).__name__):
                with self.assertRaises(BackendError) as caught:
                    require_success(response, "save-as", {"project": "case"})

                error = caught.exception
                self.assertEqual(error.code, "PSCAD_COMMAND_FAILED")
                self.assertEqual(error.backend, "legacy")
                self.assertEqual(error.operation, "save-as")
                self.assertEqual(error.details["project"], "case")
                self.assertIn("response", error.details)
                json.dumps(error.to_dict())

    def test_response_payload_is_json_safe_and_bounded(self):
        response = ET.fromstring(
            '<response success="false" object="ignored"><message>'
            + ("x" * 1_000)
            + "</message></response>"
        )

        payload = response_payload(response)

        self.assertEqual(payload["tag"], "response")
        self.assertEqual(payload["success"], "false")
        self.assertLess(len(payload["children"][0]["text"]), 1_000)
        json.dumps(payload)
        self.assertEqual(response_payload(object())["type"], "object")

    def test_response_payload_flattens_non_reserved_attributes_without_spoofing_structure(self):
        response = ET.fromstring(
            '<response tag="wrong" children="wrong" attributes="wrong" success="false">'
            "<message>denied</message></response>"
        )

        payload = response_payload(response)

        self.assertEqual(payload["tag"], "response")
        self.assertEqual(payload["children"][0]["tag"], "message")
        self.assertEqual(payload["success"], "false")
        self.assertEqual(
            payload["reserved_attributes"],
            {"tag": "wrong", "children": "wrong", "attributes": "wrong"},
        )
        json.dumps(payload)


class TestProjectIdentityRewrite(unittest.TestCase):
    def test_rewrite_changes_only_project_and_project_level_output_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pscx"
            target = folder / "new.pscx"
            source_text = (
                '<?xml version="1.0"?><project name="old" Target="EMTDC">\n'
                '  <output name="old" />\n'
                '  <section><output name="old" /></section>\n'
                '  <param value="old must remain" />\n'
                "</project>"
            )
            source.write_text(source_text, encoding="utf-8")

            rewrite_project_identity(source, target, "new")

            root = ET.parse(target).getroot()
            self.assertEqual(root.get("name"), "new")
            self.assertEqual(root.find("output").get("name"), "new")
            self.assertEqual(root.find("section/output").get("name"), "old")
            self.assertEqual(root.find("param").get("value"), "old must remain")
            self.assertEqual(source.read_text(encoding="utf-8"), source_text)
            self.assertEqual(list(folder.glob(".new.pscx.*.tmp")), [])

    def test_rewrite_supports_same_source_and_destination_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.pscx"
            path.write_text(
                '<project name="old" Target="EMTDC"><output name="old" /></project>',
                encoding="utf-8",
            )

            rewrite_project_identity(path, path, "new")

            root = ET.parse(path).getroot()
            self.assertEqual(root.get("name"), "new")
            self.assertEqual(root.find("output").get("name"), "new")

    def test_rewrite_same_name_preserves_source_bytes_and_same_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pscx"
            destination = folder / "copy.pscx"
            source_bytes = (
                "<?xml version='1.0' encoding='UTF-8'?>\r\n"
                "<project name='old' Target='EMTDC'>\r\n"
                "  <output note=\"embedded name='junk' must remain\" name='old' />\r\n"
                "</project>\r\n"
            ).encode("utf-8")
            source.write_bytes(source_bytes)

            rewrite_project_identity(source, destination, "old")

            self.assertEqual(destination.read_bytes(), source_bytes)
            self.assertEqual(source.read_bytes(), source_bytes)
            rewrite_project_identity(source, source, "old")
            self.assertEqual(source.read_bytes(), source_bytes)

    def test_rewrite_preserves_utf16_bom_and_crlf_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pscx"
            destination = folder / "new.pscx"
            source_text = (
                '<?xml version="1.0" encoding="UTF-16"?>\r\n'
                '<project name="old" Target="EMTDC">\r\n'
                '  <output name="old" />\r\n'
                '  <param value="old must remain" />\r\n'
                "</project>\r\n"
            )
            source_bytes = source_text.encode("utf-16")
            source.write_bytes(source_bytes)

            rewrite_project_identity(source, destination, "new")

            self.assertEqual(
                destination.read_bytes(),
                source_text.replace('name="old"', 'name="new"').encode("utf-16"),
            )
            self.assertTrue(destination.read_bytes().startswith(b"\xff\xfe"))
            self.assertEqual(source.read_bytes(), source_bytes)

    def test_rewrite_preserves_utf16_and_utf32_bom_and_byte_order(self):
        encodings = (
            ("utf-16-le", b"\xff\xfe", "UTF-16"),
            ("utf-16-be", b"\xfe\xff", "UTF-16"),
            ("utf-32-le", b"\xff\xfe\x00\x00", "UTF-32"),
            ("utf-32-be", b"\x00\x00\xfe\xff", "UTF-32"),
        )
        for codec, bom, declared in encodings:
            for include_bom in (True, False):
                with self.subTest(codec=codec, include_bom=include_bom):
                    with tempfile.TemporaryDirectory() as temporary:
                        folder = Path(temporary)
                        source = folder / "old.pscx"
                        destination = folder / "new.pscx"
                        source_text = (
                            f'<?xml version="1.0" encoding="{declared}"?>\r\n'
                            '<project name="old" Target="EMTDC">\r\n'
                            '  <output name="old" />\r\n'
                            "</project>\r\n"
                        )
                        source_bytes = (bom if include_bom else b"") + source_text.encode(codec)
                        source.write_bytes(source_bytes)

                        rewrite_project_identity(source, destination, "new")

                        self.assertEqual(
                            destination.read_bytes(),
                            (bom if include_bom else b"")
                            + source_text.replace('name="old"', 'name="new"').encode(codec),
                        )
                        self.assertEqual(source.read_bytes(), source_bytes)

    def test_rewrite_changes_only_unqualified_output_name_attribute(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pscx"
            destination = folder / "new.pscx"
            source.write_text(
                '<project xmlns:x="urn:test" name="old" Target="EMTDC">'
                '<output x:name="old" name="old" />'
                '</project>',
                encoding="utf-8",
            )

            rewrite_project_identity(source, destination, "new")

            output = ET.parse(destination).getroot().find("output")
            self.assertEqual(output.get("name"), "new")
            self.assertEqual(output.get("{urn:test}name"), "old")

    def test_rewrite_preserves_library_bytes_and_rewrites_all_matching_output_entities(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pslx"
            destination = folder / "new.pslx"
            source_text = (
                "<?xml version='1.0' encoding='UTF-8'?>\r\n"
                "<project name='旧名' Target='Library'>\r\n"
                "  <output name='&#26087;&#21517;' />\r\n"
                "  <output name='旧名' />\r\n"
                "  <param value='旧名 must remain' />\r\n"
                "</project>\r\n"
            )
            source_bytes = source_text.encode("utf-8")
            source.write_bytes(source_bytes)

            rewrite_project_identity(source, destination, "新名")

            expected = source_text.replace("name='旧名'", "name='新名'").replace(
                "name='&#26087;&#21517;'", "name='新名'"
            ).encode("utf-8")
            self.assertEqual(destination.read_bytes(), expected)
            root = ET.parse(destination).getroot()
            self.assertEqual(root.get("name"), "新名")
            self.assertEqual([output.get("name") for output in root.findall("output")], ["新名", "新名"])
            self.assertEqual(root.find("param").get("value"), "旧名 must remain")
            self.assertEqual(source.read_bytes(), source_bytes)

    def test_rewrite_rejects_kind_suffix_mismatch_without_damaging_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "library.pslx"
            destination = folder / "case.pscx"
            source.write_text(
                '<project name="library" Target="Library"><output name="library" /></project>',
                encoding="utf-8",
            )
            destination.write_text("do not replace", encoding="utf-8")

            with self.assertRaises(ValueError):
                rewrite_project_identity(source, destination, "case")

            self.assertEqual(destination.read_text(encoding="utf-8"), "do not replace")
            self.assertEqual(list(folder.glob(".case.pscx.*.tmp")), [])

    def test_rewrite_removes_temp_file_when_replacement_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "old.pscx"
            destination = folder / "new.pscx"
            source.write_text(
                '<project name="old" Target="EMTDC"><output name="old" /></project>',
                encoding="utf-8",
            )
            destination.write_text("do not replace", encoding="utf-8")

            with patch(
                "pscad_mcp.core.backend.legacy_support.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    rewrite_project_identity(source, destination, "new")

            self.assertEqual(destination.read_text(encoding="utf-8"), "do not replace")
            self.assertEqual(list(folder.glob(".new.pscx.*.tmp")), [])

    def test_rewrite_rejects_malformed_xml_and_wrong_root_without_damaging_destination(self):
        for source_text in (
            '<project name="old" Target="EMTDC"><output name="old">',
            '<library name="old" Target="EMTDC"><output name="old" /></library>',
        ):
            with self.subTest(source_text=source_text):
                with tempfile.TemporaryDirectory() as temporary:
                    folder = Path(temporary)
                    source = folder / "old.pscx"
                    destination = folder / "new.pscx"
                    source.write_text(source_text, encoding="utf-8")
                    destination.write_text("do not replace", encoding="utf-8")

                    with self.assertRaises((ET.ParseError, ValueError)):
                        rewrite_project_identity(source, destination, "new")

                    self.assertEqual(destination.read_text(encoding="utf-8"), "do not replace")
                    self.assertEqual(list(folder.glob(".new.pscx.*.tmp")), [])


class TestProjectKindAndGeometry(unittest.TestCase):
    def test_project_kind_accepts_pscad_target_markers_and_checks_suffix(self):
        case_root = ET.fromstring('<project Target="EMTDC" />')
        library_root = ET.fromstring('<project Target="Library" />')

        self.assertEqual(project_kind(case_root, ".pscx"), "case")
        self.assertEqual(project_kind(library_root, ".pslx"), "library")
        with self.assertRaises(ValueError):
            project_kind(case_root, ".pslx")
        with self.assertRaises(ValueError):
            project_kind(case_root, ".txt")

    def test_rectangles_touching_margin_intersect(self):
        occupied = Rect(18, 18, 36, 18)
        candidate = Rect(54, 18, 18, 18)

        self.assertTrue(occupied.intersects(candidate, margin=18))

    def test_candidates_begin_snapped_and_are_grid_aligned_unique_and_deterministic(self):
        candidates = list(candidate_rectangles((19, 20), 18, 36, grid=18, rings=2))

        self.assertEqual(candidates[0], Rect(18, 18, 18, 36))
        self.assertTrue(all(rect.x % 18 == 0 and rect.y % 18 == 0 for rect in candidates))
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertEqual(
            candidates,
            list(candidate_rectangles((19, 20), 18, 36, grid=18, rings=2)),
        )
        self.assertEqual(snap_to_grid(26, 18), 18)


if __name__ == "__main__":
    unittest.main()
