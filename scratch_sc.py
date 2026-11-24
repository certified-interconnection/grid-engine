import numpy as np
import gridengine as ge
for name in ["case30", "case118"]:
    case = ge.load_case(name)
    sc = ge.run_short_circuit(case)
    print("=====", name, "shape", sc.i_f_ka.shape, "dtype", sc.i_f_ka.dtype)
    print("max kA:", sc.max_current_ka, "at bus", sc.max_bus, "min kA:", sc.i_f_ka.min())
    slack = case.sources[0].bus
    vn = case.bus_map()[slack].vn_kv
    idx = list(sc.bus_ids).index(slack)
    print("slack bus i_f:", sc.i_f_ka[idx], "theory sk/(sqrt3 Un):", ge.shortcircuit.theoretical_slack_current_ka(sc.sk_mva, vn))
    sc2 = ge.run_short_circuit(case, sk_mva=2000.0)
    print("2x sk:", sc2.i_f_ka[idx], "ratio:", sc2.i_f_ka[idx] / sc.i_f_ka[idx])
    print("finite:", bool(np.isfinite(sc.i_f_ka).all()), "all>0:", bool((sc.i_f_ka > 0).all()))
