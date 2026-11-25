# Step 3: ways to make room (case118, P1)

Source: `results/options_case118.json` (written by `bench/options_study.py`; this file by `bench/options_report.py`).

90 clusters from `results/capacity_case118.json`, 80 of them do not fully fit as a plain all-or-nothing subset. Requested in total: 42599.1 MW. Plain best subset matches Step 2 in 90 of 90 clusters. Generator reactive limits: False. All re-checks passed: True.

| Option | Total MW admitted | Gain over plain (MW) | Clusters with a gain | Share of clusters that don't fit | Re-checks failed |
|---|---:|---:|---:|---:|---:|
| Plain best subset | 18271.0 | 0.0 |  |  | 0 |
| Flexible load, keep 50% | 21022.4 | 2751.4 | 33 | 41.2% | 0 |
| Flexible load, keep 0% | 21023.8 | 2752.8 | 34 | 42.5% | 0 |
| Storage 25% of load | 19095.7 | 824.7 | 16 | 20.0% | 0 |
| Storage 50% of load | 21022.4 | 2751.4 | 33 | 41.2% | 0 |
| Generation RAS, keep 0% | 26654.8 | 8383.8 | 57 | 71.2% | 0 |
| Best single switch | 18634.2 | 363.2 | 7 | 8.8% | 0 |
| Partial MW | 23233.4 | 4962.4 | 80 | 100.0% | 0 |

Storage 50% uses the same rule as flexible load keep 50% (load cut by half after an outage), so the two rows are equal by construction. Partial MW counts the fractional MW of left-out requests on top of the plain subset. Each option can fall back to the plain subset, so no option is below it.
