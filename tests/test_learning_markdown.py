import pytest

from pscad_mcp.learning.markdown import render_backlog
from pscad_mcp.learning.models import (
    CandidateKind,
    CandidateState,
    ImprovementCandidate,
)


def _candidate(state=CandidateState.OPEN):
    return ImprovementCandidate(
        candidate_id="PSCAD-IMP-ABC123",
        fingerprint="abc123",
        kind=CandidateKind.RELIABILITY,
        state=state,
        primary_tool="run_project",
        code="TIMEOUT",
        priority=4,
        invocation_count=4,
        goal_failure_count=0,
        first_seen="2026-08-18T01:00:00+00:00",
        last_seen="2026-08-19T01:00:00+00:00",
        retryable=True,
        evidence_watermark="watermark",
        immediate_attention=False,
    )


def test_renderer_writes_only_bounded_candidate_fields(tmp_path):
    backlog = tmp_path / "improvement-backlog.md"
    render_backlog(
        backlog,
        [_candidate()],
        generated_at="2026-08-19T02:00:00+00:00",
    )
    text = backlog.read_text(encoding="utf-8")
    assert "# PSCAD MCP Improvement Backlog" in text
    assert "## Open" in text
    assert "PSCAD-IMP-ABC123" in text
    assert "run_project" in text
    assert "TIMEOUT" in text
    assert "watermark" not in text
    assert "abc123" not in text


def test_empty_render_replaces_old_content_with_header_only(tmp_path):
    backlog = tmp_path / "improvement-backlog.md"
    backlog.write_text("SECRET_OLD_CONTENT", encoding="utf-8")
    render_backlog(
        backlog,
        [],
        generated_at="2026-08-19T02:00:00+00:00",
    )
    text = backlog.read_text(encoding="utf-8")
    assert "SECRET_OLD_CONTENT" not in text
    assert "No retained improvement candidates." in text
    assert list(tmp_path.glob("improvement-backlog.md.*.tmp")) == []


def test_renderer_creates_parent_and_orders_sections_and_public_fields(tmp_path):
    backlog = tmp_path / "nested" / "improvement-backlog.md"
    candidates = [
        _candidate(state)
        for state in (
            CandidateState.RESOLVED_BY_LATER_EVIDENCE,
            CandidateState.NOTIFIED,
            CandidateState.REOPENED,
            CandidateState.OPEN,
        )
    ]

    render_backlog(
        backlog,
        candidates,
        generated_at="2026-08-19T02:00:00+00:00",
    )

    text = backlog.read_text(encoding="utf-8")
    sections = (
        "## Open",
        "## Reopened",
        "## Notified",
        "## Resolved by later evidence",
    )
    positions = [text.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "Generated at: 2026-08-19T02:00:00+00:00" in text

    candidate_start = text.index("### PSCAD-IMP-ABC123")
    field_lines = (
        "- Candidate ID: PSCAD-IMP-ABC123",
        "- Kind: reliability",
        "- State: open",
        "- Primary tool: run_project",
        "- Code: TIMEOUT",
        "- Priority: 4",
        "- Invocation count: 4",
        "- Goal failure count: 0",
        "- First seen: 2026-08-18T01:00:00+00:00",
        "- Last seen: 2026-08-19T01:00:00+00:00",
        "- Retryable: True",
        "- Immediate attention: False",
        "- Next action: Reproduce the failure and inspect recovery.",
    )
    field_positions = [text.index(line, candidate_start) for line in field_lines]
    assert field_positions == sorted(field_positions)


def test_renderer_keeps_existing_file_when_atomic_replace_fails(tmp_path, monkeypatch):
    backlog = tmp_path / "improvement-backlog.md"
    backlog.write_text("SECRET_OLD_CONTENT", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr("pscad_mcp.learning.markdown.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        render_backlog(
            backlog,
            [_candidate()],
            generated_at="2026-08-19T02:00:00+00:00",
        )

    assert backlog.read_text(encoding="utf-8") == "SECRET_OLD_CONTENT"
    assert list(tmp_path.glob("improvement-backlog.md.*.tmp")) == []
