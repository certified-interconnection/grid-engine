# Problem formulation (Steps 1 and 2)

## The question

A grid operator receives a cluster of interconnection requests at the same time: generators and large loads, each with
a bus and a size in MW. Before anything connects, the operator must show that the grid stays within limits in every
season it studies and after every outage in its contingency set. Two questions follow:

1. **Individual:** how many MW of each request fit on their own?
2. **Cluster:** which requests should be admitted together, and how does that compare with deciding one by one?

Today's fast screens answer both with a linear (DC) model and check afterwards with full AC power flow. Step 1 builds
and validates the AC engine; Step 2 measures individual and cluster capacity with it and compares the decision rules.

## Definitions

- **Grid and season.** A MATPOWER case and a load case `s` in {summer peak, winter peak, light load}: loads, generation
  and capacitor banks scaled by 1.00 / 0.90 / 0.55 (`gridengine/seasons.py`).
- **Contingency set** `C`: `P1` (every single-branch outage that does not island the grid), `P7` (pairs of branches
  with the same two end buses, a stand-in for common-tower circuits), `N2` (a seeded sample of non-islanding double
  outages). Our definitions, not an operator's study files (`gridengine/contingencies.py`).
- **Request** `i`: bus `b_i`, size `m_i` (MW), kind (generation or load), unity power factor. Injected at `b_i` and
  balanced by the existing generators in proportion to their output (deliverability-style).
- **Secure.** For a case `c` in `{base} ∪ C`, AC Newton-Raphson converges, every branch is at or below its rating,
  and every voltage is in [0.90, 1.10] pu.
- **Incremental rule.** A case that is already insecure before any request is added counts as passing if the requests
  don't make it worse (loading or voltage no further out of bounds than before, within 0.005). Studies charge a project
  only for the violations it causes or worsens.
- **Capacity** of a set of requests along a direction: the largest `t` in [0, 1] such that `t · request` passes every case,
  found by bisection (tolerance 1%), with contingency screening and a final check against the full set
  (`gridengine/capacity.py`).
- **Individual capacity** `cap_i`: capacity of request `i` alone. It "fits" if `cap_i = m_i`.
- **Joint capacity:** capacity of all requests scaled together.
- **Cluster decisions** (all-or-nothing per request, every one checked against the full AC set):
  - *first come:* in a random queue order, admit each request if the admitted set still passes;
  - *largest first:* the same in decreasing size;
  - *best subset (AC):* the subset with the most MW that passes, found exactly by trying subsets in decreasing MW;
  - *linear pick (DC):* the subset with the most MW that passes in DC, then checked in AC.

## Hypotheses

- **H1 (engine):** grid-engine (Power Grid Model) agrees with an independent AC solver (pandapower) to within 1e-6 pu in
  voltage on every comparable single outage. *Test:* `bench/validate.py`, part A.
- **H2 (linear baseline):** a DC security check calls a meaningful share of AC-insecure cases secure, more so for
  double outages and at peak load. *Test:* `bench/validate.py`, part B, the "DC secure, AC insecure" cell.
- **H3 (outages):** a single-outage criterion cuts the capacity of a typical bus by a large fraction, and by different
  amounts in different seasons. *Test:* `bench/capacity_study.py`, the N-0 vs P1 maps.
- **H4 (clusters):** deciding over the whole cluster admits more secure MW than first come, and the sum of individual
  capacities overstates what the cluster can take together. *Test:* `bench/capacity_study.py`, the cluster runs.
- **H5 (DC decisions):** the DC cluster pick is often not AC-secure, and DC individual capacity is a biased estimate of AC.
  *Test:* `bench/cluster_baselines.py`.

## Metrics and uncertainty

Every headline number is a share or a total over scenarios and is reported with a 95% interval: Wilson intervals for
shares, bootstrap over clusters (2,000 resamples) for totals and ratios (`bench/report.py`).

## What would count as a failure

- H1 fails if any comparable case differs by more than 1e-6 pu, or if the two solvers disagree on convergence.
- H4 fails if the best subset admits no more than first come in total, or the interval on the gain includes zero.
- H5 fails if the DC pick is AC-secure in essentially every cluster.

## Not claimed

Synthetic and test grids only (real utility models are restricted); our contingency definitions; no generator reactive
limits, short circuit or dynamics in these checks; all-or-nothing admission with no partial MW; costs and timelines are
Step 4.
