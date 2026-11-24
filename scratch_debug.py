import numpy as np
import pandapower as pp
import pandapower.networks as pn
from dataclasses import replace

import gridengine as ge
from gridengine import pgm as gpm

case = ge.load_case("case30")
net = pn.case30()
pp.runpp(net, calculate_voltage_angles=True, tolerance_mva=1e-9, max_iteration=100)
ppvm = net.res_bus.vm_pu.values

res = ge.run_power_flow(case)
print("pgm[0], pp[0]:", res.vm[0], ppvm[0])
print("bus0 id/vn:", case.buses[0])
print("bus 1 vs 2:", res.vm[1], ppvm[1], res.vm[2], ppvm[2])

# A: source sk influence on power flow
mi = gpm.build_input(case, sk_mva=1e9)
m = gpm.make_model(mi, case.freq_hz)
r = m.calculate_power_flow()
print("sk=1e9 vm[0:3]:", r["node"]["u_pu"][:3])
mi2 = gpm.build_input(case, sk_mva=1e6)
m2 = gpm.make_model(mi2, case.freq_hz)
r2 = m2.calculate_power_flow()
print("sk=1MVA vm[0:3]:", r2["node"]["u_pu"][:3])

# C: shunt sign flip
case_b = replace(case, shunts=[replace(s, q_mvar=-s.q_mvar) for s in case.shunts])
res_b = ge.run_power_flow(case_b)
print("flipped shunt max dV:", np.abs(res_b.vm - ppvm).max())
print("orig shunt max dV:", np.abs(res.vm - ppvm).max())
print("shunts:", case.shunts)

# D: single contingency by building input with branch status 0
br = case.branch_map()[31]
print("branch 31:", br)
case_c = replace(case, branches=[replace(b, in_service=False) if b.id == 31 else b for b in case.branches])
res_c = ge.run_power_flow(case_c)
net2 = pn.case30()
net2.line.at[br.index, "in_service"] = False
pp.runpp(net2, calculate_voltage_angles=True, tolerance_mva=1e-9, max_iteration=100)
print("single-outage PGM vs pp max dV:", np.abs(res_c.vm - net2.res_bus.vm_pu.values).max())
print("pgm vm:", res_c.vm[:6], "pp vm:", net2.res_bus.vm_pu.values[:6])

batch = ge.run_contingencies(case, ge.p1(case)[:1])
print("batch vm[0:6]:", batch.vm[0][:6], "secure", batch.secure)
print("batch vs single:", np.abs(batch.vm[0] - res_c.vm).max())
print("batch loading vs single loading:", np.abs(batch.loading[0] - res_c.loading).max())
print("batch loading[:5]:", batch.loading[0][:5], "single:", res_c.loading[:5])
