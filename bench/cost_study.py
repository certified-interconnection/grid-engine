"""Illustrative cost and time to admit the rest of each cluster on IEEE 118 (a public test grid, synthetic ratings).

For every cluster in results/capacity_case118.json and each contingency set (P1, P1+P7):
- best subset: the stored exact best all-or-nothing subset (re-checked here). The rest of the cluster is added on
  top of it, scaled together by t in [0, 1]; the case and element that bind first are the "best subset" binding.
- full cluster: every request at full size; the failing case with the worst loading (same rule as
  CapacityStudy._binding) and the element in it that the requests overload or pull out of the voltage band.
For each binding element, gridengine.costs gives the upgrade class and cost / time ranges from data/costs/sources.csv.
Overloads are sized at the full cluster (rating x worst loading in that case); a low-voltage bus gets the MVAr found
by bisection on a capacitive injection at that bus until that one case passes. One element per case, no re-study
after the upgrade, so these are first-step upgrades, not a full plan.
Also reported: LBNL PJM network-upgrade $/kW ranges times the MW of generation left out (loads are not covered by
that data).

These numbers are illustrative only: IEEE 118 is a test grid with no line lengths, synthetic thermal ratings and
made-up requests; costs are MISO 2021 and LBNL 2022 dollars, not escalated.

Usage: python bench/cost_study.py [case118] -> results/costs_case118.json, RESULTS_COSTS.md
"""
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np
from power_grid_model import ComponentType, DatasetType, initialize_array

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7   # noqa: E402
from gridengine.capacity import CapacityStudy                           # noqa: E402
from gridengine.costs import Sources, upgrade, per_kw_range              # noqa: E402

CASE = sys.argv[1] if len(sys.argv) > 1 else "case118"
NPROC = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TOL = 0.005          # the incremental rule's tolerance in CapacityStudy._ok
_E = {}
_CAP = {}


def engines():
    if not _E:
        base = Engine(load_case(CASE))
        _E["base"] = base
        for s in SEASONS:
            _E[s] = Engine(apply_season(base.case, s))
    return _E


def raw(cs, requests, scale, case, extra_q=None):
    """One case, full output (per-branch loading, per-node voltage). Same injection and balance as
    CapacityStudy._evaluate. extra_q: (probe position, var) capacitive injection at a probe bus."""
    p, net = cs._injection(requests, np.asarray(scale, float)[None, :])
    upd = dict(cs.eng._update([case]))
    sl = initialize_array(DatasetType.update, ComponentType.sym_load, (1, len(cs.input["sym_load"])))
    sl["id"] = cs.input["sym_load"]["id"][None, :]
    sl["p_specified"] = cs.input["sym_load"]["p_specified"][None, :]
    sl["q_specified"] = cs.input["sym_load"]["q_specified"][None, :]
    sl["p_specified"][:, cs.n_load0:] = p[0][None, :]
    q = np.abs(p[0]) * cs.tanphi * np.sign(p[0])
    if extra_q is not None:
        q = q.copy(); q[extra_q[0]] -= extra_q[1]
    sl["q_specified"][:, cs.n_load0:] = q[None, :]
    upd["sym_load"] = sl
    if cs.balance == "gens" and len(cs.gen_p0) and cs.gen_p0.sum() > 0:
        g = initialize_array(DatasetType.update, ComponentType.sym_gen, (1, len(cs.gen_p0)))
        g["id"] = cs.input["sym_gen"]["id"][None, :]
        g["p_specified"] = (cs.gen_p0 * max(1.0 - net[0] / cs.gen_p0.sum(), 0.0))[None, :]
        upd["sym_gen"] = g
    out, failed = cs.eng.run(model=cs.model, update=upd, n=1)
    L = np.nan_to_num(out["generic_branch"]["loading"][0], nan=0.0)
    u = out["node"]["u_pu"][0]
    conv = bool(np.isfinite(u).all() and u.min() > 0 and not failed[0])
    return dict(loading=L, u=u, converged=conv)


