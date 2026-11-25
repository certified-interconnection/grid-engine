"""Base-case check against references that don't go through pandapower's MATPOWER converter:
  - Power Grid Model's own validated IEEE 300 solution (data/reference, no reactive limits, same as grid-engine)
  - MATPOWER's stored solution in each .m file (computed WITH generator reactive limits, which grid-engine does not
    model, so differences of a few hundredths of a pu are expected and reported for information only)
pandapower's from_mpc converts 12 IEEE 300 branches wrongly ("trafos that connect same voltage levels"), so it is not
used as the referee there. Usage: python bench/validate_reference.py -> results/validate_reference.json"""
import json, os, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case
from power_grid_model.utils import json_deserialize_from_file

out = {}
for name in ["case30", "case118", "case_ACTIVSg200", "case300", "case_ACTIVSg500", "case_ACTIVSg2000"]:
    c = load_case(name); eng = Engine(c)
    o = eng.model.calculate_power_flow(calculation_initialization=eng.init, error_tolerance=1e-10, max_iterations=30)
    ref = int(np.nonzero(c["bus"][:, 1] == 3)[0][0])
    r = dict(matpower_stored_max_dv=float(np.abs(o["node"]["u_pu"] - c["bus"][:, 7]).max()),
             matpower_stored_max_dangle_deg=float(np.abs(np.rad2deg(o["node"]["u_angle"]) - (c["bus"][:, 8] - c["bus"][ref, 8])).max()))
    if name == "case300":
        R = json_deserialize_from_file(Path(__file__).resolve().parent.parent / "data/reference/pgm_matpower_case300_sym_output.json")["node"]
        m = {int(i): (u, a) for i, u, a in zip(R["id"], R["u_pu"], R["u_angle"])}
        bn = c["bus_numbers"]
        r["pgm_reference_matched"] = sum(int(b) in m for b in bn)
        r["pgm_reference_max_dv"] = float(max(abs(o["node"]["u_pu"][k] - m[int(b)][0]) for k, b in enumerate(bn)))
        r["pgm_reference_max_dangle_deg"] = float(max(abs(np.rad2deg(o["node"]["u_angle"][k] - m[int(b)][1])) for k, b in enumerate(bn)))
    out[name] = r
    print(name, r)
os.makedirs("results", exist_ok=True)
json.dump(out, open("results/validate_reference.json", "w"), indent=1)
