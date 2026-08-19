Use $pscad-mcp-improver in review-only mode.

Call review_improvement_backlog with limit=10, min_evidence=3, and mark_notified=true.
Do not modify repository files, create a branch, run tests, or start remediation.

When attention_required=false, finish quietly with no user-facing attention request.
When attention_required=true, report only the returned candidate IDs, categories,
tools, stable codes, evidence counts, and priorities. Ask whether to start one
consolidated remediation batch. Do not include local paths or raw stored data.

If learning_enabled=false, remain quiet. If enabled learning is unavailable,
use this heartbeat's prior run context and report monitoring unavailable only
after two consecutive unavailable runs.

Keep cadence and notification policy in Codex automation, not this prompt.