def element(cs, requests, scale, case, reason, case_kv, trafo):
    """The element charged to the requests in this case, and what the upgrade must cover."""
    E = cs.eng
    r = raw(cs, requests, scale, case)
    z = raw(cs, requests, np.zeros(len(requests)), case)
    if reason == "diverged" or not r["converged"]:
        return dict(kind="diverged")
    gb = cs.input["generic_branch"]
    lo, hi = E.v_band
    if reason == "overload":
        charged = r["loading"] > np.maximum(1.0, z["loading"]) + TOL
        if not charged.any():
            charged = r["loading"] > 1.0 + 1e-9
        k = int(np.argmax(np.where(charged, r["loading"], -1)))
        f, t = int(gb["from_node"][k]), int(gb["to_node"][k])
        rating = float(gb["sn"][k]) / 1e6
        req = rating * float(r["loading"][k])
        base = dict(branch_id=int(gb["id"][k]), from_bus=f, to_bus=t, rating_mva=rating, required_mva=req,
                    loading=float(r["loading"][k]))
        if trafo[k]:
            return dict(kind="transformer", kv_hi=max(case_kv[f], case_kv[t]), kv_lo=min(case_kv[f], case_kv[t]), **base)
        return dict(kind="line", kv=case_kv[f], **base)
    low = reason == "low voltage"
    bad = (r["u"] < np.minimum(lo, z["u"]) - TOL) if low else (r["u"] > np.maximum(hi, z["u"]) + TOL)
    if not bad.any():
        bad = (r["u"] < lo) if low else (r["u"] > hi)
    b = int(np.argmin(np.where(bad, r["u"], np.inf))) if low else int(np.argmax(np.where(bad, r["u"], -np.inf)))
    mvar = reactive_need(cs, requests, scale, case, b, z, low)
    return dict(kind="low_voltage" if low else "high_voltage", bus=b, kv=case_kv[b], u_pu=float(r["u"][b]), mvar=mvar)


def reactive_need(cs, requests, scale, case, bus, z, low, qmax_mvar=2000.0):
    """MVAr (capacitive if low, inductive if high) at `bus` for this case to pass the voltage part of the
    incremental rule, by bisection to 1 MVAr. None if not reached within qmax_mvar."""
    cs2 = CapacityStudy(cs.eng, sorted(set(cs.buses) | {bus}), balance=cs.balance)
    pos = cs2.pos[bus]
    lo_b, hi_b = cs.eng.v_band
    sgn = 1.0 if low else -1.0

    def ok(q):
        r = raw(cs2, requests, scale, case, extra_q=(pos, sgn * q * 1e6))
        if not r["converged"]:
            return False
        if low:
            return bool((r["u"] >= np.minimum(lo_b, z["u"]) - TOL).all())
        return bool((r["u"] <= np.maximum(hi_b, z["u"]) + TOL).all())

    if not ok(qmax_mvar):
        return None
    a, b = 0.0, qmax_mvar
    while b - a > 1.0:
        m = 0.5 * (a + b)
        a, b = (a, m) if ok(m) else (m, b)
    return round(b, 1)


def charged_elements(cs, requests, scale, allc, ok):
    """Distinct branches overloaded and buses out of band (beyond the no-request case, as in the incremental rule)
    over every failing case: how many elements a full plan would have to touch, not just the binding one."""
    lo, hi = cs.eng.v_band
    br, bus, div = set(), set(), 0
    for i in np.nonzero(~ok)[0]:
        r = raw(cs, requests, scale, allc[i])
        z = raw(cs, requests, np.zeros(len(requests)), allc[i])
        if not r["converged"]:
            div += 1
            continue
        br |= set(np.nonzero(r["loading"] > np.maximum(1.0, z["loading"]) + TOL)[0].tolist())
        bus |= set(np.nonzero((r["u"] < np.minimum(lo, z["u"]) - TOL) | (r["u"] > np.maximum(hi, z["u"]) + TOL))[0].tolist())
    return dict(n_branches_charged=len(br), n_buses_charged=len(bus), n_cases_diverged=div)


def cases_of(E, name):
    return p1(E.branches) + (p7(E.branches) if name == "P1+P7" else [])


