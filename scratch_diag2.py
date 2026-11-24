from dataclasses import replace
import numpy as np
import pandapower as pp
import pandapower.networks as pn
import gridengine as ge
from gridengine import pgm as gpm

case = ge.load_case("case118")
net = pn.case118()

def pp_solve(shunt_ids=None, off=False):
    net2 = pn.case118()
    if off:
        net2.shunt["in_service"] = False
    else:
        keep = set()
        for s in case.shunts:
            if s.table == "shunt" and (shunt_ids is None or s.index in shunt_ids):
                keep.add(s.index)
        net2.shunt["in_service"] = [i in keep for i in net2.shunt.index]
    pp.runpp(net2, calculate_voltage_angles=True, tolerance_mva=1e-9, max_iteration=100)
    return net2

# 1. no shunts: PGM vs pp
no_sh = replace(case, shunts=[])
r = ge.run_power_flow(no_sh)
nets = pp_solve(off=True)
print("no-shunt max dV vs pp(no shunt):", np.abs(r.vm - nets.res_bus.vm_pu.values).max())
print("pgm vm at buses 5,37,65:", r.vm[[4,36,64]], "pp:", nets.res_bus.vm_pu.values[[4,36,64]])
print("min vm bus:", int(np.argmin(r.vm)), r.vm.min())

# 2. only shunt at bus 5 (index 0) in both
for q, idx in [(40.0, 0), (20.0, 0), (40.0, 2)]:
    sv = [replace(case.shunts[0], q_mvar=q)] if idx == 0 else [replace(case.shunts[2], q_mvar=q)]
    c = replace(case, shunts=sv)
    try:
        rr = ge.run_power_flow(c)
        pgmvm = rr.vm
        ok = "ok"
    except Exception as e:
        pgmvm = None
        ok = "FAIL " + str(e).splitlines()[0][:40]
    netq = pp_solve(shunt_ids={idx})
    print("q", q, "shunt index", idx, ok, "pp vm at bus:", netq.res_bus.vm_pu.values[[4 if idx==0 else 36]] if pgmvm is None else np.abs(pgmvm - netq.res_bus.vm_pu.values).max())

# 3. print shunt arrays as fed to pgm
mi = gpm.build_input(case)
print("shunt input g1,b1:", mi.data["shunt"]["g1"][:5], mi.data["shunt"]["b1"][:5])
print("node u_rated of that node:", mi.data["node"]["u_rated"][4])
print("shunt nodes:", mi.data["shunt"]["node"][:5])
