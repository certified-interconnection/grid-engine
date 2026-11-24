import numpy as np
import power_grid_model as pgm
from power_grid_model import initialize_array, PowerGridModel, LoadGenType, BranchSide, FaultType, CalculationMethod

for comp in ["line", "transformer", "generic_branch", "sym_gen", "fault", "source"]:
    try:
        a = initialize_array("sym_output", comp, 1)
        print("sym_output", comp, "->", a.dtype.names)
    except Exception as e:
        print("sym_output", comp, "ERR", e)
for comp in ["fault", "node"]:
    for kind in ["sym_sc_output", "asym_sc_output"]:
        try:
            a = initialize_array(kind, comp, 1)
            print(kind, comp, "->", a.dtype.names)
        except Exception as e:
            print(kind, comp, "ERR", e)
a = initialize_array("update", "line", 1)
print("update line ->", a.dtype.names)
a = initialize_array("update", "transformer", 1)
print("update transformer ->", a.dtype.names)
a = initialize_array("update", "fault", 1)
print("update fault ->", a.dtype.names)
print("BranchSide:", [b.name for b in BranchSide])
print("methods:", [m.name for m in CalculationMethod])
print("SC types:", [s.name for s in FaultType])
print("LoadGenType:", [l.name for l in LoadGenType])

# prototype: 2 bus, 1 line, source at bus1, gen+regulator at bus2
node = initialize_array("input", "node", 2)
node["id"] = [1, 2]; node["u_rated"] = [110e3, 110e3]
line = initialize_array("input", "line", 1)
line["id"] = [3]; line["from_node"] = [1]; line["to_node"] = [2]
line["from_status"] = [1]; line["to_status"] = [1]
line["r1"] = [1.0]; line["x1"] = [10.0]; line["c1"] = [0.0]; line["tan1"] = [0.0]; line["i_n"] = [500.0]
load = initialize_array("input", "sym_load", 1)
load["id"] = [4]; load["node"] = [2]; load["status"] = [1]
load["type"] = [LoadGenType.const_power]; load["p_specified"] = [20e6]; load["q_specified"] = [5e6]
gen = initialize_array("input", "sym_gen", 1)
gen["id"] = [5]; gen["node"] = [2]; gen["status"] = [1]
gen["type"] = [LoadGenType.const_power]; gen["p_specified"] = [10e6]; gen["q_specified"] = [0.0]
vr = initialize_array("input", "voltage_regulator", 1)
vr["id"] = [6]; vr["regulated_object"] = [5]; vr["status"] = [1]
vr["u_ref"] = [1.02]; vr["q_min"] = [-100e6]; vr["q_max"] = [100e6]
src = initialize_array("input", "source", 1)
src["id"] = [7]; src["node"] = [1]; src["status"] = [1]
src["u_ref"] = [1.0]; src["u_ref_angle"] = [0.0]; src["sk"] = [2000e6]; src["rx_ratio"] = [0.1]; src["z01_ratio"] = [1.0]
data = {"node": node, "line": line, "sym_load": load, "sym_gen": gen,
        "voltage_regulator": vr, "source": src}
from power_grid_model.validation import validate_input_data


model = PowerGridModel(data)
res = model.calculate_power_flow(calculation_method="newton_raphson", error_tolerance=1e-8, max_iterations=50)
print("node u_pu:", res["node"]["u_pu"], "u_angle", res["node"]["u_angle"])
print("line loading:", res["line"]["loading"], "s_from", res["line"]["s_from"])
print("gen q:", res["sym_gen"]["q"])

# short circuit prototype
fault = initialize_array("input", "fault", 2)
fault["id"] = [10, 11]; fault["status"] = [0, 0]
fault["fault_type"] = [FaultType.three_phase] * 2
fault["fault_phase"] = [0, 0]; fault["fault_object"] = [1, 2]
fault["r_f"] = [0.0, 0.0]; fault["x_f"] = [0.0, 0.0]
data2 = dict(data); data2["fault"] = fault
model2 = PowerGridModel(data2)
upd = initialize_array("update", "fault", (2, 1))
upd["id"] = [[10], [11]]
upd["status"] = [[1], [0]]
try:
    sc = model2.calculate_short_circuit(fault_type="three_phase", update_data={"fault": upd})
    print("SC keys:", list(sc.keys()))
    print("SC fault:", sc["fault"]["i_f"], sc["fault"]["id"], sc["fault"]["energized"])
    print("SC node u_pu:", sc["node"]["u_pu"])
except Exception as e:
    print("SC ERR", type(e).__name__, e)