def study_cluster(cl, name, src, case_kv, trafo):
    E = engines()[cl["season"]]
    reqs = cl["requests"]
    cs = CapacityStudy(E, sorted(set(int(r["bus"]) for r in reqs)))
    conts = cases_of(E, name)
    allc = [()] + list(conts)
    k = len(reqs)
    best = cl[name]["cluster"]["admitted"]
    a = np.zeros(k); a[best] = 1.0
    rest = [j for j in range(k) if j not in best]
    ok_best = bool(cs._check(reqs, a, allc)[0].all())
    out = dict(seed=cl["seed"], season=cl["season"], set=name, n_requests=k, best_subset=best,
               best_mw=float(sum(reqs[j]["mw"] for j in best)), rest=rest,
               rest_mw=float(sum(reqs[j]["mw"] for j in rest)),
               rest_gen_mw=float(sum(reqs[j]["mw"] for j in rest if reqs[j]["kind"] == "gen")),
               rest_load_mw=float(sum(reqs[j]["mw"] for j in rest if reqs[j]["kind"] == "load")),
               best_subset_rechecked_secure=ok_best)
    if not rest:
        out["note"] = "whole cluster admitted; no upgrade needed"
        return out
    full = np.ones(k)
    ok_full, r_full = cs._check(reqs, full, allc)
    if ok_full.all():
        out["note"] = "full cluster passes on re-check"
        return out
    # full cluster binding case
    bf = cs._binding(r_full, ok_full, allc)
    i_full = int(np.nonzero(~ok_full)[0][np.argmax(r_full["max_loading"][~ok_full])])
    el_f = element(cs, reqs, full, allc[i_full], bf["reason"], case_kv, trafo)
    out["full_cluster"] = dict(binding=bf, n_failing_cases=int((~ok_full).sum()), element=el_f,
                               upgrade=upgrade(el_f, src), **charged_elements(cs, reqs, full, allc, ok_full))
    # best subset + rest scaled by t: first case to bind
    lo_t, hi_t = 0.0, 1.0
    while hi_t - lo_t > 0.01:
        m = 0.5 * (lo_t + hi_t)
        if cs._check(reqs, a + m * (1 - a), allc)[0].all():
            lo_t = m
        else:
            hi_t = m
    s_hi = a + hi_t * (1 - a)
    ok_h, r_h = cs._check(reqs, s_hi, allc)
    bb = cs._binding(r_h, ok_h, allc)
    i_b = int(np.nonzero(~ok_h)[0][np.argmax(r_h["max_loading"][~ok_h])])
    el_b = element(cs, reqs, s_hi, allc[i_b], bb["reason"], case_kv, trafo)
    # size an overload at the full cluster in the same case (the upgrade has to carry all of the rest)
    if el_b["kind"] in ("line", "transformer"):
        rf = raw(cs, reqs, full, allc[i_b])
        kk = int(np.nonzero(cs.input["generic_branch"]["id"] == el_b["branch_id"])[0][0])
        if rf["converged"]:
            el_b["required_mva_full"] = el_b["rating_mva"] * float(rf["loading"][kk])
            el_b["required_mva"] = max(el_b["required_mva"], el_b["required_mva_full"])
    elif el_b["kind"] in ("low_voltage", "high_voltage"):
        zb = raw(cs, reqs, np.zeros(k), allc[i_b])
        el_b["mvar_at_t"] = el_b["mvar"]
        el_b["mvar"] = reactive_need(cs, reqs, full, allc[i_b], el_b["bus"], zb, el_b["kind"] == "low_voltage")
    out["best_subset_plus_rest"] = dict(t_rest=lo_t, binding=bb, element=el_b, upgrade=upgrade(el_b, src))
    lb = {}
    for st in ("complete", "active"):
        rng_, item = per_kw_range(out["rest_gen_mw"], src, st)
        lb[st] = dict(cost_usd=rng_, item=item)
    out["lbnl_per_kw"] = lb
    return out


def fmt_rng(r, scale=1e6, nd=1):
    if r is None:
        return "n/a"
    lo, c, hi = r
    f = lambda v: "n/a" if v is None else f"{v / scale:.{nd}f}"
    return f"{f(lo)} / {f(c)} / {f(hi)}"


def job(a):
    i, name = a
    cap = _CAP.get("cap") or _CAP.setdefault("cap", json.load(open(f"results/capacity_{CASE}.json")))
    E = engines()
    case = E["base"].case
    case_kv = {int(b[0]): float(b[9]) for b in case["bus"]}
    brr = case["branch"][case["branch"][:, 10] > 0]
    kv_f = np.array([case_kv[int(x)] for x in brr[:, 0]]); kv_t = np.array([case_kv[int(x)] for x in brr[:, 1]])
    trafo = (brr[:, 8] != 0) | (kv_f != kv_t)
    return study_cluster(cap["clusters"][i], name, Sources(), case_kv, trafo)


def main():
    t0 = time.time()
    cap = json.load(open(f"results/capacity_{CASE}.json"))
    src = Sources()
    E = engines()
    jobs = [(i, name) for i in range(len(cap["clusters"])) for name in ("P1", "P1+P7")]
    with mp.get_context("spawn").Pool(NPROC) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    out = dict(case=CASE, illustrative=True,
               caveat=("IEEE 118 test grid with synthetic ratings, no line lengths and made-up requests; costs are "
                       "MISO MTEP21 (2021 $) and LBNL PJM (2022 $) unit costs from data/costs/sources.csv, not "
                       "escalated; one element per binding case, no re-study after the upgrade."),
               sources_csv=os.path.relpath(src.path), q_limits=E["base"].q_limits, ratings=E["base"].ratings,
               n_clusters=len(cap["clusters"]), rows=rows, wall_seconds=time.time() - t0)
    json.dump(out, open(f"results/costs_{CASE}.json", "w"), indent=1, default=float)
    write_md(out)
    print("wrote", time.time() - t0)


