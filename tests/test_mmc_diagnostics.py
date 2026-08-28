import pytest

from pscad_mcp.hvdc.builders.mmc.diagnostics import classify_mmc_failure
from tests.mmc_parametric_fakes import error_with_code


@pytest.mark.parametrize(
    ("code", "category", "retryable"),
    [
        ("MMC_ABSOLUTE_PATH_UNRESOLVED", "binding_repair", False),
        ("MMC_NUMERICAL_UNSTABLE", "numerical_stability", True),
        ("MMC_CONTROL_UNSTABLE", "control_stability", True),
        ("MMC_ACCEPTANCE_FAILED", "acceptance", False),
        ("LICENSE_UNAVAILABLE", "environment", False),
        ("EXECUTOR_UNHEALTHY", "environment", False),
    ],
)
def test_failure_classification_is_explicit(
    code: str, category: str, retryable: bool
) -> None:
    result = classify_mmc_failure(error_with_code(code))
    assert result.category == category
    assert result.retryable is retryable
    assert len(result.signature) == 64


def test_failure_signature_ignores_volatile_candidate_history() -> None:
    first = error_with_code("MMC_NUMERICAL_UNSTABLE")
    second = error_with_code("MMC_NUMERICAL_UNSTABLE")
    first.details.update({"candidate_id": "pwm-0", "timestamp": "one"})
    second.details.update({"candidate_id": "pwm-1", "timestamp": "two"})

    assert classify_mmc_failure(first).signature == classify_mmc_failure(second).signature
