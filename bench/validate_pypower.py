"""Independent-solver check against PYPOWER (a port of MATPOWER's own Newton-Raphson), on every outage.

For each season and each contingency set (P1, P7, N2 sample), solve the same case in grid-engine (Power Grid Model,
batch) and in PYPOWER (one runpf per case, reactive limits off, tolerance 1e-10), then compare bus voltage magnitudes
and angles. PYPOWER reads the same MATPOWER arrays, so the two share the input file and nothing else.
(pandapower's MATPOWER converter disagrees with both on IEEE 300 and Texas 2,000 in the base case, so it is not used
as the referee; see results/validate_<case>.json part A for the grids where it agrees.)
Usage: python bench/validate_pypower.py <case> -> results/validate_pypower_<case>.json"""
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7, n2_sample
from pypower.api import runpf, ppoption
from gridengine.qlim_ref import solve_qlim
QLIM = os.environ.get("GE_QLIM") == "1"   # then the reference is MATPOWER's reactive-limit outer loop (qlim_ref)

CASE = sys.argv[1]
OPT = ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, ENFORCE_Q_LIMS=0, PF_MAX_IT=30)
base = Engine(load_case(CASE))
sets = dict(P1=p1(base.branches), P7=p7(base.branches), N2=n2_sample(base.branches, n=300, seed=0))
on = np.nonzero(base.case["branch"][:, 10] > 0)[0]      # engine branch k <-> case branch row on[k]


def q(x):
    x = np.asarray(x, float)
    return {p: float(np.quantile(x, p)) for p in (0.5, 0.9, 0.99, 1.0)} if len(x) else None


out = dict(case=CASE, ratings=base.ratings, q_limits=base.q_limits, seasons={})
t0 = time.time()
for season in SEASONS:
    eng = Engine(apply_season(base.case, season))
    c = eng.case
    ref = int(np.nonzero(c["bus"][:, 1] == 3)[0][0])
    out["seasons"][season] = {}
    for name, conts in [("base", [()])] + list(sets.items()):
        if not conts:
            continue
        if name == "base":
            o, _ = eng.run(tol=1e-10)
        else:
            o, _ = eng.run(update=eng._update(conts), n=len(conts), tol=1e-10)
        U = o["node"]["u_pu"]; A = o["node"]["u_angle"]
        dv, da, both, pgm_only, pyp_only, neither = [], [], 0, 0, 0, 0
        for s, cont in enumerate(conts):
            ppc = dict(version="2", baseMVA=c["baseMVA"], bus=c["bus"].copy(), gen=c["gen"].copy(), branch=c["branch"].copy())
            ppc["bus"][:, 0] += 1; ppc["gen"][:, 0] += 1; ppc["branch"][:, 0] += 1; ppc["branch"][:, 1] += 1
            for bi in cont:
                ppc["branch"][on[bi], 10] = 0
            try:
                if QLIM:
                    vref, ok = solve_qlim(c, out_branches=[on[bi] for bi in cont])
                    r = None
                else:
                    r, ok = runpf(ppc, OPT)
            except Exception:
                ok = 0
            u = U[s]
            ok_pgm = bool(np.isfinite(u).all() and (u > 0.3).all())
            if ok and ok_pgm:
                both += 1
                if QLIM:
                    dv.append(float(np.abs(vref - u).max()))
                else:
                    dv.append(float(np.abs(r["bus"][:, 7] - u).max()))
                    da.append(float(np.abs(r["bus"][:, 8] - r["bus"][ref, 8] - np.rad2deg(A[s])).max()))
            elif ok_pgm:
                pgm_only += 1
            elif ok:
                pyp_only += 1
            else:
                neither += 1
        out["seasons"][season][name] = dict(n=len(conts), compared=both, converged_pgm_only=pgm_only,
                                            converged_pypower_only=pyp_only, converged_neither=neither,
                                            max_dv=q(dv), max_dangle_deg=q(da))
        print(season, name, out["seasons"][season][name]["compared"], "of", len(conts),
              "max dV", out["seasons"][season][name]["max_dv"] and out["seasons"][season][name]["max_dv"][1.0], flush=True)
out["seconds"] = time.time() - t0
os.makedirs("results", exist_ok=True)
json.dump(out, open(f"results/validate_pypower_{CASE}{'_qlim' if QLIM else ''}.json", "w"), indent=1)
print("wrote")
