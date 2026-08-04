import unittest

from pscad_mcp.core.pscad_adapter import PscadAdapter


class ImmediateExecutor:
    async def run_safe(self, func, *args, **kwargs):
        kwargs.pop("timeout", None)
        return func(*args, **kwargs)


class FakeTrace:
    def __init__(self, values, domain):
        self.data = values
        self.domain = type("Domain", (), {"data": domain})()


class FakeCall:
    def __init__(self, name, call_id, children=None):
        self.name = name
        self.id = call_id
        self.children = children or []

    def __getitem__(self, key):
        if key == "Name":
            return self.name
        raise KeyError(key)

    def calls(self):
        return iter(self.children)


class FakeRun:
    def trace(self, call):
        return FakeTrace([1.0, 2.0, 3.0], [0.0, 0.1, 0.2])


class FakeFile:
    root = FakeCall(
        None,
        0,
        [FakeCall("Root", 0, [FakeCall("Voltage", 10, [FakeCall("PGB:Data", 1)])])],
    )
    num_runs = 1

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, index):
        self.run_index = index
        return FakeRun()


class FakePsout:
    File = FakeFile


class FailingValuesTrace:
    @property
    def data(self):
        raise RuntimeError("values unavailable " + "x" * 1_000)

    @property
    def domain(self):
        return None


class FailingDomainTrace:
    data = [4.0, 5.0]

    @property
    def domain(self):
        raise RuntimeError("domain unavailable")


class SelectiveRun:
    def trace(self, call):
        if call.id == 11:
            raise RuntimeError("trace unavailable")
        if call.id == 12:
            return FailingValuesTrace()
        if call.id == 13:
            return FailingDomainTrace()
        return FakeTrace([1.0, 2.0], [0.0, 0.1])


class FailureFile:
    root = FakeCall(
        None,
        0,
        [
            FakeCall("TraceFail", 11),
            FakeCall("ValuesFail", 12),
            FakeCall("DomainFail", 13),
            FakeCall("Good", 14),
        ],
    )
    num_runs = 1

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, index):
        return SelectiveRun()


class FailingPsout:
    File = FailureFile


class TestPsoutReader(unittest.IsolatedAsyncioTestCase):
    async def test_reads_trace_values_and_domains(self):
        adapter = PscadAdapter(ImmediateExecutor(), psout_module=FakePsout())

        result = await adapter.read_psout("sample.psout", max_samples=10)

        self.assertEqual(result["runs"], 1)
        self.assertEqual(result["channels"][0]["path"], "Root/Voltage/PGB:Data")
        self.assertEqual(result["channels"][0]["values"], [1.0, 2.0, 3.0])
        self.assertEqual(result["channels"][0]["domain"], [0.0, 0.1, 0.2])

    async def test_reports_skipped_channels_without_dropping_successful_channels(self):
        adapter = PscadAdapter(ImmediateExecutor(), psout_module=FailingPsout())

        result = await adapter.read_psout("sample.psout", max_samples=10)

        self.assertEqual(
            [channel["path"] for channel in result["channels"]],
            ["DomainFail", "Good"],
        )
        self.assertEqual(result["channels"][0]["domain"], [])
        self.assertEqual(
            {item["stage"] for item in result["skipped_channels"]},
            {"trace", "values", "domain"},
        )
        self.assertTrue(any("TraceFail" in warning for warning in result["warnings"]))
        self.assertLessEqual(
            max(len(item["reason"]) for item in result["skipped_channels"]),
            256,
        )


if __name__ == "__main__":
    unittest.main()
