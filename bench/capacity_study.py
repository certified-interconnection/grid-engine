"""Capacity study on one grid: (A) hosting-capacity map for new generation and new load at every bus, per season,
with no outages (N-0) and under every single outage (P1); (B) clusters of nearby requests per season: each request
alone, the cluster scaled together, the best all-or-nothing subset (exact cluster decision), largest-first admission
and first-come admission (random queue order). Violations that exist before any request is added are not charged
to the requests (see CapacityStudy._ok), under P1 and under P1 + P7.
Usage: python bench/capacity_study.py case118 [n_clusters] [nproc] -> results/capacity_<case>.json"""
import json, os, sys, time, multiprocessing as mp
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7
from gridengine.capacity import CapacityStudy
import networkx as nx

CASE = sys.argv[1] if len(sys.argv) > 1 else "case118"
NCL = int(sys.argv[2]) if len(sys.argv) > 2 else 30
NPROC = int(sys.argv[3]) if len(sys.argv) > 3 else (os.cpu_count() or 2)
_E = {}


def engines():
    if not _E:
        base = Engine(load_case(CASE))
        _E["base"] = base
        for s in SEASONS:
            _E[s] = Engine(apply_season(base.case, s))
    return _E


def map_job(a):
    season, bus, kind, mw_max = a
    E = engines()[season]
    cs = CapacityStudy(E, [bus])
    out = {}
    for name, conts in (("N0", []), ("P1", p1(E.branches))):
        c = cs.capacity([dict(bus=bus, mw=mw_max, kind=kind)], conts, tol=0.02)
        out[name] = dict(mw=c["mw"], capped=bool(c.get("censored")), binding=c["binding"])
    return dict(season=season, bus=bus, kind=kind, **out)


def cluster_job(a):
    seed, season = a
    E = engines()[season]
    rng = np.random.default_rng(1000 + seed)
    G = nx.Graph([(b["f"], b["t"]) for b in E.branches])
    center = int(rng.choice(list(G.nodes)))
    near = sorted(nx.single_source_shortest_path_length(G, center, cutoff=2))
    K = int(rng.integers(5, 9))
    buses = rng.choice(near, size=min(K, len(near)), replace=len(near) < K)
    total_load = E.case["bus"][:, 2].sum()
    reqs = []
    for b in buses:
        kind = "load" if rng.random() < 0.3 else "gen"     # about 30% large loads (data centers), 70% generation
        mw = float(np.clip(rng.lognormal(np.log(0.02 * total_load), 0.6), 5, 0.08 * total_load))
        reqs.append(dict(bus=int(b), mw=round(mw, 1), kind=kind))
    cs = CapacityStudy(E, sorted(set(int(b) for b in buses)))
    res = dict(seed=seed, season=season, center=center, requests=reqs)
    for name, conts in (("P1", p1(E.branches)), ("P1+P7", p1(E.branches) + p7(E.branches))):
        ind = cs.individual(reqs, conts)
        jt = cs.joint(reqs, conts)
        cl = cs.best_subset(reqs, conts)
        lf = cs.admit(reqs, conts)
        q = cs.admit(reqs, conts, order=list(rng.permutation(len(reqs))))
        res[name] = dict(individual=ind, joint_mw=jt["mw"], joint_t=jt["t"], joint_binding=jt["binding"],
                         cluster=cl, largest_first=lf, queue=q, sum_individual_mw=float(sum(i["capacity_mw"] for i in ind)),
                         fits_alone_mw=float(sum(r["mw"] for r, i in zip(reqs, ind) if i["fits"])))
    res["solves"] = cs.solves
    return res


def main():
    t0 = time.time()
    E = engines(); nb = E["base"].case["bus"].shape[0]
    total_load = E["base"].case["bus"][:, 2].sum()
    mw_max = round(0.15 * total_load, -1)
    out = dict(case=CASE, n_bus=nb, total_load_mw=float(total_load), map_cap_mw=mw_max, ratings=E["base"].ratings, q_limits=E["base"].q_limits,
               balance="new generation displaces existing generators pro rata; new load served pro rata")
    jobs = [(s, b, k, mw_max) for s in SEASONS for k in ("gen", "load") for b in range(nb)]
    with mp.get_context("spawn").Pool(NPROC) as p:
        out["map"] = p.map(map_job, jobs, chunksize=4)
        print("map done", time.time() - t0, flush=True)
        out["clusters"] = p.map(cluster_job, [(i, s) for s in SEASONS for i in range(NCL)], chunksize=1)
    out["wall_seconds"] = time.time() - t0
    os.makedirs("results", exist_ok=True)
    json.dump(out, open(f"results/capacity_{CASE}.json", "w"), indent=1, default=float)
    print("wrote", time.time() - t0)


if __name__ == "__main__":
    main()
