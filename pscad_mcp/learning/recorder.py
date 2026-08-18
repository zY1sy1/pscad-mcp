from .models import InvocationOutcome
from .service import LearningRuntime, learning_runtime


class InvocationRecorder:
    def __init__(self, runtime: LearningRuntime) -> None:
        self._runtime = runtime

    def register_tool_name(self, name: str) -> None:
        self._runtime.register_tool_name(name)

    def record(
        self,
        *,
        tool_name: str,
        duration_ms: int,
        outcome: InvocationOutcome,
        error_code: str | None,
        retryable: bool | None,
        backend: str | None,
        pscad_version: str | None,
    ) -> None:
        self._runtime.record_invocation(
            tool_name=tool_name,
            duration_ms=duration_ms,
            outcome=outcome,
            error_code=error_code,
            retryable=retryable,
            backend=backend,
            pscad_version=pscad_version,
        )


learning_recorder = InvocationRecorder(learning_runtime)
