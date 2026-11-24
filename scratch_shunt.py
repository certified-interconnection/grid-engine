from dataclasses import replace
import gridengine as ge

case = ge.load_case("case118")
for s in case.shunts:
    c = replace(case, shunts=[s])
    try:
        r = ge.run_power_flow(c)
        print(s.id, s.bus, "p", s.p_mw, "q", s.q_mvar, "table", s.table, "-> OK", round(float(r.vm.min()), 3))
    except Exception as e:
        print(s.id, s.bus, "p", s.p_mw, "q", s.q_mvar, "table", s.table, "-> FAIL", str(e).splitlines()[0][:60])
