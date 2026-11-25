"""Step 2 baselines on the clusters of results/capacity_<case>.json (same requests, seasons and contingency sets):
  - DC (linear) capacity of each request vs the AC capacity already computed: over- and under-estimates
  - the linear cluster pick (best DC subset, what a DFAX-style screen admits) and whether it is AC-secure
  - DC capacity at every bus vs the AC capacity map
Usage: python bench/cluster_baselines.py case118 [nproc] -> results/baselines_<case>.json"""
import json, os, sys, multiprocessing as mp
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7, dc
from gridengine.capacity import CapacityStudy

CASE = sys.argv[1]
NPROC = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 2)
R = json.load(open(f"results/capacity_{CASE}.json"))
_E = {}


def eng(season):
    if not _E:
        base = Engine(load_case(CASE))
        for s in SEASONS:
            _E[s] = Engine(apply_season(base.case, s))
    return _E[season]


def conts_for(E, name):
    return p1(E.branches) if name == "P1" else p1(E.branches) + p7(E.branches)


def cluster_job(c):
    E = eng(c["season"]); reqs = c["requests"]
    out = dict(seed=c["seed"], season=c["season"])
    for name in ("P1", "P1+P7"):
        cs = conts_for(E, name)
        dc_ind = [dc.capacity(E.case, r["bus"], r["kind"], cs, r["mw"]) for r in reqs]
        pick = dc.best_subset(E.case, reqs, cs)
        st = CapacityStudy(E, sorted(set(r["bus"] for r in reqs)))
        a = np.zeros(len(reqs)); a[pick["admitted"]] = 1
        ac_ok = st.secure(reqs, a, cs)[0] if pick["admitted"] else True
        out[name] = dict(dc_individual=dc_ind, ac_individual=[i["capacity_mw"] for i in c[name]["individual"]],
                         dc_pick=pick, dc_pick_ac_secure=bool(ac_ok), ac_best_mw=c[name]["cluster"]["mw"],
                         first_come_mw=c[name]["queue"]["mw"])
    return out


def map_job(m):
    E = eng(m["season"])
    res = {}
    for name, cs in (("N0", []), ("P1", p1(E.branches))):
        res[name] = dc.capacity(E.case, m["bus"], m["kind"], cs, R["map_cap_mw"])
    return dict(season=m["season"], bus=m["bus"], kind=m["kind"], dc=res, ac={k: m[k]["mw"] for k in ("N0", "P1")})


if __name__ == "__main__":
    with mp.get_context("spawn").Pool(NPROC) as p:
        maps = p.map(map_job, R["map"], chunksize=8)
        cls = p.map(cluster_job, R["clusters"], chunksize=1)
    json.dump(dict(case=CASE, map=maps, clusters=cls), open(f"results/baselines_{CASE}.json", "w"), indent=1)
    print("wrote")
