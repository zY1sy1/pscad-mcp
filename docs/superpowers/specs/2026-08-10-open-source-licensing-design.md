# Open-source licensing design

## Goal

Make the public fork's licensing and attribution clearer without claiming
ownership of upstream or third-party material.

## Scope

- Add a root `LICENSE` containing the standard MIT license text.
- Use `Copyright (c) 2026 pscad-mcp contributors` as the collective copyright
  designation rather than assigning all upstream work to the fork owner.
- Add a root `NOTICE` that identifies the upstream repository, describes this
  repository as a modified fork, and states that the project is not affiliated
  with or endorsed by Manitoba Hydro International Ltd. (MHI).
- State in `NOTICE` that generated PSCAD API snapshots under `docs/raw` and
  `docs/md` are third-party material and are not covered by the repository's
  MIT license.
- Update the README license section to link to `LICENSE` and `NOTICE`.

## Boundaries

- Do not claim that the MIT license grants rights to PSCAD, its documentation,
  trademarks, software, or other MHI material.
- Do not replace or remove the existing upstream author metadata.
- Do not remove generated PSCAD documentation or rewrite Git history in this
  change. Removing third-party snapshots can be handled as a separate cleanup.
- Do not state that the new files resolve any uncertainty in the upstream chain
  of title; upstream confirmation remains preferable before commercial use.

## Verification

- Confirm `LICENSE` matches the standard MIT text.
- Confirm `NOTICE` names the upstream repository and separates MIT-covered code
  from third-party material.
- Confirm the README links resolve to the two root files.
- Run `git diff --check` and inspect the final diff before completion.

