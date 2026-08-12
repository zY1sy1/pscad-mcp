import json
import math
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.workflows.sweep.models import SweepSpec


_DEFAULT_SPEC = object()


class TestSweepSpec(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.source = self.workspace / "source"
        self.source.mkdir()
        (self.source / "case.pscx").write_text("case", encoding="utf-8")
        self.path_policy = PathPolicy(str(self.workspace))

    def tearDown(self):
        self.temp_dir.cleanup()

    def valid_spec(self):
        return {
            "source_root": "source",
            "entry_file": "case.pscx",
            "project_name": "Study",
            "scenarios": [
                {
                    "name": "Nominal",
                    "updates": [
                        {
                            "component_id": 7,
                            "parameters": {"R": 1.5, "enabled": True},
                        }
                    ],
                }
            ],
            "outputs": [
                {"path": "results/main.psout", "channels": ["Main/Voltage"]}
            ],
        }

    def parse(self, raw=_DEFAULT_SPEC):
        return SweepSpec.parse(
            self.valid_spec() if raw is _DEFAULT_SPEC else raw,
            self.path_policy,
        )

    def assert_invalid(self, raw, message=None):
        context = self.assertRaises(ValueError)
        with context:
            self.parse(raw)
        if message is not None:
            self.assertIn(message, str(context.exception))

    def test_parses_defaults_into_immutable_json_safe_normalized_records(self):
        spec = self.parse()

        self.assertEqual(spec.source_root, self.source.resolve())
        self.assertEqual(spec.entry_file, "case.pscx")
        self.assertEqual(spec.project_name, "Study")
        self.assertEqual(spec.run_timeout_seconds, 3600)
        self.assertEqual(spec.max_samples, 10_000)
        self.assertEqual(spec.poll_interval_seconds, 1.0)
        self.assertEqual(spec.output_stability_seconds, 0.5)
        self.assertEqual(spec.filesystem_timestamp_tolerance_seconds, 2.0)
        self.assertIsInstance(spec.scenarios, tuple)
        self.assertIsInstance(spec.scenarios[0].updates, tuple)
        self.assertIsInstance(spec.outputs, tuple)
        self.assertEqual(spec.scenarios[0].updates[0].parameters["R"], 1.5)
        with self.assertRaises(TypeError):
            spec.scenarios[0].updates[0].parameters["R"] = 2.0
        with self.assertRaises(FrozenInstanceError):
            spec.project_name = "Changed"

        normalized = spec.to_dict()
        self.assertEqual(normalized["source_root"], str(self.source.resolve()))
        self.assertEqual(normalized["scenarios"][0]["updates"][0]["parameters"], {"R": 1.5, "enabled": True})
        self.assertEqual(normalized["outputs"][0]["channels"], ["Main/Voltage"])
        json.dumps(normalized, allow_nan=False)

    def test_requires_a_mapping_and_all_required_top_level_fields(self):
        for raw in (None, [], "spec"):
            with self.subTest(raw=raw):
                self.assert_invalid(raw)

        for field in ("source_root", "entry_file", "project_name", "scenarios", "outputs"):
            raw = self.valid_spec()
            del raw[field]
            with self.subTest(field=field):
                self.assert_invalid(raw, field)

    def test_rejects_unknown_fields_at_every_level(self):
        cases = []
        top = self.valid_spec()
        top["command"] = "run()"
        cases.append(top)
        scenario = self.valid_spec()
        scenario["scenarios"][0]["expression"] = "x + 1"
        cases.append(scenario)
        update = self.valid_spec()
        update["scenarios"][0]["updates"][0]["callback"] = "f"
        cases.append(update)
        output = self.valid_spec()
        output["outputs"][0]["glob"] = "*.psout"
        cases.append(output)

        for raw in cases:
            with self.subTest(raw=raw):
                self.assert_invalid(raw, "unknown")

    def test_source_root_must_be_an_existing_directory_inside_workspace(self):
        missing = self.valid_spec()
        missing["source_root"] = "missing"
        self.assert_invalid(missing)

        file_source = self.valid_spec()
        file_source["source_root"] = "source/case.pscx"
        file_source["entry_file"] = "case.pscx"
        self.assert_invalid(file_source, "directory")

        outside_dir = self.workspace.parent / f"{self.workspace.name}-outside"
        outside_dir.mkdir(exist_ok=True)
        try:
            outside = self.valid_spec()
            outside["source_root"] = str(outside_dir)
            self.assert_invalid(outside, "outside")
        finally:
            outside_dir.rmdir()

        with self.assertRaises(ValueError):
            SweepSpec.parse(self.valid_spec(), PathPolicy(allow_unscoped_paths=True))

    def test_rejects_sources_in_managed_sweep_storage(self):
        managed = self.workspace / ".pscad-mcp" / "sweeps" / "campaign" / "baseline"
        managed.mkdir(parents=True)
        (managed / "case.pscx").write_text("case", encoding="utf-8")
        raw = self.valid_spec()
        raw["source_root"] = str(managed)

        self.assert_invalid(raw, ".pscad-mcp")

    def test_entry_file_is_relative_contained_existing_and_supported(self):
        (self.source / "nested").mkdir()
        (self.source / "nested" / "workspace.pswx").write_text("workspace", encoding="utf-8")
        raw = self.valid_spec()
        raw["entry_file"] = "nested\\workspace.pswx"
        self.assertEqual(self.parse(raw).entry_file, "nested/workspace.pswx")

        for entry in (
            str((self.source / "case.pscx").resolve()),
            "../case.pscx",
            "missing.pscx",
            "case.txt",
            "",
        ):
            raw = self.valid_spec()
            raw["entry_file"] = entry
            with self.subTest(entry=entry):
                self.assert_invalid(raw)

    def test_project_name_and_scenario_list_are_nonempty(self):
        for project_name in ("", "   ", None):
            raw = self.valid_spec()
            raw["project_name"] = project_name
            with self.subTest(project_name=project_name):
                self.assert_invalid(raw, "project_name")

        for scenarios in ([], (), None, "Nominal"):
            raw = self.valid_spec()
            raw["scenarios"] = scenarios
            with self.subTest(scenarios=scenarios):
                self.assert_invalid(raw, "scenarios")

    def test_scenario_names_are_nonempty_and_unique_case_insensitively(self):
        for name in ("", "   ", None):
            raw = self.valid_spec()
            raw["scenarios"][0]["name"] = name
            with self.subTest(name=name):
                self.assert_invalid(raw, "name")

        raw = self.valid_spec()
        raw["scenarios"].append(
            {"name": "nOMINAL", "updates": [{"component_id": 8, "parameters": {"R": 2}}]}
        )
        self.assert_invalid(raw, "unique")

    def test_updates_require_positive_component_ids_and_nonempty_parameter_mappings(self):
        for updates in ([], (), None, "update"):
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"] = updates
            with self.subTest(updates=updates):
                self.assert_invalid(raw, "updates")

        for component_id in (True, False, 0, -1, 1.5, "7", None):
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"][0]["component_id"] = component_id
            with self.subTest(component_id=component_id):
                self.assert_invalid(raw, "component_id")

        for parameters in ({}, None, [], "R=1"):
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"][0]["parameters"] = parameters
            with self.subTest(parameters=parameters):
                self.assert_invalid(raw, "parameters")

        for parameter_name in ("", "   ", 1, None):
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"][0]["parameters"] = {parameter_name: 1}
            with self.subTest(parameter_name=parameter_name):
                self.assert_invalid(raw, "parameter")

    def test_parameter_values_accept_only_json_scalars_and_preserve_strings_as_data(self):
        values = [None, True, False, 42, -3, 1.25, "${HOME}", "x + 1", "run()"]
        for value in values:
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"][0]["parameters"] = {"value": value}
            with self.subTest(value=value):
                spec = self.parse(raw)
                self.assertEqual(spec.to_dict()["scenarios"][0]["updates"][0]["parameters"]["value"], value)

        invalid_values = [math.nan, math.inf, -math.inf, [], {}, (1,), object()]
        for value in invalid_values:
            raw = self.valid_spec()
            raw["scenarios"][0]["updates"][0]["parameters"] = {"value": value}
            with self.subTest(value=value):
                self.assert_invalid(raw, "JSON scalar")

    def test_rejects_duplicate_component_parameter_targets_across_updates(self):
        raw = self.valid_spec()
        raw["scenarios"][0]["updates"] = [
            {"component_id": 7, "parameters": {"R": 1, "L": 2}},
            {"component_id": 7, "parameters": {"R": 3}},
        ]

        self.assert_invalid(raw, "duplicate")

    def test_baseline_must_exactly_match_a_scenario_name(self):
        raw = self.valid_spec()
        raw["baseline_scenario"] = "Nominal"
        self.assertEqual(self.parse(raw).baseline_scenario, "Nominal")

        for baseline in ("nominal", "Missing", "", 7):
            raw = self.valid_spec()
            raw["baseline_scenario"] = baseline
            with self.subTest(baseline=baseline):
                self.assert_invalid(raw, "baseline_scenario")

    def test_outputs_require_relative_supported_paths_and_exact_nonempty_channels(self):
        for outputs in ([], (), None, "results/main.psout"):
            raw = self.valid_spec()
            raw["outputs"] = outputs
            with self.subTest(outputs=outputs):
                self.assert_invalid(raw, "outputs")

        raw = self.valid_spec()
        raw["outputs"] = [{"path": "results\\main.OUT", "channels": ["A/B", "C D"]}]
        output = self.parse(raw).outputs[0]
        self.assertEqual(output.path, "results/main.OUT")
        self.assertEqual(output.channels, ("A/B", "C D"))

        absolute_output = str((self.source / "main.psout").resolve())
        for path in (absolute_output, "../main.psout", "main.csv", ""):
            raw = self.valid_spec()
            raw["outputs"][0]["path"] = path
            with self.subTest(path=path):
                self.assert_invalid(raw)

        for channels in ([], (), None, "A/B", [""], ["   "], [1], ["A/*"], ["A?"], ["A[0]"]):
            raw = self.valid_spec()
            raw["outputs"][0]["channels"] = channels
            with self.subTest(channels=channels):
                self.assert_invalid(raw, "channels")

    def test_numeric_options_enforce_types_and_inclusive_bounds(self):
        valid_values = {
            "run_timeout_seconds": (60, 604_800),
            "max_samples": (1, 1_000_000),
            "poll_interval_seconds": (0.1, 60),
            "output_stability_seconds": (0.1, 60),
            "filesystem_timestamp_tolerance_seconds": (0, 60),
        }
        for field, bounds in valid_values.items():
            for value in bounds:
                raw = self.valid_spec()
                raw[field] = value
                with self.subTest(field=field, value=value):
                    self.assertEqual(getattr(self.parse(raw), field), value)

        invalid_values = {
            "run_timeout_seconds": (True, 59, 604_801, math.inf),
            "max_samples": (True, 0, 1_000_001, 1.5),
            "poll_interval_seconds": (True, 0.09, 61, math.nan),
            "output_stability_seconds": (True, 0.09, 61, math.inf),
            "filesystem_timestamp_tolerance_seconds": (True, -0.1, 61, math.nan),
        }
        for field, values in invalid_values.items():
            for value in values:
                raw = self.valid_spec()
                raw[field] = value
                with self.subTest(field=field, value=value):
                    self.assert_invalid(raw, field)

    def test_directory_keys_are_safe_deterministic_and_case_sensitive_to_name_bytes(self):
        raw = self.valid_spec()
        raw["scenarios"] = [
            {"name": "CON", "updates": [{"component_id": 1, "parameters": {"R": 1}}]},
            {"name": "a/b: c", "updates": [{"component_id": 2, "parameters": {"R": 2}}]},
            {"name": "scenario-电压", "updates": [{"component_id": 3, "parameters": {"R": 3}}]},
        ]
        first = self.parse(raw)
        second = self.parse(raw)
        keys = [scenario.directory_key for scenario in first.scenarios]

        self.assertEqual(keys, [scenario.directory_key for scenario in second.scenarios])
        self.assertEqual(len(keys), len({key.casefold() for key in keys}))
        for key in keys:
            self.assertRegex(key, r"^scenario-[0-9a-f]{24}$")
            self.assertNotIn(key.upper(), {"CON", "PRN", "AUX", "NUL"})

        nominal = self.parse().scenarios[0].directory_key
        case_variant = self.valid_spec()
        case_variant["scenarios"][0]["name"] = "nominal"
        self.assertNotEqual(nominal, self.parse(case_variant).scenarios[0].directory_key)


if __name__ == "__main__":
    unittest.main()
