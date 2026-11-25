THE BRIEF (do exactly this; it replaces any older TASK.md or RESULT.md in the repo):

# G1: build grid-engine, the physics core of Certified Interconnection

Repo: C:\Users\sehaj\certinter\grid-engine (public, org certified-interconnection, Sehaj's). Empty except README.

## HARD RULES
- Never push or touch any git remote. Commit locally after EVERY step (small commits).
- Never invent numbers. Every number in README.md or RESULT.md must come from a results/*.json written by a committed
  script. If something fails, write that plainly.
- No em dashes anywhere.
- Heavy runs (2,000-bus grid, benchmarks) go to Kaggle (`kaggle kernels push`, CPU). Laptop only for tests on
  grids up to 118 buses. Use the Python at C:\Users\sehaj\pgm-contrib\.venv\Scripts\python.exe (has
  power_grid_model 1.13) and `pip install pandapower matpowercaseframes` into it if missing.
- Use `pandapower` only as the independent cross-check, never as the engine.

## What to build: a small Python package `gridengine/`
1. `cases.py`: load a grid from pandapower.networks (case30, case118, case300, case_illinois200) or a MATPOWER file
   (copy C:\Users\sehaj\cluster-screen\data\raw\case_ACTIVSg2000.m and case_ACTIVSg500.m into data/). Return one
   neutral dataclass (buses, lines/transformers with ratings, loads, generators, slack).
2. `seasons.py`: three load cases from a base case: `summer_peak` (loads x1.00), `winter_peak` (x0.90, power
   factor 0.97), `light_load` (x0.55, with generators re-dispatched pro rata). Document the assumptions in the
   README; they are simple, public, stated choices, not PJM's cases.
3. `contingencies.py`: NERC TPL-001 style sets on the branch list: `P1` single branch outages (skip bridges that
   island the grid), `P7` common-corridor double outages (pairs of branches with the same two end buses), and `N2`
   a seeded random sample of non-islanding branch pairs.
4. `pgm.py`: convert the case to Power Grid Model input (sym_load, sym_gen, source for slack, line or
   generic_branch, transformer where needed), and run a **batch** power flow where each scenario switches branch
   status (from_status/to_status) for one contingency. Return per-scenario branch loading (vs rating), bus voltage
   magnitudes, and a secure flag (no loading > 1.0, voltages in [0.9, 1.1]).
5. `shortcircuit.py`: three-phase fault current at every bus using PGM's short-circuit calculation; report the
   max fault current per bus.
6. `tests/`: (a) intact power flow on case30 and case118 matches pandapower voltages to 1e-6 pu; (b) the P1 batch
   result for 5 contingencies matches pandapower runs with the branch removed, to 1e-5 pu; (c) contingency set sizes
   are what the definitions give. `pytest -q` must pass.
7. `bench/benchmark.py`: time the full P1 batch on case118 (laptop) and case_ACTIVSg2000 (Kaggle), PGM batch vs a
   pandapower loop, same machine; write results/bench_<case>.json.
8. README: what it does, install, a 10-line example, the season and contingency definitions, the benchmark table
   from results/, honest limits. RESULT.md: what was built, test status, numbers with their source files, what
   is unfinished.

## Done means
pytest passes, results/bench_case118.json exists (and bench_case_ACTIVSg2000.json if the Kaggle run finished),
README and RESULT.md written, everything committed, nothing pushed.


---
You are one Freebuff session. Your working directory is the git repo C:\Users\sehaj\certinter\grid-engine.

Read your brief first and do exactly what it says: C:\Users\sehaj\freebuff-jobs\G1-grid-engine.md
If earlier sessions already built part of it (check git log, RESULT.md history, results/), continue from there instead of starting over.

Work until the tests pass and every deliverable in the brief exists. Then commit with git and write RESULT.md
in the repo root (what you built, test status, anything left unfinished). Do not push.
