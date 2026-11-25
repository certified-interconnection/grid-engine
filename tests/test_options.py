"""Unit checks for the Step 3 options (gridengine/options.py) on case118, summer peak, P1.

The cluster is Step 2's cluster 25 (results/capacity_case118.json): three requests at buses 84 and 85, only 40.4 of
168.9 MW fit as a plain all-or-nothing subset. Checks:
- keep = 1.0 reproduces the plain best subset exactly (the per-case evaluation adds nothing by itself);
- every option's admitted set passes the full AC check under its own rule, re-checked after the search;
- every option admits at least the plain best subset (each option is a relaxation);
- the original Engine is not mutated by the switching option.
"""
import numpy as np
import pytest

from gridengine import Engine, load_case, apply_season, p1
from gridengine.capacity import CapacityStudy
from gridengine.options import OptionsStudy

REQ = [dict(bus=85, mw=73.7, kind="load"), dict(bus=85, mw=54.8, kind="gen"), dict(bus=84, mw=40.4, kind="load")]


@pytest.fixture(scope="module")
def eng():
    return Engine(apply_season(Engine(load_case("case118")).case, "summer_peak"))


@pytest.fixture(scope="module")
def study(eng):
    return OptionsStudy(eng, REQ, p1(eng.branches))


def _check_option(study, rec):
    plain = study.plain
    assert rec["mw"] >= plain["mw"] - 1e-9
    assert np.isclose(rec["gain_mw"], rec["mw"] - plain["mw"])
    assert np.isclose(rec["mw"], sum(REQ[j]["mw"] for j in rec["admitted"])) or rec.get("rule") == "partial"


def test_plain_matches_step2(study):
    assert sorted(study.plain["admitted"]) == [2]
    assert np.isclose(study.plain["mw"], 40.4)


def test_flexible_keep_one_is_the_plain_subset(study):
    plain = study.plain
    out = study.best_subset_flexible(REQ, study.conts, [0, 1, 2], 1.0, relax=False)
    assert np.isclose(out["mw"], plain["mw"])
    assert sorted(out["admitted"]) == sorted(plain["admitted"])
    out = study.best_subset_flexible(REQ, study.conts, [0, 1, 2], 1.0)
    assert np.isclose(out["mw"], plain["mw"]) and not out["option_used"]


@pytest.mark.parametrize("name,idx,keep", [("flex_load_50", [0, 2], 0.5), ("flex_load_0", [0, 2], 0.0),
                                           ("storage_25", [0, 2], 0.75), ("ras_gen_0", [1], 0.0)])
def test_flexible_options_relax_and_recheck(study, name, idx, keep):
    rec = study.best_subset_flexible(REQ, study.conts, idx, keep)
    _check_option(study, rec)
    assert study.recheck_flexible(rec), name
    if rec["option_used"]:
        # the gain really needs the curtailment: the same set is not secure as a firm request
        assert not study.cs.secure(REQ, study._vec(rec["admitted"], 3), study.conts)[0]


def test_storage_matches_flexible_rule(study):
    s = study.best_subset_storage(REQ, study.conts, 0.5)
    f = study.best_subset_flexible(REQ, study.conts, [0, 2], 0.5)
    assert np.isclose(s["mw"], f["mw"]) and s["admitted"] == f["admitted"]


def test_switch_relaxes_rechecks_and_does_not_mutate(eng, study):
    before = eng.input["generic_branch"]["from_status"].copy()
    sw = study.best_switch(top=4)
    _check_option(study, sw)
    assert study.recheck_switch(sw)
    assert np.array_equal(before, eng.input["generic_branch"]["from_status"])
    cs = CapacityStudy(eng, study.buses)
    assert np.isclose(cs.best_subset(REQ, study.conts)["mw"], study.plain["mw"])


def test_partial_relaxes_and_rechecks(study):
    pt = study.partial_mw()
    _check_option(study, pt)
    assert study.recheck_partial(pt)
    assert all(0.0 <= x["t"] <= 1.0 for x in pt["per_request"])


# A second small cluster (loads at buses 104, 105, 106, from Step 2's cluster 1) where nothing fits as a firm request
# but post-contingency curtailment admits a load, so the option path (option_used) and its re-check are exercised.
REQ2 = [dict(bus=104, mw=70.3, kind="load"), dict(bus=105, mw=90.2, kind="load"), dict(bus=106, mw=172.0, kind="load")]


@pytest.fixture(scope="module")
def study2(eng):
    return OptionsStudy(eng, REQ2, p1(eng.branches))


@pytest.mark.parametrize("keep", [0.5, 0.0])
def test_flexible_gain_is_real_and_rechecks(study2, keep):
    rec = study2.best_subset_flexible(REQ2, study2.conts, [0, 1, 2], keep)
    assert study2.plain["mw"] == 0.0
    assert rec["option_used"] and rec["gain_mw"] > 0
    assert study2.recheck_flexible(rec, REQ2, study2.conts)
    assert not study2.cs.secure(REQ2, study2._vec(rec["admitted"], 3), study2.conts)[0]


def test_two_code_paths_agree(study2):
    """The search's per-case evaluator and the re-check (CapacityStudy's own code path) give the same verdict."""
    keepvec = np.array([0.5, 0.5, 0.5])
    for a in ([1, 0, 0], [0, 1, 0], [1, 1, 0]):
        a = np.array(a, float)
        fast = bool(study2._ok_rows(study2.cs, REQ2, a, keepvec, study2.conts).all())
        assert fast == study2.secure_flexible(REQ2, a, study2.conts, keepvec)
    k = next(i for i in range(len(study2.eng.branches)) if not study2._islanding(i, study2.conts))
    cs2 = study2.switched(k)
    for a in ([1, 0, 0], [0, 1, 0]):
        a = np.array(a, float)
        fast = bool(study2._ok_rows(cs2, REQ2, a, np.ones(3), study2.conts).all())
        assert fast == study2.secure_switched(k, a)
