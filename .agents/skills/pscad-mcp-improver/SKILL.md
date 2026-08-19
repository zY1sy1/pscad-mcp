---
name: pscad-mcp-improver
description: Review PSCAD MCP improvement evidence and, only after explicit user approval, reproduce and remediate approved candidates with regression tests. Use for scheduled backlog review or user-requested MCP improvement.
---

# PSCAD MCP Improver

Review-only mode is the default. It has no auto-remediation. Remediation is a
separate mode that cannot begin from a backlog result alone.

## Review-only mode

Call exactly:

```text
review_improvement_backlog(limit=10, min_evidence=3, mark_notified=true)
```

This mode changes no repository file, creates no branch or worktree, runs no
tests, and starts no remediation. When `attention_required=false`, finish
quietly. When attention is required, report only each returned candidate's ID,
category, tools, stable code, evidence count, and priority. Do not expose local
paths or raw stored data, and do not make a patch from the review result.

## Approved remediation mode

Enter this mode only after explicit user approval identifies an approved
candidate list. Do not infer approval from a request to review, a high
priority, or a backlog candidate.

1. Work in an isolated `codex/` branch or worktree. Read applicable
   `AGENTS.md` instructions before changing files.
2. Reproduce one approved candidate and write a failing regression test before
   changing source. Run the test and observe the failure for the reproduced
   root cause.
3. Make the smallest source change that fixes that root cause, verify the
   regression and relevant checks, and commit one root cause at a time.
4. Summarize the candidate, evidence, regression test, source change, and
   verification. Keep an unreproduced candidate unchanged in the generated
   backlog and list the fixed action `needs_evidence` in the remediation
   summary. Do not create a speculative patch.

The skill may propose or edit `AGENTS.md` or its own instructions only during
an approved remediation when a repeated workflow mistake has been reproduced;
a backlog candidate alone is not sufficient evidence. It must never weaken
safety or run licensed acceptance without the existing opt-in.

## Rationalization Guards

| Rationalization | Counter |
| --- | --- |
| review result alone is approval | Counter: review result is evidence, not approval; remain in review-only mode and wait for explicit user approval and an approved candidate list. |
| time pressure means patch now | Counter: time pressure does not change the approval gate; stay in review-only mode until approval. |
| tests pass means accepted | Counter: passing tests do not replace explicit user approval; tests only verify an approved change. |
| candidate alone justifies AGENTS.md change | Counter: a backlog candidate alone is insufficient; require an approved remediation after a repeated workflow mistake has been reproduced. |

## Red Flags

Any violation of a guard means immediately return to review-only mode, make no
remediation change, and wait for explicit user approval. Stop on any of these:

- Treating a review result, priority, or evidence count as approval.
- Using time pressure to skip the approved candidate list or the failing
  regression test.
- Treating passing tests as acceptance of an unapproved change.
- Editing `AGENTS.md` because a candidate exists without reproducing a
  repeated workflow mistake during approved remediation.
- Patching an unreproduced candidate instead of recording `needs_evidence`.

## Verification record

Future operator checklist only. Record outcomes here only after actually
running the checks; do not infer or invent results.

- [ ] Scheduled empty run: confirm `attention_required=false` finishes quietly
  without repository changes or remediation.
- [ ] Critical finding under time pressure: confirm the skill remains
  review-only until explicit approval and an approved candidate list exist.
- [ ] Unreproduced candidate: confirm it stays unchanged and the remediation
  summary uses the fixed action `needs_evidence`.

Never merge, push, publish, or deploy.
Never edit improvement-backlog.md; it is a generated projection.
