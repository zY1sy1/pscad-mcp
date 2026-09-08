# PSCAD Acceptance Work

Read `docs/acceptance-criteria.md` before planning or running acceptance, or
interpreting a failed acceptance report. It applies to model work and MCP work.

- An unsuccessful acceptance attempt is evidence for the next diagnosis, not
  completion of the user's task. Within the authorized scope, fix reproducible
  implementation/model defects and rerun affected acceptance to closure.
- Separate environment contention, implementation defects, model/physical
  failures, and unsupported external capabilities. Do not label all four as
  "acceptance failed" and stop without investigating.
- For independent tasks, use separate PSCAD instances and workspaces. Runners
  supporting it use process-local `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1`; never
  terminate another task's processes or infer ownership from a global PID delta.
- Preserve license opt-ins, source immutability, physical criteria and evidence
  integrity. Never lower thresholds, skip failed checks, or reuse stale reports
  to obtain PASS.
- Report a genuine external blocker with evidence, work already attempted,
  independent work completed, and the exact missing prerequisite. Do not claim
  completion while required acceptance is still pending or blocked.
