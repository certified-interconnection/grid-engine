"""Build data/costs/sources.csv: every cost and time number the cost layer may use, each with its public URL and
where in the source it is. Nothing here is estimated from memory.

Three kinds of rows:
1. LBNL / Exeter PJM interconnection cost data file (computed here from the public xlsx, which is kept in
   data/costs/raw/ and matches the file on LBNL's publication page byte for byte, SHA-256 below). The medians are
   checked against the numbers printed in the LBNL report; the script stops if they disagree.
2. MISO Transmission Cost Estimation Guide for MTEP21 (April 27, 2021, 2021 dollars), read from the copy filed as a
   public workpaper in Texas PUC docket 53601 (MISO's own cdn.misoenergy.org returned HTTP 403 to every request).
   Values transcribed by hand from the page images; the per-state line table is in miso_mtep21_line_costs.csv.
3. Time: PJM's own queue (results/timelines_pjm.json, from bench/timelines.py) and the transformer lead-time range
   quoted in the NIAC draft report on power transformers.

Ranges: low, central, high. Where the source gives a single value (no spread), low = central = high and the
`note` column says "single value in source". Where it gives two values and no central one, central is left empty.

Usage: python bench/cost_sources.py -> data/costs/sources.csv
"""
import csv
import hashlib
import json
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
XLSX = os.path.join(ROOT, "data/costs/raw/pjm_costs_2022_clean_data.xlsx")
XLSX_SHA256 = "50a363318b18e36418ac1af4f7afb923998c0863d990a73b59816d014c0af245"
OUT = os.path.join(ROOT, "data/costs/sources.csv")

LBNL_XLSX_URL = "https://eta-publications.lbl.gov/sites/default/files/pjm_costs_2022_clean_data.xlsx"
LBNL_PDF_URL = "https://eta-publications.lbl.gov/sites/default/files/berkeley_lab_2023.1.12-_pjm_interconnection_costs.pdf"
MISO_URL = "https://interchange.puc.texas.gov/Documents/53601_1_1208306.PDF"
NIAC_URL = ("https://cisa.gov/sites/default/files/2024-06/DRAFT_NIAC_Addressing%20the%20Critical%20Shortage%20of%20"
            "Power%20Transformers%20to%20Ensure%20Reliability%20of%20the%20U.S.%20Grid_Report_06052024_508c.pdf")
PJM_QUEUE_URL = "https://www.pjm.com/planning/services-requests/interconnection-queues.aspx"

COLS = ["item", "unit", "low", "central", "high", "year_dollars", "url", "where_in_source", "note"]
# Medians printed in the LBNL report (PDF p.6, footnotes 5-7), used as a check on the computation below.
REPORT_NETWORK_MEDIAN = {"Complete": 16, "Active": 68, "Withdrawn": 136}
MIN_N = 10


def lbnl_rows():
    h = hashlib.sha256(open(XLSX, "rb").read()).hexdigest()
    assert h == XLSX_SHA256, f"LBNL xlsx hash changed: {h}"
    d = pd.read_excel(XLSX, sheet_name="data")
    d["study_year"] = pd.to_datetime(d["Study Date"]).dt.year
    s = d[d.study_year.between(2017, 2022)]
    rows = []
    for col, key in (("$2022 Network Cost/kW", "network"), ("$2022 Total Cost/kW", "total")):
        for st, g in s.groupby("Request Status"):
            x = g[col].dropna()
            q = x.quantile([0.25, 0.5, 0.75])
            if key == "network":
                assert round(q[0.5]) == REPORT_NETWORK_MEDIAN[st], (st, q[0.5])
            rows.append(dict(
                item=f"lbnl_pjm_{key}_cost_{st.lower()}", unit="$/kW", low=round(q[0.25], 1),
                central=round(q[0.5], 1), high=round(q[0.75], 1), year_dollars=2022, url=LBNL_XLSX_URL,
                where_in_source=(f"sheet 'data', column '{col}', Request Status = {st}, Study Date 2017-2022; "
                                 f"25th / 50th / 75th percentile over n={len(x)} projects"),
                note=(f"report: {LBNL_PDF_URL} (PDF p.6 footnotes 5-7 give the network medians: complete $16, "
                      f"active $68, withdrawn $136 per kW; reproduced here)" if key == "network" else
                      f"report: {LBNL_PDF_URL}")))
        if key == "network":
            for (st, fuel), g in s.groupby(["Request Status", "Fuel"]):
                x = g[col].dropna()
                if len(x) < MIN_N:
                    continue
                q = x.quantile([0.25, 0.5, 0.75])
                rows.append(dict(
                    item=f"lbnl_pjm_network_cost_{st.lower()}_{fuel.lower().replace(' ', '_')}", unit="$/kW",
                    low=round(q[0.25], 1), central=round(q[0.5], 1), high=round(q[0.75], 1), year_dollars=2022,
                    url=LBNL_XLSX_URL,
                    where_in_source=(f"sheet 'data', column '{col}', Request Status = {st}, Fuel = {fuel}, "
                                     f"Study Date 2017-2022; 25th / 50th / 75th percentile over n={len(x)}"),
                    note=f"fuel groups with n < {MIN_N} left out"))
    return rows


