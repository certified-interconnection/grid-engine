"""Cross-checks against pandapower (independent solver) and basic properties of the contingency sets."""
import numpy as np
import pytest
import pandapower as pp
from pandapower.converter.matpower import from_mpc

from gridengine import Engine, load_case, apply_season, p1, p7, n2_sample
from gridengine.cases import DATA


def _pandapower(name):
    net = from_mpc(f"{DATA}/{name}.m", f_hz=60)
    pp.runpp(net, numba=False, init="flat", enforce_q_lims=False, tolerance_mva=1e-9)
    return net


@pytest.mark.parametrize("name", ["case30", "case118", "case_ACTIVSg200"])
def test_base_case_matches_pandapower(name):
    eng = Engine(load_case(name))
    out = eng.model.calculate_power_flow(calculation_initialization=eng.init, error_tolerance=1e-10, max_iterations=30)
    net = _pandapower(name)
    assert np.abs(out["node"]["u_pu"] - net.res_bus.vm_pu.values).max() < 1e-6


def test_single_outages_match_pandapower():
    name = "case118"
    eng = Engine(load_case(name))
    conts = p1(eng.branches)[:6]
    upd = eng._update(conts)
    out = eng.model.calculate_power_flow(update_data=upd, calculation_initialization=eng.init, error_tolerance=1e-10,
                                         max_iterations=30)
    for s, c in enumerate(conts):
        b = eng.branches[c[0]]
        net = from_mpc(f"{DATA}/{name}.m", f_hz=60)
        hits = [("line", i) for i, r in net.line.iterrows() if {int(r.from_bus), int(r.to_bus)} == {b["f"], b["t"]}]
        hits += [("trafo", i) for i, r in net.trafo.iterrows() if {int(r.hv_bus), int(r.lv_bus)} == {b["f"], b["t"]}]
        if len(hits) != 1:
            continue  # parallel branches: skip, ambiguous mapping
        tb, i = hits[0]
        net[tb].loc[i, "in_service"] = False
        pp.runpp(net, numba=False, init="flat", enforce_q_lims=False, tolerance_mva=1e-9)
        assert np.abs(out["node"]["u_pu"][s] - net.res_bus.vm_pu.values).max() < 1e-5


def test_contingency_sets():
    eng = Engine(load_case("case118"))
    a, b = p1(eng.branches), p7(eng.branches)
    assert len(a) == 177 and all(len(c) == 1 for c in a)
    assert all(len(c) == 2 for c in b)
    assert len(n2_sample(eng.branches, n=50)) == 50


def test_seasons_scale_load():
    c = load_case("case118")
    w = apply_season(c, "light_load")
    assert np.isclose(w["bus"][:, 2].sum(), 0.55 * c["bus"][:, 2].sum())


def test_light_load_switches_capacitors():
    c = load_case("case118")
    w = apply_season(c, "light_load")
    caps = c["bus"][:, 5] > 0
    assert np.allclose(w["bus"][caps, 5], 0.55 * c["bus"][caps, 5])
    assert np.allclose(w["bus"][~caps, 5], c["bus"][~caps, 5])


def test_texas2000_light_load_base_case_is_secure():
    # regression: with capacitors left in at 55% load the base case ran at 152% loading and 1.15 pu
    r = Engine(apply_season(load_case("case_ACTIVSg2000"), "light_load")).base_case()
    assert r["converged"][0] and r["max_loading"][0] < 1.0 and r["vmax"][0] < 1.1


def test_capacity_is_secure_and_tight():
    from gridengine.capacity import CapacityStudy
    eng = Engine(load_case("case118")); P1 = p1(eng.branches)
    r = dict(bus=10, mw=300.0, kind="gen")
    cs = CapacityStudy(eng, [10])
    c = cs.capacity([r], P1, tol=0.01)
    assert 0 < c["mw"] < 300
    assert cs.secure([r], [c["t"]], P1)[0]
    assert not cs.secure([r], [min(1.0, c["t"] + 0.02)], P1)[0]


def test_best_subset_beats_fixed_orders():
    from gridengine.capacity import CapacityStudy
    eng = Engine(load_case("case118")); P1 = p1(eng.branches)
    req = [dict(bus=10, mw=300, kind="gen"), dict(bus=25, mw=200, kind="load"), dict(bus=26, mw=80, kind="gen")]
    cs = CapacityStudy(eng, [10, 25, 26])
    best = cs.best_subset(req, P1)
    assert best["mw"] >= cs.admit(req, P1)["mw"] and best["mw"] >= cs.admit(req, P1, order=[2, 1, 0])["mw"]
