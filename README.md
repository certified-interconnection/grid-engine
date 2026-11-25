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

## What it does
- **Cases:** MATPOWER files read directly (IEEE 30, 118, 300; synthetic ACTIVSg 200, 500 and 2,000-bus grids).
- **Power Grid Model input:** every branch as a `generic_branch` (tap ratio, phase shift, rating), PV generators as
  `sym_gen` with a `voltage_regulator`, the slack as a stiff `source`, all nodes on a 100 MVA / 100 kV base,
  the same conventions as Power Grid Model's own IEEE validation cases.
- **Seasons** (stated assumptions, not any operator's cases): `summer_peak` = base case, `winter_peak` = loads x0.90,
  `light_load` = loads x0.55; generation scaled with load.
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
pandapower to 1e-5 pu; contingency-set sizes; season scaling.

## Benchmarks
`python bench/benchmark.py <case>` writes `results/bench_<case>.json` (PGM batch vs a pandapower loop, same machine,
every season and contingency set). Results are listed below once run.

## Limits
- Our contingency definitions are not any operator's study files; the input format is plain so a utility's own
  lists can replace them.
- No generator reactive limits yet (as in Power Grid Model's validation cases), no dynamics.
- Short circuit is next on the list.

## License
MIT. Part of Certified Interconnection, led by Sehaj Randhir Singh.
