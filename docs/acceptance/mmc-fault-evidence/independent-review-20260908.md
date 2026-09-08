# Independent MMC Diagnostic Review

This record concerns the fixed diagnostic revisions `f108bac` and
`c5ed2e2329beac247d700e2851a6302b20e2154c`. It does not establish physical
acceptance. The final steady attempt remains `FAIL`; fault and recovery
acceptance are pending.

## Frozen Evidence

Evidence root:
`D:/PSCAD-Workspace/mmc-fault-evidence/fault-evidence-20260908T085929376555Z`.

The root reviewer independently verified the saved channel contract, sample
JSON and output index against the case report hashes, then verified all 38
OUT/INF/INFX files with `verify_output_dataset`. All identities matched.
The three installed source hashes also matched their pre-run records:

| Source | SHA-256 |
| --- | --- |
| Project | `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd` |
| Library | `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b` |
| Master | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |

The final report identifies commit `c5ed2e2`, scope
`steady_only_diagnostic`, and `owned_process_cleaned: true`. This was a
static review of finalized files; the reviewer started no PSCAD instance.

## Independent Energy Calculation

For each of six arms per terminal, use the actual capacitor sum and energy
channels on the same 1600 samples in `[4.6, 5.0)` seconds. The cell count is
76 and capacitance is 2800 uF. With voltage in kV and energy in MJ:

```text
mean_cell_voltage = sum(Vc) / 76
within_arm_variance = energy / (0.5 * 2800e-6 * 76) - mean_cell_voltage**2
nominal_terminal_energy = 6 * 0.5 * 2800e-6 * 76 * (640 / 76)**2
```

| Quantity | T1 | T2 |
| --- | ---: | ---: |
| Mean total capacitor energy, MJ | 51.934476 | 31.791467 |
| Nominal total capacitor energy, MJ | 45.271579 | 45.271579 |
| Mean cell voltage, kV | 7.630502 | 7.054767 |
| Mean within-arm variance, kV squared | 23.022577 | 0.000707 |
| Mean within-arm standard deviation, kV | 4.792498 | 0.015548 |

The last row averages each sample's reconstructed standard deviation across
all six arms. It is not the square root of the preceding averaged variance.
Only roundoff below zero is clipped when computing this diagnostic square
root; no acceptance waveform or criterion is changed.

T1 has excess total stored energy combined with a low mean cell voltage.
The energy is unevenly distributed among cells. T2 is nearly balanced but
has insufficient stored energy. Treating both terminals as a single uniform
capacitor-energy deficit would therefore give an unsupported diagnosis.

## Sorting Contract Investigation

The installed library exposes
`E_SORTER(Dim, NS, Enab, order2, IN, OUT)` with ascending `order2=1`.
Its definition offers no explanation of the sign of `NS`. A read-only
inspection of the linked `lib/gf42/intermediate.lib` using the installed
GFortran 4.2.1 `nm.exe` and `objdump.exe` identifies these control-flow facts:

- In `csmf.o`, `_e_sorter_` computes `abs(NS)` and caps the sorting loop at
  `Dim-1`. With ascending order and positive `NS`, the outer loop covers
  positions `1..abs(NS)` and selects the lowest values into that prefix.
  The remaining suffix is not guaranteed to be ordered.
- With ascending order and negative `NS`, the outer loop covers the last
  `abs(NS)` positions, selecting the highest values into that suffix.
- In `mmc.o`, `_hbridge_ctrl1_` traverses `Idx` from `Dim` toward 1 when
  positive requested insertion meets negative arm current, or negative
  insertion meets positive arm current. It traverses from 1 toward `Dim`
  for the other current-sign combinations.

Auditable offsets are `_e_sorter_` `0x185..0x2e4` and `0x3d2..0x4b5`, and
`_hbridge_ctrl1_` `0x5555..0x5601` followed by its indexed selection loop.
The generated calls use an unsigned insertion count for the sorter. This
does not satisfy the suffix-order assumption used by the firing controller
in the opposite-sign cases. The waveform consequence still needs direct
measurement; these branches alone do not prove the entire model's failure
cause or justify changing measured current polarity.

The next diagnostic must compare the exact delayed voltage array supplied
to the sorter with its returned indices in the same calculation step, and
record count, enable, current direction and actual capacitor-current energy
moments. It must retain the original physical checks and preserve this
failed evidence. No vendor routine body or disassembly is copied into the
repository.

## Software Verification

From the fault-evidence worktree:

```powershell
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m pytest tests/test_mmc_fault_channels.py tests/test_mmc_template_audit.py tests/test_mmc_template_native.py -q
```

Result: **113 passed, 1 skipped in 19.45 s**. This verifies the reviewed
software contracts and regressions, not electrical acceptance of the MMC.
