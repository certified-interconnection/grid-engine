"""Queue timelines from PJM's own public queue file (no outside data).

For every generation interconnection request that reached commercial operation: years from queue entry
(`submitted`) to in-service (`in_service`). For every request that withdrew: years from queue entry to
withdrawal (`withdrawn`). Reported as median with the 25th and 75th percentiles, overall, by fuel class,
by request-year cohort (2008-2012, 2013-2017, 2018+ where available, plus a pre-2008 group), by single
request year, and by cohort within fuel class.

Groups with fewer than MIN_N observations are kept in the JSON with their count but with the percentiles
set to null, so a reader can see how much of the file supports each number.

Usage: python bench/timelines.py [path/to/pjm_generation_requests.csv] -> results/timelines_pjm.json
Default input: the pjm-queue-data working copy; the file is PJM's public PlanningQueues.xml, cleaned.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

CSV = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/sehaj/certinter/pjm-queue-data/data/pjm_generation_requests.csv"
OUT = "results/timelines_pjm.json"
SOURCE_URL = "https://www.pjm.com/planning/services-requests/interconnection-queues.aspx"
MIN_N = 5
COHORTS = [("pre-2008", 1900, 2007), ("2008-2012", 2008, 2012), ("2013-2017", 2013, 2017), ("2018+", 2018, 2100)]


def stats(x):
    """n, median, p25, p75, mean of a duration in years; percentiles null when n < MIN_N."""
    x = pd.Series(x).dropna()
    n = int(len(x))
    if n == 0:
        return dict(n=0, median=None, p25=None, p75=None, mean=None, small_sample=True)
    out = dict(n=n, median=round(float(x.median()), 3), mean=round(float(x.mean()), 3), small_sample=n < MIN_N)
    if n >= MIN_N:
        out["p25"] = round(float(x.quantile(0.25)), 3)
        out["p75"] = round(float(x.quantile(0.75)), 3)
    else:
        out["p25"] = None
        out["p75"] = None
    return out


def cohort_of(year):
    for name, lo, hi in COHORTS:
        if lo <= year <= hi:
            return name
    return "unknown"


def table(df, col="years"):
    """Overall / by fuel / by cohort / by year / by cohort within fuel."""
    out = dict(overall=stats(df[col]))
    out["by_fuel"] = {str(k): stats(g[col]) for k, g in df.groupby("fuel_class")}
    out["by_cohort"] = {str(k): stats(g[col]) for k, g in df.groupby("cohort")}
    out["by_year"] = {str(int(k)): stats(g[col]) for k, g in df.groupby("year")}
    out["by_cohort_fuel"] = {
        f"{c} | {f}": stats(g[col]) for (c, f), g in df.groupby(["cohort", "fuel_class"])}
    return out


def main():
    df = pd.read_csv(CSV)
    for c in ("submitted", "withdrawn", "in_service"):
        df[c] = pd.to_datetime(df[c], format="%m/%d/%Y", errors="coerce")
    df["fuel_class"] = df["fuel_class"].fillna("unknown")
    df["year"] = df["submitted"].dt.year

    n_rows = len(df)
    q = dict(
        rows=n_rows,
        submitted_present=int(df.submitted.notna().sum()),
        in_service_present=int(df.in_service.notna().sum()),
        withdrawn_present=int(df.withdrawn.notna().sum()),
        in_service_present_by_status={str(k): int(v) for k, v in
                                      df[df.in_service.notna()].groupby("status").size().items()},
        withdrawn_present_by_status={str(k): int(v) for k, v in
                                     df[df.withdrawn.notna()].groupby("status").size().items()},
        submitted_year_min=int(df.year.min()), submitted_year_max=int(df.year.max()),
    )

    # --- reached commercial operation -------------------------------------------------
    svc = df[df.in_service.notna() & (df.status != "Withdrawn")].copy()
    dropped_withdrawn_with_date = int((df.in_service.notna() & (df.status == "Withdrawn")).sum())
    svc["years"] = (svc.in_service - svc.submitted).dt.days / 365.25
    neg = svc[svc.years < 0]
    svc = svc[svc.years >= 0]
    svc["cohort"] = svc.year.map(cohort_of)

    # --- withdrawn ---------------------------------------------------------------------
    wd = df[df.withdrawn.notna()].copy()
    wd["years"] = (wd.withdrawn - wd.submitted).dt.days / 365.25
    neg_w = wd[wd.years < 0]
    wd = wd[wd.years >= 0]
    wd["cohort"] = wd.year.map(cohort_of)

    # --- still waiting: how long has the queue been open for requests not yet resolved --
    ref = pd.Timestamp("2026-11-24")   # snapshot date of the file
    pend = df[(df.status == "Active") & df.in_service.isna()].copy()
    pend["years"] = (ref - pend.submitted).dt.days / 365.25
    pend["cohort"] = pend.year.map(cohort_of)

    out = dict(
        case="pjm_generation_requests",
        input_file=os.path.abspath(CSV),
        source_url=SOURCE_URL,
        source_note=("PJM public PlanningQueues.xml, cleaned into data/pjm_generation_requests.csv by the "
                     "pjm-queue-data repo (snapshot 2026-11-24). Dates as posted by PJM: submitted = queue entry."),
        unit="years",
        min_group_size=MIN_N,
        cohorts={c: [lo, hi] for c, lo, hi in COHORTS},
        data_quality=dict(
            q,
            service_rows_used=int(len(svc)),
            service_rows_dropped_negative_duration=int(len(neg)),
            service_rows_dropped_withdrawn_with_in_service_date=dropped_withdrawn_with_date,
            withdrawal_rows_used=int(len(wd)),
            withdrawal_rows_dropped_negative_duration=int(len(neg_w)),
            in_service_column_empty=int(df.in_service.isna().sum()),
            withdrawn_column_empty=int(df.withdrawn.isna().sum()),
        ),
        service=table(svc),
        withdrawal=table(wd),
        pending_active=dict(overall=stats(pend.years), by_cohort={str(k): stats(g.years) for k, g in
                                                                 pend.groupby("cohort")}),
    )
    os.makedirs("results", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1, default=float)

    s = out["service"]["overall"]
    w = out["withdrawal"]["overall"]
    print(f"wrote {OUT}")
    print(f"service: n={s['n']} median={s['median']} p25={s['p25']} p75={s['p75']}")
    print(f"withdrawal: n={w['n']} median={w['median']} p25={w['p25']} p75={w['p75']}")
    for c in ("2008-2012", "2013-2017", "2018+"):
        cs = out["service"]["by_cohort"].get(c)
        cw = out["withdrawal"]["by_cohort"].get(c)
        print(f"  {c}: service {cs}; withdrawal {cw}")


if __name__ == "__main__":
    main()
