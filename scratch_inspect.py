import power_grid_model as pgm
from power_grid_model import ComponentType
print("ComponentType:", [c.value for c in ComponentType])
import pandapower.networks as pn
for name in ["case30", "case118", "case300", "case_illinois200"]:
    net = getattr(pn, name)()
    print("=====", name, "buses", len(net.bus))
    for t in ["line", "trafo", "trafo3w", "gen", "sgen", "load", "shunt", "ext_grid", "ward", "xward", "impedance", "dcline"]:
        if t in net and len(net[t]):
            print("  ", t, len(net[t]), list(net[t].columns))
    print("  line max_i_ka sample:", net.line.max_i_ka.head(3).tolist() if "line" in net else None)
    print("  bus vn_kv sample:", net.bus.vn_kv.head(3).tolist())
