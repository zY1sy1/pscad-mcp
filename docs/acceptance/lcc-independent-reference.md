# Preparing an independent LCC reference

WP1C engineering PASS does not supply the independent reference needed by WP6.
The checked-in golden remains a placeholder. Do not replace it with output from
the builder under test or label an independently reloaded copy as an independent
reference implementation.

`scripts/generate_lcc_golden.py` requires `--review-record` as well as literal
`--confirm`. It checks an approved review record, all declared source hashes,
the target blueprint/acceptance contract, compiler and timesteps. The generated
golden embeds the review and its hash. Input changes or a missing review leave
the previous golden untouched.

The review must be performed against an official reference, an independently
assembled project, or independently reviewed external reference output. A human
reviewer or an independently authorized review workflow must establish physical
appropriateness, independence from `lcc.fixed_autonomous`, raw-output provenance,
and correct selector/unit normalization. The generator verifies that those
reviewed files are still the same; it cannot establish independence or a license
from an arbitrary JSON declaration.

Work in a separate reference asset directory containing the target blueprint
and acceptance contract. Keep official/reference inputs immutable. The command
writes `golden.json` alongside the supplied blueprint, so use a staging copy:

```powershell
python scripts/generate_lcc_golden.py `
  --reference-output D:/Reference/normalized.json `
  --blueprint D:/Reference/target-assets/blueprint.json `
  --library D:/Reference/target-assets/library/cigre_lcc_v1.pslx `
  --compiler 'C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe' `
  --review-record D:/Reference/review.json --confirm
```

The record has the following exact fields. Example identities below are
placeholders, not an approval or usable acceptance evidence. Every `path` must
be absolute and every hash must match the corresponding finalized file.

```json
{
  "schema_version": 1,
  "review_status": "approved",
  "review_id": "REPLACE_WITH_ACTUAL_REVIEW_ID",
  "reviewer": "REPLACE_WITH_ACTUAL_REVIEWER",
  "reviewed_at_utc": "2026-09-26T00:00:00Z",
  "scope": "lcc.fixed_autonomous",
  "reference_kind": "independent_manual_assembly",
  "independence_statement": "REPLACE_WITH_REVIEWED_IMPLEMENTATION_AND_PROVENANCE_BASIS",
  "target_blueprint_sha256": "REPLACE_WITH_TARGET_BLUEPRINT_HASH",
  "acceptance_sha256": "REPLACE_WITH_TARGET_ACCEPTANCE_CONTRACT_HASH",
  "normalized_output": {"path": "D:/Reference/normalized.json", "sha256": "REPLACE_WITH_HASH"},
  "source_project": {"path": "D:/Reference/reference.pscx", "sha256": "REPLACE_WITH_HASH"},
  "source_libraries": [{"path": "D:/Reference/reference.pslx", "sha256": "REPLACE_WITH_HASH"}],
  "raw_outputs": [{"path": "D:/Reference/reference_01.out", "sha256": "REPLACE_WITH_HASH"}],
  "output_metadata": [{"path": "D:/Reference/reference.inf", "sha256": "REPLACE_WITH_HASH"}],
  "compiler": {"path": "C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe", "sha256": "REPLACE_WITH_HASH"},
  "emtdc_time_step_s": 0.00005,
  "output_step_s": 0.00005
}
```

Allowed reference kinds are `official_reference`, `independent_manual_assembly`
and `external_reviewed_output`. Include all source libraries, OUT/PSOUT parts and
INF/INFX metadata used to normalize the reference. The actual timesteps must
match the reviewed target blueprint. Keep units and selectors exact; reference
generation does not authorize threshold or waveform adjustments.

Generating this file is reference preparation only. Final WP6 still needs an
independent review, target/reference comparison, dynamic/physical acceptance,
publication reload, source immutability and owned-process cleanup from the
delivered revision. The current WP1C runner deliberately retains its incomplete
golden verdict; this change does not promote it to final accepted.
