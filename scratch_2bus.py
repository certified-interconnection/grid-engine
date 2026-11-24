import numpy as np, math
import pandapower as pp
from power_grid_model import initialize_array, PowerGridModel, LoadGenType

def build(q_mvar, p_mw=0.0, vn=138.0):
    node = initialize_array("input","node",2); node["id"]=[1,2]; node["u_rated"]=[vn*1e3]*2
    line = initialize_array("input","line",1)
    line["id"]=[3]; line["from_node"]=[1]; line["to_node"]=[2]
    line["from_status"]=[1]; line["to_status"]=[1]
    line["r1"]=[1.0]; line["x1"]=[10.0]; line["c1"]=[0.0]; line["tan1"]=[0.0]; line["i_n"]=[1000.0]
    load = initialize_array("input","sym_load",1)
    load["id"]=[4]; load["node"]=[2]; load["status"]=[1]; load["type"]=[LoadGenType.const_power]
    load["p_specified"]=[50e6]; load["q_specified"]=[10e6]
    shunt = initialize_array("input","shunt",1)
    shunt["id"]=[5]; shunt["node"]=[2]; shunt["status"]=[1]
    shunt["g1"]=[p_mw*1e6/(vn*1e3)**2]; shunt["b1"]=[-q_mvar*1e6/(vn*1e3)**2]
    src = initialize_array("input","source",1)
    src["id"]=[6]; src["node"]=[1]; src["status"]=[1]; src["u_ref"]=[1.0]; src["u_ref_angle"]=[0.0]
    src["sk"]=[1e18]; src["rx_ratio"]=[0.1]; src["z01_ratio"]=[1.0]
    return {"node":node,"line":line,"sym_load":load,"shunt":shunt,"source":src}

for q in [0.0, 4.0, 40.0, -40.0]:
    m = PowerGridModel(build(q))
    try:
        r = m.calculate_power_flow(error_tolerance=1e-8, max_iterations=100)
        vm = r["node"]["u_pu"]
    except Exception as e:
        vm = str(e).splitlines()[0][:50]
    net = pp.create_empty_network(sn_mva=100, f_hz=50)
    b1 = pp.create_bus(net, vn_kv=138); b2 = pp.create_bus(net, vn_kv=138)
    pp.create_line_from_parameters(net, b1, b2, 1.0, 1.0, 10.0, 0.0, 1000.0)
    pp.create_load(net, b2, 50, 10)
    pp.create_shunt(net, b2, q_mvar=q, p_mw=0)
    pp.create_ext_grid(net, b1, vm_pu=1.0)
    pp.runpp(net, tolerance_mva=1e-10)
    print("q", q, "pgm:", vm, "pp:", net.res_bus.vm_pu.values, "pp shunt p/q:", net.res_shunt[["p_mw","q_mvar"]].values)
