"""Contingency analysis benchmark: Power Grid Model batch vs a pandapower loop, same machine.
Usage: python bench/benchmark.py case118 [n_pandapower]  -> results/bench_<case>.json"""
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7, n2_sample
from gridengine.cases import DATA

name = sys.argv[1] if len(sys.argv) > 1 else "case118"
n_pp = int(sys.argv[2]) if len(sys.argv) > 2 else 40
out = dict(case=name)
t = time.perf_counter(); base = Engine(load_case(name)); out["build_seconds"] = time.perf_counter() - t
out["ratings"] = base.ratings
out["q_limits"] = base.q_limits
out["n_branches"] = len(base.branches)
sets = dict(P1=p1(base.branches), P7=p7(base.branches), N2=n2_sample(base.branches, n=300, seed=0))
out["seasons"] = {}
for season in SEASONS:
    eng = Engine(apply_season(base.case, season))
    rs = {}
    for k, conts in sets.items():
        if not conts:
            rs[k] = dict(n=0); continue
        r = eng.contingency_analysis(conts)
        ok = r["converged"]
        rs[k] = dict(n=r["n"], secure=int(r["secure"].sum()), converged=int(ok.sum()), seconds=r["seconds"],
                     ms_per_case=1000 * r["seconds"] / r["n"], overloaded_cases=int((r["max_loading"][ok] > 1).sum()),
                     low_voltage_cases=int((r["vmin"][ok] < 0.9).sum()), high_voltage_cases=int((r["vmax"][ok] > 1.1).sum()))
    out["seasons"][season] = rs

# pandapower loop on the first n_pp P1 outages (summer), for timing only
import pandapower as pp
from pandapower.converter.matpower import from_mpc
net = from_mpc(f"{DATA}/{name}.m", f_hz=60)
elems = [("line", i, int(r.from_bus), int(r.to_bus)) for i, r in net.line.iterrows()] + \
        [("trafo", i, int(r.hv_bus), int(r.lv_bus)) for i, r in net.trafo.iterrows()]
t = time.perf_counter(); k = 0
for tb, i, f, tt in elems[:n_pp]:
    net[tb].loc[i, "in_service"] = False
    try:
        pp.runpp(net, numba=False, init="flat", enforce_q_lims=False)
    except Exception:
        pass
    net[tb].loc[i, "in_service"] = True
    k += 1
out["pandapower_loop"] = dict(n=k, seconds=time.perf_counter() - t, ms_per_case=1000 * (time.perf_counter() - t) / max(k, 1),
                              note="pandapower without numba; Newton from flat start, no Q limits")
os.makedirs("results", exist_ok=True)
json.dump(out, open(f"results/bench_{name}.json", "w"), indent=1)
print(json.dumps(out, indent=1))
