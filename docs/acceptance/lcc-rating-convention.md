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
voltage: an ideal series pair of six-pulse bridges has
`U_d0 = 2 * (3 sqrt(2) / pi) * U_LL`, before firing angle and commutation-drop
effects. Source immutability, physical thresholds and independent-reference
requirements remain applicable. Previous raw reports retain their original
request and revision; this correction does not relabel them as accepted.
