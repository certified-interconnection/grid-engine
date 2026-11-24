from power_grid_model import initialize_array
for comp in ["node", "line", "generic_branch", "transformer", "sym_load", "sym_gen",
             "voltage_regulator", "shunt", "source", "fault", "three_winding_transformer"]:
    try:
        a = initialize_array("input", comp, 1)
        print(comp, "->", a.dtype.names)
    except Exception as e:
        print(comp, "ERR", e)
print()
a = initialize_array("sym_output", "node", 1)
print("node sym_output:", a.dtype.names)
b = initialize_array("sym_output", "branch", 1)
print("branch sym_output:", b.dtype.names)
c = initialize_array("sym_output", "appliance", 1)
print("appliance sym_output:", c.dtype.names)
d = initialize_array("sym_sc_output", "fault", 1) if True else None
print("fault sc output:", d.dtype.names)
