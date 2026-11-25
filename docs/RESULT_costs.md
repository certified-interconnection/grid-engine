# Step 4 result: cost and time ranges

Branch `costs` of grid-engine, merged with `master` first. Nothing pushed. Every number below names the file it
comes from; every cost or time number used by the code is a row of `data/costs/sources.csv` with a public URL and
where in the source it is.

## What ran

| step | script | output | status |
|---|---|---|---|
| 1 timelines | `bench/timelines.py` (anaconda python) | `results/timelines_pjm.json` | ran |
| 2 sources | `bench/cost_sources.py` | `data/costs/sources.csv` (34 rows, all with URL) | ran |
| 3 cost layer | `gridengine/costs.py` | (module) | smoke-tested on hand-made elements |
| 4 cost study | `bench/cost_study.py` (grid-engine venv) | `results/costs_case118.json`, `RESULTS_COSTS.md` | see below |

The untracked files left by an earlier automated attempt were checked before use: `bench/timelines.py` was read
line by line and its headline numbers were recomputed independently in pandas (n = 1,205 and median 2.825 years
for service; n = 291 and median 2.951 for the 2008-2012 cohort; both match), so it was kept. Its JSON was
regenerated. `data/costs/raw/pjm_costs_2022_clean_data.xlsx` was downloaded again from LBNL's publication page and
is byte-identical (SHA-256 `50a36331...c0af245`, checked in `bench/cost_sources.py`), so it was kept.

## 1. Timelines from PJM's queue (`results/timelines_pjm.json`)

Source: PJM's public `PlanningQueues.xml` (https://www.pjm.com/planning/services-requests/interconnection-queues.aspx),
snapshot 2026-11-24, cleaned to `pjm-queue-data/data/pjm_generation_requests.csv`. The in-service date is PJM's
`ActualInServiceDate`, not a projected date.

Date columns: present, but only partly filled, as expected from request outcomes. Of 8,190 rows, `submitted` is
filled on 8,190, `in_service` on 1,217 (6,973 empty), `withdrawn` on 4,094 (4,096 empty). 90 of the 4,181 rows with
status Withdrawn have no withdrawal date. Dropped: 4 service rows and 1 withdrawal row with negative duration, and 8
rows with status Withdrawn that carry an in-service date. Requests were submitted 1997 to 2023.

Years from queue entry to commercial operation (status not Withdrawn, actual in-service date present):

| group | n | p25 | median | p75 |
|---|---|---|---|---|
| all | 1,205 | 1.49 | 2.83 | 4.75 |
| entered before 2008 | 375 | 1.13 | 2.39 | 4.15 |
| entered 2008-2012 | 291 | 1.61 | 2.95 | 5.20 |
| entered 2013-2017 | 385 | 1.78 | 3.16 | 4.92 |
| entered 2018+ | 154 | 0.95 | 2.52 | 4.58 |
| natural gas | 401 | 1.33 | 2.68 | 4.29 |
| solar | 345 | 2.08 | 3.98 | 5.63 |
| wind | 116 | 2.78 | 4.07 | 6.47 |
| storage | 40 | 1.48 | 2.15 | 3.80 |
| nuclear | 44 | 2.43 | 4.07 | 5.89 |
| coal | 65 | 0.81 | 1.84 | 3.07 |
| other | 154 | 0.93 | 1.54 | 2.25 |
| hydro | 32 | 1.16 | 1.67 | 3.87 |
| solar+storage | 7 | 1.04 | 1.46 | 2.22 |
| offshore wind | 1 | n/a | 6.96 | n/a |

The 2018+ row is survivor-biased: only requests that already finished are in it (2,348 requests entered 2018+ are
still Active, median 5.2 years in the queue so far, p25 4.3, p75 5.7). Use 2013-2017 for a typical process time.

Years from queue entry to withdrawal (withdrawal date present):

