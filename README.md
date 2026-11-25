# grid-engine

The physics core of [Certified Interconnection](https://certified-interconnection.github.io): seasonal cases,
NERC-style contingency sets and batch AC power flow on [Power Grid Model](https://github.com/PowerGridModel/power-grid-model).

```python
from gridengine import Engine, load_case, apply_season, p1, p7, n2_sample

base = Engine(load_case("case118"))                 # MATPOWER case -> Power Grid Model
winter = Engine(apply_season(base.case, "winter_peak"))
res = winter.contingency_analysis(p1(winter.branches))
print(res["secure"].sum(), "of", res["n"], "single outages secure")
```

## Status (v0.3)
Steps 1 to 4 of Certified Interconnection live here, each with tests and a generated report:

| Step | What | Where | Headline (95% intervals in the report) |
|---|---|---|---|
| 1 | AC engine on Power Grid Model: seasons, P1 / P7 / N2 contingencies, generator reactive limits, DC baseline | `gridengine/engine.py`, `dc.py`, `bench/validate*.py` | 18,935 of 19,041 cases agree with PYPOWER (MATPOWER port) to 1e-10 pu, no convergence disagreements |
| 2 | Capacity of each bus, project and cluster; exact best cluster decision | `gridengine/capacity.py`, `bench/capacity_study.py` | best cluster decision +15% MW over first come (IEEE 118, single outages); DC cluster pick AC-insecure in 15.6% of clusters |
| 3 | Ways to make room: flexible load, storage, generation tripping, one switch, partial MW | `gridengine/options.py`, `bench/options_study.py` | every option re-checked in AC; partial MW +4,962 MW, flexible load +2,751 MW over 80 clusters |
| 4 | Time and cost ranges from public sources only | `gridengine/costs.py`, `data/costs/sources.csv`, `bench/timelines.py` | PJM median 2.8 years from request to operation (1,205 projects) |

- Problem statement, hypotheses and failure criteria: [docs/FORMULATION.md](docs/FORMULATION.md)
- Every result with intervals, generated from `results/`: [docs/REPORT.md](docs/REPORT.md) (`python bench/report.py`)
- Step 5 (certify or defer) is kept private for now.

## What it does
- **Cases:** MATPOWER files read directly (IEEE 30, 118, 300; synthetic ACTIVSg 200, 500 and 2,000-bus grids).
- **Power Grid Model input:** every branch as a `generic_branch` (tap ratio, phase shift, rating), PV generators as
  `sym_gen` with a `voltage_regulator`, the slack as a stiff `source`, all nodes on a 100 MVA / 100 kV base,
  the same conventions as Power Grid Model's own IEEE validation cases.
- **Seasons** (stated assumptions, not any operator's cases): `summer_peak` = base case, `winter_peak` = loads x0.90,
  `light_load` = loads x0.55; generation scaled with load, and capacitor banks scaled with load (operators switch
  them out as load falls; leaving them in pushed the 2,000-bus grid to 1.15 pu and 152% loading before any outage).
- **Contingencies** (our definitions of the NERC TPL-001 categories): `P1` every single branch outage that doesn't
  island the grid; `P7` pairs of branches with the same two end buses (a stand-in for common-tower circuits);
  `N2` a seeded random sample of non-islanding double outages.
- **Security:** converged, no branch above 100% of its rating, all voltages in [0.90, 1.10] pu.
- **Ratings:** published RATE_A where the case has it. Where it doesn't (IEEE 118 and 300 have none), a stated
  rule: worst apparent power over the base case and every single outage, divided by 0.7.
- **Batch:** all contingencies of a set run as one Power Grid Model batch from a flat start (PGM's default linear
  start diverged on some outage cases).

## Checks
`pytest tests`: base-case voltages match pandapower to 1e-6 pu on three grids; single-outage voltages match
pandapower to 1e-5 pu; contingency-set sizes; season scaling; capacitor switching and a regression test that the
2,000-bus light-load base case is secure.

## Benchmarks
`python bench/benchmark.py <case>` writes `results/bench_<case>.json` (PGM batch vs a pandapower loop, same machine,
every season and contingency set). Run on Kaggle CPU (one notebook per grid); the JSON files are in `results/`.

| grid | season | P1 secure | P7 secure | N2 (300) secure | ms per outage |
|---|---|---|---|---|---|
| IEEE 118 | summer peak | 177 / 177 | 3 / 7 | 294 / 300 | 1.0 |
| IEEE 118 | winter peak | 177 / 177 | 4 / 7 | 297 / 300 | 1.0 |
| IEEE 118 | light load | 177 / 177 | 5 / 7 | 300 / 300 | 1.0 |
| IEEE 118 | pandapower loop, same machine | | | | 119 |
| IEEE 300 | summer peak | 289 / 322 | 0 / 1 | 229 / 300 | 2.8 |
| IEEE 300 | winter peak | 296 / 322 | 0 / 1 | 244 / 300 | 2.7 |
| IEEE 300 | light load | 308 / 322 | 1 / 1 | 272 / 300 | 2.6 |
| IEEE 300 | pandapower loop, same machine | | | | 138 |
| Texas 2,000 (synthetic) | summer peak | 2733 / 2756 | 398 / 718 | 291 / 300 | 35.2 |
| Texas 2,000 (synthetic) | winter peak | 2755 / 2756 | 493 / 718 | 300 / 300 | 34.2 |
| Texas 2,000 (synthetic) | light load | 2755 / 2756 | 701 / 718 | 300 / 300 | 33.4 |
| Texas 2,000 (synthetic) | pandapower loop, same machine | | | | 231 |

"Secure" counts only converged cases (non-converged count as not secure). IEEE 118 and 300 use the synthetic ratings
above; Texas 2,000 uses its published ratings. The pandapower loop runs Newton-Raphson from a flat start without
numba, one outage at a time, on the first 30 single outages, so it is a rough reference, not a tuned comparison:
Power Grid Model's batch is about 115x faster on IEEE 118, 50x on IEEE 300 and 7x on Texas 2,000 in this setup.
On Texas 2,000 in summer, 320 of 718 common-tower pairs (P7) are insecure, against 23 of 2,756 single outages.

## Limits
- Our contingency definitions are not any operator's study files; the input format is plain so a utility's own
  lists can replace them.
- Generator reactive limits are optional (`Engine(case, q_limits=True)` or `GE_QLIM=1`); headline numbers are without them and the report gives both. No dynamics yet.
- Short circuit is implemented but not yet validated against a reference.

## License
MIT. Part of Certified Interconnection, led by Sehaj Randhir Singh.
