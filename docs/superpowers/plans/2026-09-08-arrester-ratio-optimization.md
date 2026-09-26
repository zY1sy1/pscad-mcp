# Arrester Ratio Optimization

Goal: Optimize five residual-voltage scales in a copy of the cumulative-close
model. Previously closed switches stay closed. Preserve all original files.

Primary comparison fixes the first and last residual voltages at 100 and 60 kV
at 1 kA. Optimize the three middle scales to maximize the minimum new-branch
current share in stages 2-5. The source remains 120 kV / 20 ohm, the normalized
I-V curves remain unchanged, and timer events remain 0/2/4/6/8 ms. Compare the
existing arithmetic spacing, geometric spacing, optimized continuous values
and a practical rounded sequence. A secondary tradeoff study finds voltage
spans for at least 95% and 99% new-branch share at every later stage.

No manufacturer curves, current ratings or allowable minimum clamp voltage
were supplied. Expanded-span cases are therefore comparison cases, not rated
hardware recommendations. Report source current, minimum bus voltage and
energy duty alongside current shares. Do not claim a global hardware optimum.

- [x] Read the source model, existing current evidence and acceptance criteria.
- [x] Reconstruct the piecewise-linear static I-V network using SciPy roots.
- [x] Validate that network against existing native PSCAD results before search.
- [x] Search fixed-span candidates and expanded-span target cases.
- [x] Generate independent PSCAD copies and run every shortlisted case.
- [x] Compare measured current shares with predictions; retain all failed evidence.
- [x] Verify no reopening, KCL, waveform completeness, input hashes and owned cleanup.
- [x] Deliver optimized native cases, a comparison plot, data and a scoped recommendation.

Implementation files: scripts/arrester_ratio_search.py for static prediction
and search; scripts/run_arrester_ratio_study.py for native copies and validation;
tests/test_arrester_ratio_search.py for numeric/model-risk regression coverage.
The existing acceptance lifecycle and cumulative-result reader are reused.

The first native attempt compiled and ran all six cases. Analysis of the integer
case rejected a numeric-leading description as a malformed output row. That
attempt and its outputs are retained under the first study's runs directory.
The copied-case description now has a text prefix. Independent review also led
to strict preflight checks for search-code, source and candidate hashes. Final
evidence must come from a fresh search and run with the finalized code.

Final evidence is in
`C:/Users/335/Documents/PSCAD-MCP/five_arrester_ratio_optimization_20260908_final`.
All six native cases pass at code revision
`238fedd1413ae8f031247ef754cf1d4dd0ca34fd`. The continuous fixed-span result is
100/88.826306/77.904293/68.246790/60 kV and gives 86.9509% in each later stage.
The exhaustive integer-grid result is 100/89/78/68/60 kV (minimum 86.4445%).
The 95% and 99% copies achieve 95.01% and 99.01%, with final residual scales
49.789455 and 29.083811 kV and peak source currents 3.3512 and 4.4175 kA.
All original input hashes remain unchanged; owned PSCAD PID 19576 and all owned
EMTDC executables exited. Thirty-two focused tests and static checks passed.