| group | n | p25 | median | p75 |
|---|---|---|---|---|
| all | 4,093 | 0.51 | 1.31 | 3.24 |
| entered before 2008 | 512 | 0.76 | 1.81 | 4.06 |
| entered 2008-2012 | 1,052 | 0.56 | 1.28 | 3.11 |
| entered 2013-2017 | 904 | 0.46 | 1.17 | 2.66 |
| entered 2018+ | 1,625 | 0.43 | 1.34 | 3.39 |
| solar | 2,015 | 0.43 | 1.03 | 2.95 |
| natural gas | 596 | 0.67 | 1.36 | 2.75 |
| wind | 477 | 0.87 | 2.12 | 4.82 |
| storage | 416 | 0.49 | 1.68 | 3.72 |
| solar+storage | 214 | 0.50 | 2.05 | 3.64 |

(Every fuel and every cohort-by-fuel cell, with counts, is in the JSON.)

Cross-check against LBNL "Queued Up 2025" (https://emp.lbl.gov/sites/default/files/2025-12/Queued%20Up%202025%20Edition%20-%2012.15.2025.pdf,
p.47, table "Sample Size (# requests) by Region and Year", PJM row): LBNL counts 67, 55, 92, 50, 35, 63, 60 PJM
projects reaching operation in 2018 to 2024. This file gives 68, 57, 93, 50, 35, 62, 48 for the same in-service
years, so the two agree closely except 2024 (48 vs 60). The PJM median durations in that report are only in charts,
which could not be read as numbers, so they are not compared. Its text (p.51) says the median request-to-operation
time across regions with data rose to over 4 years for projects built 2018-2024; this file gives a PJM median of
51 months (n = 413) for in-service years 2018-2024.

## 2. Cost sources (`data/costs/sources.csv`)

34 rows, every one with a public URL and the page / table / column it is on. Built by `bench/cost_sources.py`.

| source | rows | what | how read |
|---|---|---|---|
| LBNL / Exeter, "Interconnection Cost Analysis in the PJM Territory" (Jan 2023) data file, https://eta-publications.lbl.gov/sites/default/files/pjm_costs_2022_clean_data.xlsx | 17 | network and total interconnection cost, $/kW (2022 $), 25th / 50th / 75th percentile by request status and by status x fuel (n >= 10), projects studied 2017-2022 | computed from the xlsx; the three network medians (complete $16, active $68, withdrawn $136 per kW) match the report text, PDF p.6 footnotes 5-7, and the script stops if they don't |
| MISO "Transmission Cost Estimation Guide for MTEP21" (April 2021, 2021 $), copy filed in Texas PUC docket 53601, https://interchange.puc.texas.gov/Documents/53601_1_1208306.PDF | 13 | new single circuit $/mile (138, 161, 345 kV; min / median / max over 15 states), reconductor $/mile, standard circuit MVA, transformer $/MVA (345/138, 161/138), reactive devices $/MVAr, shunt reactor | transcribed by hand from the page images (the PDF is a scan; its OCR text is garbled), per-state values in `data/costs/miso_mtep21_line_costs.csv` |
| PJM queue, via `results/timelines_pjm.json` | 3 | queue entry to operation (all; 2013-2017) and to withdrawal, years | computed (section 1) |
| NIAC draft report on power transformers (June 2024), https://cisa.gov/sites/default/files/2024-06/DRAFT_NIAC_Addressing%20the%20Critical%20Shortage%20of%20Power%20Transformers%20to%20Ensure%20Reliability%20of%20the%20U.S.%20Grid_Report_06052024_508c.pdf | 1 | large power transformer lead time 80 / 120 / 210 weeks | p.3, a quote of Wood Mackenzie; a pre-decisional draft |

