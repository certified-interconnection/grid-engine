"""Upgrade class, cost range and time range for a binding element of a capacity study.

    from gridengine.costs import Sources, upgrade
    src = Sources()                                  # data/costs/sources.csv, the only numbers used here
    upgrade(dict(kind="line", kv=138, rating_mva=180, required_mva=230), src)
    upgrade(dict(kind="transformer", kv_hi=345, kv_lo=138, rating_mva=400, required_mva=470), src)
    upgrade(dict(kind="low_voltage", kv=138, mvar=60), src)

Every cost and time number comes from data/costs/sources.csv (built by bench/cost_sources.py, one public URL per
row). If the CSV has no row for an element (for example a 230 kV line: that column was not transcribed), the cost
is returned as None with the reason; nothing is filled in.

Upgrade classes and the stated rules that pick them (modelling assumptions, not anyone's planning standard):
- Overloaded line, required MVA (rating x worst loading) at or below MISO's standard circuit rating for the voltage
  class (sources row miso_standard_circuit_rating_<kv>kv): "reconductor line", cost per mile from
  miso_reconductor_per_circuit_<kv>kv. Assumes the existing structures can carry the new conductor, as MISO's guide
  itself assumes for its reconductor estimates.
- Overloaded line, required MVA above that rating: "new parallel line", n = ceil((required - rating) / standard
  rating) new single circuits, cost per mile n x miso_new_single_circuit_<kv>kv (range over the 15 MISO states).
- Line costs are per mile only. The test grids have no line lengths; the only public ohms-per-mile figure found
  was a single 345 kV value (no range, no 138 kV value), so lengths are not inferred from reactance.
- Overloaded transformer: "add transformer", n = ceil((required - rating) / rating) parallel units each the size of
  the existing one, cost n x rating x miso_transformer_<hi>_<lo>kv ($/MVA, 2021 dollars).
- Low voltage at a bus: "add reactive support", cost mvar x miso_reactive_support (low = capacitor bank, central =
  SVC, high = STATCOM). The MVAr amount must come from the caller (a power-flow calculation, not a rule of thumb).
- High voltage at a bus: "add shunt reactor", cost mvar x miso_shunt_reactor.
- Diverged case: no upgrade class (the binding element is not identifiable from a non-converged solution).

Time:
- time_years = (25th, 75th percentile) of PJM queue entry to commercial operation for requests that entered in
  2013-2017 (pjm_queue_entry_to_cod_2013_2017), the most recent cohort with mostly resolved outcomes. It is the time
  for a whole request through PJM's process, used here because no source read gives construction time per upgrade
  class. The same range is returned for every class.
- equipment_lead_time_years (transformers only): large_power_transformer_lead_time (80 to 210 weeks, NIAC draft
  quoting Wood Mackenzie) converted at 52.18 weeks per year. Not added to time_years: ordering can overlap the study.

Dollars: MISO rows are 2021 dollars, LBNL rows 2022 dollars; no escalation is applied, the year is returned.
"""
from __future__ import annotations

import csv
import math
import os

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "costs", "sources.csv")
WEEKS_PER_YEAR = 52.18