def write_md(out):
    rows = out["rows"]
    L = ["# Cost and time to admit the rest of each cluster (IEEE 118, illustrative)", "",
         "**Illustrative only.** IEEE 118 is a public test grid: synthetic thermal ratings, no line lengths, made-up "
         "requests. Unit costs come from `data/costs/sources.csv` (MISO MTEP21 guide, 2021 dollars; LBNL PJM cost "
         "data, 2022 dollars), not escalated. One binding element per case and no re-study after the upgrade, so "
         "each row is a first-step upgrade, not an interconnection plan. Generated by `bench/cost_study.py` from "
         "`results/capacity_case118.json`; full detail in `results/costs_case118.json`.", ""]
    for name in ("P1", "P1+P7"):
        R = [r for r in rows if r["set"] == name]
        need = [r for r in R if "full_cluster" in r]
        L += [f"## Contingency set {name}", "",
              f"{len(R)} clusters; {len(R) - len(need)} admit every request (no upgrade); {len(need)} leave "
              f"requests out. Best subsets re-checked secure: "
              f"{sum(r['best_subset_rechecked_secure'] for r in R)} of {len(R)}.", ""]
        for key, title in (("best_subset_plus_rest", "binding case when the rest is added on top of the best subset"),
                           ("full_cluster", "binding case of the full cluster")):
            cnt = {}
            for r in need:
                u = r[key]["upgrade"]["upgrade_class"] or "none (diverged)"
                cnt[u] = cnt.get(u, 0) + 1
            L += [f"### Upgrade class, {title}", "", "| upgrade class | clusters |", "|---|---|"]
            L += [f"| {k} | {v} |" for k, v in sorted(cnt.items(), key=lambda x: -x[1])]
            L += [""]
        L += ["### Per cluster (best subset + rest)", "",
              "| season | seed | rest MW (gen / load) | binding element | upgrade | cost $M (low / central / high) | "
              "$M per mile (low / central / high) | time yr (low-high) | LBNL complete $M | LBNL active $M |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in need:
            b = r["best_subset_plus_rest"]; e = b["element"]; u = b["upgrade"]
            if e["kind"] in ("line", "transformer"):
                desc = f"{e['kind']} {e['from_bus']}-{e['to_bus']}, {e['rating_mva']:.0f} MVA, needs {e['required_mva']:.0f}"
            elif e["kind"] == "diverged":
                desc = "diverged"
            else:
                desc = f"bus {e['bus']} {e['u_pu']:.3f} pu, {e['mvar'] if e['mvar'] is not None else 'n/a'} MVAr"
            ty = u["time_years"]
            lt = u.get("equipment_lead_time_years")
            tys = f"{ty[0]:.1f}-{ty[1]:.1f}" + (f" (+ lead {lt[0]:.1f}-{lt[1]:.1f})" if lt else "")
            L.append(f"| {r['season']} | {r['seed']} | {r['rest_gen_mw']:.0f} / {r['rest_load_mw']:.0f} | {desc} | "
                     f"{u['upgrade_class']} | {fmt_rng(u['cost_usd'])} | {fmt_rng(u['cost_usd_per_mile'], nd=2)} | {tys} | "
                     f"{fmt_rng(r['lbnl_per_kw']['complete']['cost_usd'])} | {fmt_rng(r['lbnl_per_kw']['active']['cost_usd'])} |")
        L += [""]
    L += ["## Notes", "",
          "- Time range: 25th to 75th percentile of PJM queue entry to commercial operation, requests entered "
          "2013-2017 (`pjm_queue_entry_to_cod_2013_2017`). It is whole-process time, the same for every upgrade "
          "class: no source read gives construction time per upgrade class. Transformers also show the 80 to 210 "
          "week equipment lead time (NIAC draft quoting Wood Mackenzie).",
          "- Line upgrades are reported per mile only (no lengths on the test grid).",
          "- LBNL columns: PJM network-upgrade cost per kW (25th / 50th / 75th percentile, projects studied "
          "2017-2022) times the generation MW left out; loads are not covered by that data.",
          "- Reconductor vs new line: reconductor when the MVA needed fits MISO's standard circuit for the voltage "
          "class (394 MVA at 138 kV, 1,792 MVA at 345 kV), otherwise new parallel circuits.", ""]
    open("RESULTS_COSTS.md", "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    main()
