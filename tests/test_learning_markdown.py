from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.learning import markdown as markdown_module
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


def test_renderer_escapes_dynamic_crlf_and_keeps_file_lf_only(tmp_path):
    backlog = tmp_path / "improvement-backlog.md"
    candidate = replace(
        _candidate(),
        candidate_id="PSCAD-IMP-\r\nABC123",
        primary_tool="run\r\nproject",
        code="TIME\nOUT\r",
        first_seen="first\r\nseen",
        last_seen="last\nseen\r",
    )

    render_backlog(
        backlog,
        [candidate],
        generated_at="generated\r\nat",
    )

    raw = backlog.read_bytes()
    text = raw.decode("utf-8")
    assert b"\r" not in raw
    assert "Generated at: generated\\r\\nat" in text
    assert "### PSCAD-IMP-\\r\\nABC123" in text
    assert "- Primary tool: run\\r\\nproject" in text
    assert "- Code: TIME\\nOUT\\r" in text
    assert "- First seen: first\\r\\nseen" in text
    assert "- Last seen: last\\nseen\\r" in text


def test_renderer_preserves_replace_error_when_cleanup_also_fails(
    tmp_path,
    monkeypatch,
):
    backlog = tmp_path / "improvement-backlog.md"
    backlog.write_text("SECRET_OLD_CONTENT", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_replace(source, destination):
        raise OSError("replace failed")

    def fail_temp_unlink(path, missing_ok=False):
        if path.name.startswith("improvement-backlog.md."):
            raise OSError("cleanup failed")
        return original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(markdown_module.os, "replace", fail_replace)
    monkeypatch.setattr(markdown_module.Path, "unlink", fail_temp_unlink)

    try:
        with pytest.raises(OSError, match="replace failed"):
            render_backlog(
                backlog,
                [_candidate()],
                generated_at="2026-08-19T02:00:00+00:00",
            )
    finally:
        monkeypatch.undo()
        for temporary_path in tmp_path.glob("improvement-backlog.md.*.tmp"):
            temporary_path.unlink()

    assert backlog.read_text(encoding="utf-8") == "SECRET_OLD_CONTENT"


def test_renderer_reports_cleanup_error_without_active_exception(
    tmp_path,
    monkeypatch,
):
    backlog = tmp_path / "improvement-backlog.md"
    original_unlink = Path.unlink

    def no_op_replace(source, destination):
        return None

    def fail_temp_unlink(path, missing_ok=False):
        if path.name.startswith("improvement-backlog.md."):
            raise OSError("cleanup failed")
        return original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(markdown_module.os, "replace", no_op_replace)
    monkeypatch.setattr(markdown_module.Path, "unlink", fail_temp_unlink)

    try:
        with pytest.raises(OSError, match="cleanup failed"):
            render_backlog(
                backlog,
                [_candidate()],
                generated_at="2026-08-19T02:00:00+00:00",
            )
    finally:
        monkeypatch.undo()
        for temporary_path in tmp_path.glob("improvement-backlog.md.*.tmp"):
            temporary_path.unlink()


def test_renderer_ignores_missing_temp_during_cleanup(tmp_path, monkeypatch):
    backlog = tmp_path / "improvement-backlog.md"
    original_unlink = Path.unlink

    def missing_temp_unlink(path, missing_ok=False):
        if path.name.startswith("improvement-backlog.md."):
            raise FileNotFoundError(path)
        return original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(markdown_module.Path, "unlink", missing_temp_unlink)

    render_backlog(
        backlog,
        [_candidate()],
        generated_at="2026-08-19T02:00:00+00:00",
    )

    assert backlog.exists()
    assert list(tmp_path.glob("improvement-backlog.md.*.tmp")) == []