Single values: the MISO reconductor, standard-rating, 345/138 kV transformer and shunt-reactor rows are one number in
the source, so they are stored as low = central = high and marked "single value in source". The 161/138 kV
transformer row has two values (the table's two orientations differ) and no central value. The reactive-support
range is over device type (capacitor bank / SVC / STATCOM), not over projects.

## 3. What could not be sourced or accessed

- **MISO's own copy of the guide:** every cdn.misoenergy.org URL tried (MTEP21 to MTEP25) returned HTTP 403. The
  MTEP21 edition was read from the Texas PUC docket copy instead. Newer editions were not read, so the costs are
  2021 dollars and are not escalated.
- **LBNL's emp.lbl.gov pages** returned HTTP 403; the same files were downloaded from eta-publications.lbl.gov.
- **PJM network upgrade / RTEP cost tables:** the "Project Status & Cost Allocation" pages
  (https://www.pjm.com/planning/project-construction, .../rtep-upgrades-status/cost-allocation-view) load their data
  with JavaScript; a static fetch returns no table and no downloadable file link. Not used.
- **Line length from reactance:** the only public ohms-per-mile figure found was one 345 kV value (Iowa State EE552
  notes, https://home.engineering.iastate.edu/jdm/ee552/Transmission.pdf p.22, X = 0.06432 %/mile on 100 MVA), no
  138 kV value and no range. Not used; line upgrades are reported per mile only.
- **Construction time per upgrade class** (months to reconductor a line, build a new line, install a capacitor
  bank): no public source read gives these. The time range is PJM whole-process time (section 1) for every class,
  plus the transformer equipment lead time.
- **Queued Up PJM-specific durations:** only in charts; not read as numbers.
- **Interconnection costs for large loads:** LBNL's data cover generators only, so the per-kW cross-check applies
  to the generation part of each cluster only.

## 4. Illustrative cost study on IEEE 118 (`results/costs_case118.json`, `RESULTS_COSTS.md`)

**Illustrative only.** IEEE 118 is a public test grid with synthetic thermal ratings (worst N-1 flow / 0.7), no line
lengths and made-up requests; nothing here is a cost estimate for a real project. 90 clusters from
`results/capacity_case118.json`, each under P1 and P1+P7, re-run on grid-engine (generator reactive limits off, as
in the capacity run). All 180 stored best subsets re-checked secure.

| | P1 | P1+P7 |
|---|---|---|
| clusters that admit every request (no upgrade) | 10 | 9 |
| clusters that leave requests out | 80 | 81 |
| upgrade at the case binding the rest on top of the best subset: reconductor / new parallel line / add transformer / add reactive support | 71 / 2 / 4 / 3 | 74 / 1 / 3 / 3 |
| upgrade at the full-cluster binding case: reconductor / new line / add transformer | 74 / 0 / 6 | 74 / 1 / 6 |
| distinct branches the full cluster overloads (median, min-max) | 7.5 (1-40) | 9 (1-67) |

- Line upgrades are $ per mile only (MISO MTEP21, 2021 $): reconductor $0.34M/mile at 138 kV, $0.54M/mile at
  345 kV (single values in the source); new parallel 138 kV circuits $1.6M / $1.8M / $2.1M per mile per circuit.
- The binding transformer in the 4 (P1) transformer rows is the 161/138 kV unit (bus 85-86): $0.10M to $0.11M
  (one row $0.31M to $0.33M), no central value in the source; equipment lead time 1.5 to 4.0 years.
- The 3 reactive-support rows are bus 49 (138 kV) in cluster seed 28: 8 to 47 MVAr found by power flow, priced
  $10,506 / $101,043 / $200,000 per MVAr (capacitor / SVC / STATCOM).
- Time range on every row: 1.8 to 4.9 years (PJM 2013-2017 cohort, p25 to p75, n = 385); whole-process time, not
  construction time per upgrade.
- LBNL cross-check (PJM network-upgrade $/kW x generation MW left out): median over clusters with generation left
  out of $4.2M (complete-project percentiles, central) and $17.3M (active-project percentiles, central), n = 67
  (P1) and 71 (P1+P7) clusters.
- One element per binding case and no re-study after the upgrade: the full cluster overloads several branches at
  once (row above), so these are first-step upgrades, not plans.

## What failed or was fixed along the way

- The first full cost-study run (75 minutes, 6 processes) sized reactive support by testing 2,000 MVAr first and
  used the incremental tolerance even where the no-request case was in band; 4 of 6 voltage rows came back "not
  found". Fixed (`reactive_need` now mirrors `CapacityStudy._ok` and grows from 1 MVAr) and only the 6 voltage rows
  were recomputed (`python bench/cost_study.py case118 --patch-voltage`); the other rows don't use that function.
- `RESULT.md` is listed in the repo's `.gitignore`; it was committed with `git add -f` because the brief asks for it.