class Sources:
    def __init__(self, path=DEFAULT_CSV):
        self.path = os.path.abspath(path)
        self.rows = {}
        with open(self.path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                for k in ("low", "central", "high"):
                    r[k] = float(r[k]) if r[k] not in ("", None) else None
                if not r["url"]:
                    raise ValueError(f"row {r['item']} has no source URL")
                self.rows[r["item"]] = r

    def get(self, item):
        return self.rows.get(item)

    def rng(self, item):
        r = self.rows[item]
        return (r["low"], r["central"], r["high"])


def _scale(rng, k):
    return tuple(None if v is None else v * k for v in rng)


def _kv(v):
    return int(round(float(v)))


def upgrade(el, src: Sources):
    """el: dict with kind in {"line", "transformer", "low_voltage", "high_voltage", "diverged"} and
    line: kv, rating_mva, required_mva; transformer: kv_hi, kv_lo, rating_mva, required_mva;
    low_voltage / high_voltage: kv, mvar.
    Returns dict(upgrade_class, cost_usd (low, central, high) or None, cost_usd_per_mile (lines), year_dollars,
    time_years (low, high), equipment_lead_time_years, items (sources.csv rows used), note)."""
    t = src.get("pjm_queue_entry_to_cod_2013_2017")
    out = dict(upgrade_class=None, cost_usd=None, cost_usd_per_mile=None, year_dollars=None,
               time_years=(t["low"], t["high"]), equipment_lead_time_years=None,
               items=["pjm_queue_entry_to_cod_2013_2017"], note="")
    kind = el["kind"]
    if kind == "diverged":
        out["note"] = "case diverged; no element to upgrade"
        return out

    if kind == "line":
        kv = _kv(el["kv"])
        std = src.get(f"miso_standard_circuit_rating_{kv}kv")
        if std is None:
            out.update(upgrade_class="line upgrade", note=f"no sourced rows for {kv} kV lines")
            return out
        req, rat = float(el["required_mva"]), float(el["rating_mva"])
        if req <= std["central"]:
            item = f"miso_reconductor_per_circuit_{kv}kv"
            out.update(upgrade_class="reconductor line", cost_usd_per_mile=src.rng(item),
                       note=f"required {req:.0f} MVA <= standard {kv} kV circuit {std['central']:.0f} MVA")
            out["items"] += [std["item"], item]
        else:
            n = math.ceil((req - rat) / std["central"])
            item = f"miso_new_single_circuit_{kv}kv"
            out.update(upgrade_class="new parallel line", cost_usd_per_mile=_scale(src.rng(item), n),
                       note=f"required {req:.0f} MVA > standard {kv} kV circuit {std['central']:.0f} MVA; "
                            f"{n} new circuit(s)")
            out["items"] += [std["item"], item]
        out["year_dollars"] = int(float(src.get(item)["year_dollars"]))
        return out

    if kind == "transformer":
        hi, lo = sorted((_kv(el["kv_hi"]), _kv(el["kv_lo"])), reverse=True)
        item = f"miso_transformer_{hi}_{lo}kv"
        req, rat = float(el["required_mva"]), float(el["rating_mva"])
        n = max(1, math.ceil((req - rat) / rat))
        out["upgrade_class"] = "add transformer"
        lt = src.get("large_power_transformer_lead_time")
        out["equipment_lead_time_years"] = (lt["low"] / WEEKS_PER_YEAR, lt["high"] / WEEKS_PER_YEAR)
        out["items"].append(lt["item"])
        if src.get(item) is None:
            out["note"] = f"no sourced $/MVA row for {hi}/{lo} kV"
            return out
        out.update(cost_usd=_scale(src.rng(item), n * rat), year_dollars=int(float(src.get(item)["year_dollars"])),
                   note=f"{n} parallel unit(s) of {rat:.0f} MVA")
        out["items"].append(item)
        return out

    if kind in ("low_voltage", "high_voltage"):
        item = "miso_reactive_support" if kind == "low_voltage" else "miso_shunt_reactor"
        mvar = float(el["mvar"]) if el.get("mvar") is not None else None
        out["upgrade_class"] = "add reactive support" if kind == "low_voltage" else "add shunt reactor"
        out["items"].append(item)
        out["year_dollars"] = int(float(src.get(item)["year_dollars"]))
        if mvar is None:
            out["note"] = "MVAr need not computed; cost per MVAr only"
            out["cost_usd_per_mvar"] = src.rng(item)
            return out
        out.update(cost_usd=_scale(src.rng(item), mvar), note=f"{mvar:.0f} MVAr")
        return out

    raise ValueError(f"unknown element kind {kind}")


def per_kw_range(mw, src: Sources, status="complete", fuel=None):
    """Network-upgrade cost range for `mw` of new generation from LBNL's PJM data (2022 dollars, $/kW percentiles
    25 / 50 / 75 of projects studied 2017-2022). fuel uses the per-fuel row when it exists (n >= 10)."""
    item = f"lbnl_pjm_network_cost_{status}" + (f"_{fuel}" if fuel else "")
    if src.get(item) is None:
        return None, item
    return _scale(src.rng(item), mw * 1000.0), item
