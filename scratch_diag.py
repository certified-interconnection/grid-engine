import math
from dataclasses import replace

import numpy as np
import pandapower as pp
import pandapower.networks as pn
from power_grid_model import PowerGridModel
from power_grid_model.validation import validate_input_data

import gridengine as ge
from gridengine import pgm as gpm

case = ge.load_case("case118")


def run(c, label, **kw):
    try:
        r = ge.run_power_flow(c, **kw)
        print(label, "OK vm range", round(float(r.vm.min()), 4), round(float(r.vm.max()), 4),
              "max loading", round(r.max_loading, 4))
        return r
    except Exception as e:
        print(label, "FAIL", type(e).__name__, str(e).splitlines()[0][:120])
        return None


mi = gpm.build_input(case)
errs = validate_input_data(mi.data, symmetric=True)
print("validation errors:", len(errs) if errs else errs)
for e in (errs or [])[:10]:
    print("  ", e)

run(case, "base")

# (a) no voltage regulation
no_vr = replace(case, generators=[replace(g, vm_pu=None, q_mvar=0.0) for g in case.generators])
run(no_vr, "no VR")

# (b) trafos as generic branches (r/x from uk/pk on sn base, referred to hv)
def trafo_to_gb(b):
    z_base = b.u1_kv**2 / b.sn_mva
    z = b.vk_percent / 100.0 * z_base
    r = b.vkr_percent / 100.0 * z_base
    x = math.sqrt(max(z * z - r * r, 0.0))
    return replace(b, kind="generic_branch", r_ohm=r, x_ohm=x, b_siemens=0.0,
                   tap_ratio=b.u1_kv / b.u2_kv * (case.bus_map()[b.to_bus].vn_kv / case.bus_map()[b.from_bus].vn_kv),
                   rate_mva=b.sn_mva, shift_degree=b.shift_degree)

case_gb = replace(case, branches=[trafo_to_gb(b) if b.kind == "transformer" else b for b in case.branches])
run(case_gb, "trafos as generic_branch")

# (c) no shunts
run(replace(case, shunts=[]), "no shunts")

# (d) no generators at all
run(replace(case, generators=[]), "no gens")

# (e) iterative current
try:
    mi = gpm.build_input(case)
    m = PowerGridModel(mi.data, system_frequency=case.freq_hz)
    r = m.calculate_power_flow(calculation_method="iterative_current", error_tolerance=1e-8, max_iterations=200)
    print("iterative_current OK", r["node"]["u_pu"].min(), r["node"]["u_pu"].max())
except Exception as e:
    print("iterative_current FAIL", type(e).__name__, str(e).splitlines()[0][:120])

# compare trafo pu impedances to pandapower's
net = pn.case118()
print(net.trafo[["vk_percent", "vkr_percent", "sn_mva", "vn_hv_kv", "vn_lv_kv"]].head(3))
print("my trafos:", [(round(b.u1_kv, 2), round(b.u2_kv, 2), round(b.vk_percent, 2), round(b.sn_mva, 1)) for b in case.branches if b.kind == "transformer"][:3])
print("gens:", len(case.generators), "sources:", case.sources)
