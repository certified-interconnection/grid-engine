"""Step 3: ways to make room. For every cluster in results/capacity_<case>.json (same requests, seasons and P1 set),
the plain best subset and each option (gridengine/options.py): flexible loads keep 0.5 and 0.0, storage 25% and 50%
of each load, generation on a remedial action scheme keep 0.0, the best single switch, partial MW.
Usage: python bench/options_study.py case118 [nproc] [first] [count] -> results/options_<case>.json"""
import json, os, sys, time, multiprocessing as mp
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1
from gridengine.options import OptionsStudy

CASE = sys.argv[1] if len(sys.argv) > 1 else "case118"
NPROC = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 2)
FIRST = int(sys.argv[3]) if len(sys.argv) > 3 else 0
COUNT = int(sys.argv[4]) if len(sys.argv) > 4 else None
OPTIONS = ["flex_load_50", "flex_load_0", "storage_25", "storage_50", "ras_gen_0", "switch", "partial"]
_E = {}


def engines():
    if not _E:
        base = Engine(load_case(CASE))      # same construction as bench/capacity_study.py
        _E["base"] = base
        for s in SEASONS:
            _E[s] = Engine(apply_season(base.case, s))
    return _E


def job(c):
    t0 = time.time()
    E = engines()[c["season"]]
    o = OptionsStudy(E, c["requests"], p1(E.branches))
    rec = o.record()
    rec.update(seed=c["seed"], season=c["season"], center=c["center"], requests=c["requests"],
               plain_mw_step2=float(c["P1"]["cluster"]["mw"]), seconds=time.time() - t0)
    print(c["season"], c["seed"], "plain", rec["plain"]["mw"], {k: round(v["gain_mw"], 1) for k, v in rec["options"].items()},
          round(rec["seconds"]), flush=True)
    return rec


def summarize(recs):
    s = dict(n_clusters=len(recs), n_not_fit=int(sum(not r["fits"] for r in recs)),
             plain_mw=float(sum(r["plain"]["mw"] for r in recs)), requested_mw=float(sum(r["total_mw"] for r in recs)),
             plain_matches_step2=int(sum(abs(r["plain"]["mw"] - r["plain_mw_step2"]) < 1e-6 for r in recs)),
             all_rechecks_pass=bool(all(r["plain"]["recheck"] and all(v["recheck"] for v in r["options"].values())
                                        for r in recs)),
             options={})
    nf = [r for r in recs if not r["fits"]]
    for k in OPTIONS:
        g = np.array([r["options"][k]["gain_mw"] for r in recs])
        gnf = np.array([r["options"][k]["gain_mw"] for r in nf]) if nf else np.zeros(0)
        s["options"][k] = dict(total_mw=float(sum(r["options"][k]["mw"] for r in recs)), gain_mw=float(g.sum()),
                               clusters_with_gain=int((g > 1e-6).sum()), share_all=float((g > 1e-6).mean()),
                               share_not_fit=float((gnf > 1e-6).mean()) if len(gnf) else 0.0,
                               rechecks_failed=int(sum(not r["options"][k]["recheck"] for r in recs)),
                               below_plain=int((g < -1e-6).sum()))
    s["clusters_with_loads_not_fit"] = int(sum(any(q["kind"] == "load" for q in r["requests"]) for r in nf))
    return s


def main():
    t0 = time.time()
    cap = json.load(open(f"results/capacity_{CASE}.json"))
    clusters = cap["clusters"][FIRST:None if COUNT is None else FIRST + COUNT]
    E = engines()
    with mp.get_context("spawn").Pool(NPROC) as p:
        recs = p.map(job, clusters, chunksize=1)
    out = dict(case=CASE, contingencies="P1", ratings=E["base"].ratings, q_limits=E["base"].q_limits,
               source=f"results/capacity_{CASE}.json", options=OPTIONS, clusters=recs, summary=summarize(recs),
               nproc=NPROC, wall_seconds=time.time() - t0)
    os.makedirs("results", exist_ok=True)
    name = f"results/options_{CASE}.json" if COUNT is None and FIRST == 0 else f"results/options_{CASE}_{FIRST}_{COUNT}.json"
    json.dump(out, open(name, "w"), indent=1, default=float)
    print("wrote", name, time.time() - t0, flush=True)


if __name__ == "__main__":
    main()
