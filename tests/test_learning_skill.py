from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / ".agents" / "skills" / "pscad-mcp-improver" / "SKILL.md"
PROMPT = SKILL.parent / "references" / "scheduled-review.md"


def test_improver_skill_is_review_only_until_user_approval():
    text = SKILL.read_text(encoding="utf-8")
    assert "name: pscad-mcp-improver" in text
    assert "review_improvement_backlog" in text
    assert "explicit user approval" in text
    assert "failing regression test" in text
    assert "isolated" in text and "worktree" in text
    assert "Never merge, push, publish, or deploy" in text
    assert "Never edit improvement-backlog.md" in text
    assert "needs_evidence" in text
    assert "AGENTS.md" in text
    assert "repeated workflow mistake" in text
    assert "## Rationalization Guards" in text
    assert "| review result alone is approval |" in text
    assert "| time pressure means patch now |" in text
    assert "| tests pass means accepted |" in text
    assert "| candidate alone justifies AGENTS.md change |" in text
    assert "review result is evidence, not approval" in text
    assert "time pressure does not change the approval gate" in text
    assert "passing tests do not replace explicit user approval" in text
    assert "repeated workflow mistake has been reproduced" in text
    assert "## Red Flags" in text
    assert "return to review-only mode" in text
    assert "wait for explicit user approval" in text


def test_scheduled_prompt_is_quiet_without_findings():
    text = PROMPT.read_text(encoding="utf-8")
    assert "$pscad-mcp-improver" in text
    assert "review-only mode" in text
    assert "mark_notified=true" in text
    assert "attention_required=false" in text
    assert "Do not modify repository files" in text
    assert "Monday" not in text
