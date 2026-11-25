"""Step 1 validation and baseline, one grid per run.

(A) Independent-solver check: Power Grid Model (grid-engine) vs pandapower on the base case and on EVERY single-branch
    outage that maps to exactly one pandapower element (parallel branches are ambiguous and skipped, and counted),
    summer peak. Per outage: do both converge, and max |V| and angle differences.
(B) Linear baseline: DC security (thermal only, as DC has no voltage) vs AC security, every season x {P1, P7, N2(300)}.
    Confusion counts, with the dangerous cell first: DC says secure but AC is not. AC insecurity is split into thermal,
    voltage and divergence. Also the error in the worst-branch loading, DC minus AC, per contingency.
Usage: python bench/validate.py <case> [n_pandapower_max] -> results/validate_<case>.json
"""
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case, apply_season, SEASONS, p1, p7, n2_sample, dc
from gridengine.cases import DATA

CASE = sys.argv[1]
NPP = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
out = dict(case=CASE)
base = Engine(load_case(CASE))
out["ratings"] = base.ratings
sets = dict(P1=p1(base.branches), P7=p7(base.branches), N2=n2_sample(base.branches, n=300, seed=0))
out["set_sizes"] = {k: len(v) for k, v in sets.items()}


def q(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return {p: float(np.quantile(x, p)) for p in (0.5, 0.9, 0.99, 1.0)} if len(x) else None


# ---------------- (A) pandapower cross-check
import pandapower as pp
from pandapower.converter.matpower import from_mpc
t0 = time.time()
summer = Engine(apply_season(base.case, "summer_peak"))
net0 = from_mpc(f"{DATA}/{CASE}.m", f_hz=60)
pp.runpp(net0, numba=False, init="flat", enforce_q_lims=False, tolerance_mva=1e-9)
o = summer.model.calculate_power_flow(calculation_initialization=summer.init, error_tolerance=1e-10, max_iterations=30)
A = dict(base_max_dv=float(np.abs(o["node"]["u_pu"] - net0.res_bus.vm_pu.values).max()),
         base_max_dangle_deg=float(np.abs(np.rad2deg(o["node"]["u_angle"]) - (net0.res_bus.va_degree.values - net0.res_bus.va_degree.values[summer.input["source"]["node"][0]])).max()))
elems = {}
for i, r in net0.line.iterrows():
    elems.setdefault(frozenset((int(r.from_bus), int(r.to_bus))), []).append(("line", i))
for i, r in net0.trafo.iterrows():
    elems.setdefault(frozenset((int(r.hv_bus), int(r.lv_bus))), []).append(("trafo", i))
conts = sets["P1"][:NPP]
res = summer.model.calculate_power_flow(update_data=summer._update(conts), calculation_initialization=summer.init,
                                        error_tolerance=1e-10, max_iterations=30, continue_on_batch_error=True)
dv, da, both, pgm_only, pp_only, neither, skipped = [], [], 0, 0, 0, 0, 0
for s, c in enumerate(conts):
    b = summer.branches[c[0]]
    hit = elems.get(frozenset((b["f"], b["t"])), [])
    if len(hit) != 1:
        skipped += 1; continue
    tb, i = hit[0]
    net = net0.deepcopy() if hasattr(net0, "deepcopy") else __import__("copy").deepcopy(net0)
    net[tb].loc[i, "in_service"] = False
    try:
        pp.runpp(net, numba=False, init="flat", enforce_q_lims=False, tolerance_mva=1e-9, max_iteration=30)
        ok_pp = True
    except Exception:
        ok_pp = False
    u = res["node"]["u_pu"][s]
    ok_pgm = bool(np.isfinite(u).all() and (u > 0).all())
    if ok_pgm and ok_pp:
        both += 1
        dv.append(float(np.abs(u - net.res_bus.vm_pu.values).max()))
        ref = summer.input["source"]["node"][0]
        da.append(float(np.abs(np.rad2deg(res["node"]["u_angle"][s]) - (net.res_bus.va_degree.values - net.res_bus.va_degree.values[ref])).max()))
    elif ok_pgm:
        pgm_only += 1
    elif ok_pp:
        pp_only += 1
    else:
        neither += 1
A.update(n_outages=len(conts), compared=both, skipped_parallel=skipped, converged_pgm_only=pgm_only,
         converged_pandapower_only=pp_only, converged_neither=neither, max_dv_quantiles=q(dv), max_dangle_deg_quantiles=q(da),
         seconds=time.time() - t0)
out["A_pandapower"] = A
print("A", json.dumps(A), flush=True)

# ---------------- (B) DC vs AC
B = {}
for season in SEASONS:
    eng = Engine(apply_season(base.case, season))
    B[season] = {}
    for name, cs in sets.items():
        if not cs:
            continue
        ac = eng.contingency_analysis(cs)
        d = dc.security(eng.case, cs)
        conv = ac["converged"]
        ac_th = conv & (ac["max_loading"] <= 1 + 1e-9)
        ac_full = ac["secure"]
        dcs = d["secure"]
        B[season][name] = dict(
            n=len(cs), ac_secure=int(ac_full.sum()), dc_secure=int(dcs.sum()),
            dc_secure_ac_insecure=int((dcs & ~ac_full).sum()),
            dc_secure_ac_insecure_by_reason=dict(thermal=int((dcs & conv & ~ac_th).sum()),
                                                 voltage_only=int((dcs & ac_th & ~ac_full).sum()),
                                                 diverged=int((dcs & ~conv).sum())),
            dc_insecure_ac_secure=int((~dcs & ac_full).sum()),
            agree=int((dcs == ac_full).sum()),
            thermal_only=dict(dc_secure_ac_overload=int((dcs & conv & ~ac_th).sum()), dc_overload_ac_within=int((~dcs & ac_th).sum())),
            worst_loading_error_dc_minus_ac=q((d["max_loading"] - ac["max_loading"])[conv]),
            worst_loading_abs_error=q(np.abs(d["max_loading"] - ac["max_loading"])[conv]))
        print(season, name, B[season][name]["dc_secure_ac_insecure"], "of", len(cs), flush=True)
out["B_dc_vs_ac"] = B
os.makedirs("results", exist_ok=True)
json.dump(out, open(f"results/validate_{CASE}.json", "w"), indent=1)
print("wrote")
