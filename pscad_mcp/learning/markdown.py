from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

from .models import CandidateKind, CandidateState, ImprovementCandidate


_SECTIONS = (
    (CandidateState.OPEN, "Open"),
    (CandidateState.REOPENED, "Reopened"),
    (CandidateState.NOTIFIED, "Notified"),
    (
        CandidateState.RESOLVED_BY_LATER_EVIDENCE,
        "Resolved by later evidence",
    ),
)
_NEXT_ACTION = {
    CandidateKind.RELIABILITY: "Reproduce the failure and inspect recovery.",
    CandidateKind.CORRECTNESS: "Reproduce against an explicit expected result.",
    CandidateKind.CAPABILITY: "Confirm and specify the missing capability.",
    CandidateKind.GUIDANCE: "Inspect tool schema and recovery guidance.",
    CandidateKind.EFFICIENCY: "Reduce retries while preserving recovery.",
}
_PUBLIC_FIELDS = (
    ("candidate_id", "Candidate ID"),
    ("kind", "Kind"),
    ("state", "State"),
    ("primary_tool", "Primary tool"),
    ("code", "Code"),
    ("priority", "Priority"),
    ("invocation_count", "Invocation count"),
    ("goal_failure_count", "Goal failure count"),
    ("first_seen", "First seen"),
    ("last_seen", "Last seen"),
    ("retryable", "Retryable"),
    ("immediate_attention", "Immediate attention"),
)


def _escape_scalar(value: object) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def _render_candidate(candidate: ImprovementCandidate) -> list[str]:
    public = candidate.public_dict()
    lines = [f"### {_escape_scalar(public['candidate_id'])}", ""]
    lines.extend(
        f"- {label}: {_escape_scalar(public[field])}"
        for field, label in _PUBLIC_FIELDS
    )
    lines.append(f"- Next action: {_NEXT_ACTION[candidate.kind]}")
    return lines


def _render_text(
    candidates: Iterable[ImprovementCandidate],
    *,
    generated_at: str,
) -> str:
    grouped = {state: [] for state, _ in _SECTIONS}
    for candidate in candidates:
        grouped[candidate.state].append(candidate)

    lines = [
        "# PSCAD MCP Improvement Backlog",
        "",
        f"Generated at: {_escape_scalar(generated_at)}",
        "",
    ]
    if not any(grouped.values()):
        lines.append("No retained improvement candidates.")
    else:
        for state, title in _SECTIONS:
            state_candidates = grouped[state]
            if not state_candidates:
                continue
            lines.extend((f"## {title}", ""))
            for candidate in state_candidates:
                lines.extend(_render_candidate(candidate))
                lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def render_backlog(
    path: str | os.PathLike[str],
    candidates: Iterable[ImprovementCandidate],
    *,
    generated_at: str,
) -> None:
    """Render the retained improvement candidates with an atomic replacement."""
    backlog_path = Path(path)
    text = _render_text(candidates, generated_at=generated_at)
    backlog_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    active_exception: BaseException | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=backlog_path.name + ".",
            suffix=".tmp",
            dir=backlog_path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, backlog_path)
    except BaseException as error:
        active_exception = error
        raise
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                if active_exception is None:
                    raise
