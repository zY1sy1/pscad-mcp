# Parametric LCC nameplate convention

The user selected normal engineering convention on 2026-09-26.

| Input | Meaning |
| --- | --- |
| `rated_power_mw` | Total system active DC power at the declared nameplate operating point |
| `dc_voltage_kv` | Positive magnitude of each pole's voltage relative to ground |
| `dc_current_ka` | Positive current magnitude in each pole |

The balanced bipolar contract is `P_total = 2 U_pole I_pole`. The monopolar
contract is `P_total = U_pole I_pole`. kV multiplied by kA yields MW.
Thus a +/-500 kV, 1000 MW bipole has 1 kA per pole and 500 MW per pole;
a 500 kV, 1000 MW monopole has 2 kA. A bipole's pole-to-pole voltage is 1000 kV
in the first example; it must not be passed as `dc_voltage_kv=1000`.

Nameplate ratings describe the installed topology. A single-pole operating
mode of a bipole retains that nameplate; with unchanged pole voltage/current,
its available power is half of the bipolar rating. These input identities do
not remove line/converter losses or equate sending and receiving terminal power.

The API continues to require all six base ratings. Inconsistent supplied
current is rejected with `LCC_RATING_INCONSISTENT`, the topology, pole count,
calculated total MW, and required per-pole kA. It is never silently rescaled.
Existing bipolar requests such as 1200 MW / 500 kV / 2.4 kA must be corrected
to 1.2 kA if 1200 MW is the intended total, or to 2400 MW if 2.4 kA is intended.

The catalog and hash-bound provenance declare the same formula, pole counts
and rating bases. Plans include the basis in the derived power evidence and
are invalidated when their packaged assets change. Re-plan old requests.

Regression coverage includes three bipolar ratings, an unchanged monopolar
case, rejection of the old per-pole interpretation, and rejection of catalog
changes to the pole count or power basis. Formula validation is offline evidence;
it does not establish physical acceptance of a generated PSCAD project.

The rated public LCC builder still needs audited physical parameter mappings
and its own licensed matrix. Transformer AC secondary voltage is not DC pole
voltage. The two former direct `dc_voltage_kv -> V2` bindings have been removed
from the reviewed catalog after a regression reproduced an executable direct
500 kV DC-to-500 kV AC write. An ideal series pair of six-pulse bridges has
`U_d0 = 2 * (3 sqrt(2) / pi) * U_LL`, before firing angle and commutation-drop
effects. Source immutability, physical thresholds and independent-reference
requirements remain applicable. Previous raw reports retain their original
request and revision; this correction does not relabel them as accepted.

## Verification on 2026-09-26

The formula correction is commit `79f9a49`; removal of the direct DC-to-AC
binding is `fb0b244f390d38f6d9a6378f44e91159219de3d4`. The original formula was
reproduced with four failing regressions before changing source. The separate
binding regression reproduced a falsely executable monopolar voltage write.
The final affected offline suite (`pytest tests -q -k lcc --tb=short`) passed
1069 tests with 12 licensed tests skipped and 2822 unrelated tests deselected;
the log is `D:/PA/l26-rating-regression.log`. These skips are not physical
acceptance. The changed-file lint comparison introduced no new findings
(18 pre-existing findings), and `git diff --check` passed.

Three fresh public plans use 1000 MW / 500 kV / 1 kA,
1200 MW / 500 kV / 1.2 kA, and 1600 MW / 400 kV / 2 kA. Their derivations
succeed and record the explicit total-power convention; all remain
`executable=false` because 13 physical mappings are unresolved. No staging
workspace was created. This is an implementation gap, not a pending user
decision or license failure. Hash-bound plans and the preflight record:
`D:/PA/l26-rating-preflight-fb0b244/report.json`.

Three separate owned PSCAD 4.6.2 instances then ran the immutable bipolar
template at its existing 50 Hz frequency, changing only the power-order slider
in a staged copy. These diagnostics use the existing controller's 1000 MW base;
other requested engineering/rating values are explicitly **not applied**.

| Total command (MW) | Positive pole (MW) | Negative pole (MW) | Measured total (MW) |
| --- | --- | --- | --- |
| 800 | 399.962150 | 399.957128 | 799.919278 |
| 900 | 449.934410 | 449.929037 | 899.863447 |
| 1000 | 499.956556 | 499.951010 | 999.907566 |

The reported total is the mean of instantaneous `Vp*Ip - Vn*In` during
4.0-5.0 s, accounting for the negative pole meter orientation. Output PGB
scales (0.002 for voltage and 0.5 for current) are removed to recover kV and
kA; their exact source component IDs are recorded. No absolute-value power
rectification is used. All three cases satisfy the criteria fixed before the
runs: correct voltage/current polarity, total-power tracking within 2%, and
pole mean-current mismatch below 1%. The worst tracking error is 0.015173%.

The reports, in table order, are:

- `D:/PA/l26power/180222-800/report.json`, SHA-256
  `697601717108eeffa7e44cc2829bb1910bf812819ea6240b47802055850ee1f9`
- `D:/PA/l26power/180222-900/report.json`, SHA-256
  `f5eaaa1c31bc6682113632c626b4bcde80b3517334359fb362555f835c96fef3`
- `D:/PA/l26power/180222-1000/report.json`, SHA-256
  `dd406d826d8addd84fa35893476eee0431197acc1a4cda6f088df2d57fbed1a4`

All reports bind the clean `fb0b244` revision, diagnostic script hash, exact
request, source/Master hashes, managed PID, output parts and metadata.
All 27 declared artifacts passed a fresh hash check in
`D:/PA/l26-power-integrity.json`. Source inputs and implementation remained
unchanged; all three owned processes exited without cleanup errors.
The reproducible diagnostic runner is `D:/PA/l26_power_basis_probe.py`.

These results validate the total-power interpretation of the existing template
at three operating points. They do **not** accept the public rated builder,
voltage/frequency/SCR scaling, transformer/filter/reactor design, fault or
return-mode behavior, or an independent golden. Every diagnostic report keeps
`model_accepted=false` and `public_builder_accepted=false`. The outstanding
external prerequisites remain an independently reviewed LCC reference and a
usable licensed PSCAD 5.x installation; those do not replace the remaining
parameterization implementation work.