def miso_rows():
    rows = []
    line = pd.read_csv(os.path.join(ROOT, "data/costs/miso_mtep21_line_costs.csv"))
    for kv, g in line.groupby("kv"):
        v = g.new_single_circuit_usd_per_mile
        rows.append(dict(
            item=f"miso_new_single_circuit_{kv}kv", unit="$/mile", low=int(v.min()), central=int(v.median()),
            high=int(v.max()), year_dollars=2021, url=MISO_URL,
            where_in_source=(f"MISO Transmission Cost Estimation Guide for MTEP21, guide p.38 (docket PDF p.39), "
                             f"table 'Exploratory cost estimate - A/C Transmission, New single circuit transmission "
                             f"line $/mile', {kv}kV column; min / median / max over the 15 states listed"),
            note="includes contingency (30%) and AFUDC (7.5%) per the table footnote; per-state values in "
                 "data/costs/miso_mtep21_line_costs.csv"))
    for kv, v in ((138, 340000), (161, 350000), (345, 540000)):
        rows.append(dict(
            item=f"miso_reconductor_per_circuit_{kv}kv", unit="$/mile", low=v, central=v, high=v, year_dollars=2021,
            url=MISO_URL,
            where_in_source=(f"guide p.39 (docket PDF p.40), table 'Rebuild and reconductor transmission line "
                             f"$/mile', row 'Reconductor - per circuit', {kv}kV column, 'All States'"),
            note="single value in source; includes contingency (30%) and AFUDC (7.5%)"))
    for kv, mva in ((138, 394), (161, 460), (345, 1792)):
        rows.append(dict(
            item=f"miso_standard_circuit_rating_{kv}kv", unit="MVA", low=mva, central=mva, high=mva, year_dollars="",
            url=MISO_URL,
            where_in_source=(f"guide p.34 (docket PDF p.35), table 'Conductor selection per circuit - A/C "
                             f"Transmission', row 'Power rating (MVA)', {kv}kV column"),
            note="single value in source; MISO's typical new or reconductored circuit for the voltage class"))
    rows.append(dict(
        item="miso_transformer_345_138kv", unit="$/MVA", low=6089, central=6089, high=6089, year_dollars=2021,
        url=MISO_URL,
        where_in_source=("guide p.26 (docket PDF p.27), table 'Power transformer ($/MVA)', cells 345kV row / 138kV "
                         "column and 138kV row / 345kV column (both $6,089)"),
        note="single value in source; includes material, shipping, foundation and installation"))
    rows.append(dict(
        item="miso_transformer_161_138kv", unit="$/MVA", low=4705, central="", high=4961, year_dollars=2021,
        url=MISO_URL,
        where_in_source=("guide p.26 (docket PDF p.27), table 'Power transformer ($/MVA)', cells 161kV row / 138kV "
                         "column ($4,705) and 138kV row / 161kV column ($4,961)"),
        note="the two orientations of the table differ; no central value in source"))
    rows.append(dict(
        item="miso_reactive_support", unit="$/MVAr", low=10506, central=101043, high=200000, year_dollars=2021,
        url=MISO_URL,
        where_in_source=("guide p.27 (docket PDF p.28), table 'Grid supporting devices unit costs', 138kV and 345kV "
                         "columns: low = Capacitor bank $10,506, central = Static VAr Compensator $101,043, "
                         "high = STATCOM $200,000 (same value in every voltage column)"),
        note="range is over device type, not over projects; bus position to connect the device not included"))
    return rows


def time_rows():
    t = json.load(open(os.path.join(ROOT, "results/timelines_pjm.json")))
    rows = []
    for name, s, where in (
            ("pjm_queue_entry_to_cod_all", t["service"]["overall"], "service.overall"),
            ("pjm_queue_entry_to_cod_2013_2017", t["service"]["by_cohort"]["2013-2017"], "service.by_cohort.2013-2017"),
            ("pjm_queue_entry_to_withdrawal_all", t["withdrawal"]["overall"], "withdrawal.overall")):
        rows.append(dict(
            item=name, unit="years", low=s["p25"], central=s["median"], high=s["p75"], year_dollars="",
            url=PJM_QUEUE_URL,
            where_in_source=(f"PJM PlanningQueues.xml (snapshot 2026-11-24), ActualInServiceDate or WithdrawalDate "
                             f"minus SubmittedDate; computed by bench/timelines.py, results/timelines_pjm.json "
                             f"{where}; 25th / 50th / 75th percentile over n={s['n']}"),
            note="2018+ requests that reached service are a survivor-biased sample (only fast ones finished)"))
    rows.append(dict(
        item="large_power_transformer_lead_time", unit="weeks", low=80, central=120, high=210, year_dollars="",
        url=NIAC_URL,
        where_in_source=("NIAC draft report (June 2024), p.3, Executive Summary: quotes Wood Mackenzie, lead times "
                         "'120 weeks on average in 2024' and 'Large transformers ... lead times ranging from 80 to "
                         "210 weeks'"),
        note="secondary quote of Wood Mackenzie in a pre-decisional draft; equipment lead time only, not "
             "permitting or construction"))
    return rows


def main():
    rows = lbnl_rows() + miso_rows() + time_rows()
    for r in rows:
        assert r["url"], r
        for k in ("low", "central", "high"):
            if r[k] != "" and r[k] is not None:
                r[k] = float(r[k])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} rows")


if __name__ == "__main__":
    main()
