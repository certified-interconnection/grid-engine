# Step 3 result: ways to make room

## What ran
- `gridengine/options.py` (class `OptionsStudy`, wraps `CapacityStudy`, changes nothing in it or in `Engine`):
  post-contingency curtailment (`best_subset_flexible`), storage at loads (`best_subset_storage`), generation RAS
  (`best_subset_ras`), one permanent switch (`best_switch`, on a copied engine input with the branch at status 0),
  and partial MW (`partial_mw`). Every search is exact over subsets above the plain best subset, uses
  `CapacityStudy._ok` with the original grid's no-request baseline, and every admitted set is re-checked with the full
  AC set through `CapacityStudy`'s own evaluation path.
- `tests/test_options.py`: 12 tests on case118 (keep = 1.0 gives the plain subset exactly; every option re-checks
  secure under its own rule; every option admits at least the plain subset; curtailment gains are not firm-secure;
  search and re-check code paths agree; the Engine is not mutated). Full suite: 24 passed.
- `bench/options_study.py case118 4` on Kaggle CPU (kernel `sehajrsingh/ge-options-case118`, dataset
  `sehajrsingh/ge-options-src`, copy in `bench/kaggle/options_case118`), 90 clusters, P1, reactive limits off (as in
  Step 2). Wall time 386 s.
- `bench/options_report.py` -> `RESULTS_OPTIONS.md` and `results/options_case118.png`.

## Numbers (all from `results/options_case118.json`, `summary`)
80 of 90 clusters do not fully fit. Plain best subset: 18271.0 MW of 42599.1 MW requested, and it matches Step 2 in
90 of 90 clusters. All re-checks passed; no option is below the plain subset in any cluster.

| Option | Total MW | Gain (MW) | Clusters with a gain |
|---|---:|---:|---:|
| Flexible load, keep 0.5 | 21022.4 | 2751.4 | 33 |
| Flexible load, keep 0.0 | 21023.8 | 2752.8 | 34 |
| Storage 25% | 19095.7 | 824.7 | 16 |
| Storage 50% | 21022.4 | 2751.4 | 33 |
| Generation RAS, keep 0.0 | 26654.8 | 8383.8 | 57 |
| Best single switch | 18634.2 | 363.2 | 7 |
| Partial MW | 23233.4 | 4962.4 | 80 |

## What failed or is weak
- The single switch adds little (363.2 MW, 7 clusters). Most of the 20 candidates per cluster are skipped by our
  islanding rule (a switch is skipped if any P1 outage would island the grid once it is open; per-cluster counts in
  `skipped_islanding`). On case118 many heavily loaded branches sit in two-branch cuts, so this rule removes them.
- Storage 50% is the same rule as flexible load keep 0.5, so those rows are equal by construction, not a finding.
- Curtailment is not monotone in `keep` in AC: in light_load cluster 23 keep 0.0 gains 89.0 MW and keep 0.5 gains 0;
  in light_load cluster 12 keep 0.5 gains 201.0 MW and keep 0.0 gains 152.7 MW (per-cluster records in the JSON).
- Kaggle pushes first hit the 5-session cap; the push loop retried until a slot opened.

## Limits
- Our rules, not an operator's: curtailment acts instantly and is modeled as a steady-state change at the next power
  flow; no dynamics, no RAS arming logic, no storage energy limit or state of charge.
- Balance stays pro rata across existing generators; the switch candidates come from one binding case only.
- Partial MW is sequential (largest left-out request first), so it is a feasible point, not the best fractional mix.
- Synthetic ratings (worst N-1 flow / 0.7), case118 only, P1 only, reactive limits off.
