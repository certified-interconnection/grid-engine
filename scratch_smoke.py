import numpy as np
import pandapower as pp
import pandapower.networks as pn

import gridengine as ge

for name, fn in [("case30", pn.case30), ("case118", pn.case118)]:
    case = ge.load_case(name)
    print("=====", name, case.describe())
    res = ge.run_power_flow(case)
    net = fn()
    pp.runpp(net, calculate_voltage_angles=True, tolerance_mva=1e-9, max_iteration=100)
    dv = np.abs(res.vm - net.res_bus.vm_pu.values)
    print("max |dV| vs pandapower:", dv.max(), "at bus", int(np.argmax(dv)), "converged", res.converged)
    print("pgm vm range:", res.vm.min(), res.vm.max(), "pp:", net.res_bus.vm_pu.min(), net.res_bus.vm_pu.max())
    print("max loading pgm:", res.max_loading, "pp line/trafo loading max:",
          max(net.res_line.loading_percent.max() / 100, net.res_trafo.loading_percent.max() / 100 if len(net.trafo) else 0))
    sets = ge.build_sets(case)
    print("sets:", {k: len(v) for k, v in sets.items()})
    p1 = sets["P1"][:5]
    batch = ge.run_contingencies(case, p1)
    for k, cont in enumerate(p1):
        net2 = fn()
        for bid in cont.branch_ids:
            br = case.branch_map()[bid]
            net2[br.table].at[br.index, "in_service"] = False
        pp.runpp(net2, calculate_voltage_angles=True, tolerance_mva=1e-9, max_iteration=100)
        print("  ", cont.id, "max dV:", np.abs(batch.vm[k] - net2.res_bus.vm_pu.values).max(),
              "secure:", bool(batch.secure[k]), "maxloading:", batch.max_loading[k])
    sc = ge.run_short_circuit(case)
    print("SC: max", sc.max_current_ka, "kA at bus", sc.max_bus, "n buses", len(sc.i_f_ka))
    slack_bus = case.sources[0].bus
    print("SC at slack bus:", sc.i_f_ka[case.bus_map()[slack_bus].id - 1] if False else sc.i_f_ka[list(sc.bus_ids).index(slack_bus)],
          "theoretical:", ge.shortcircuit.theoretical_slack_current_ka(sc.sk_mva, case.bus_map()[slack_bus].vn_kv))
    print("SC all finite/positive:", bool(np.isfinite(sc.i_f_ka).all()), bool((sc.i_f_ka > 0).all()))
