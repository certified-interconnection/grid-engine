"""Load a grid as MATPOWER-style arrays (bus, gen, branch, baseMVA) straight from a MATPOWER .m file in data/,
renumbered to 0..n-1. Reading MATPOWER directly (not through pandapower's model) keeps branch data exactly as
published; pandapower is used only as an independent cross-check in the tests."""
from __future__ import annotations

import os
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CASES = ["case30", "case118", "case_ACTIVSg200", "case300", "case_ACTIVSg500", "case_ACTIVSg2000"]


def load_case(name: str):
    from matpowercaseframes import CaseFrames
    path = os.path.join(DATA, name + ".m")
    if not os.path.exists(path):
        raise ValueError(f"no MATPOWER file for {name!r} in data/ (have: {CASES})")
    cf = CaseFrames(path)
    bus = cf.bus.values.astype(float).copy()
    gen = cf.gen.values.astype(float).copy()
    br = cf.branch.values.astype(float).copy()
    idx = {int(b): i for i, b in enumerate(bus[:, 0])}
    bus[:, 0] = np.arange(len(bus))
    gen[:, 0] = [idx[int(b)] for b in gen[:, 0]]
    br[:, 0] = [idx[int(b)] for b in br[:, 0]]
    br[:, 1] = [idx[int(b)] for b in br[:, 1]]
    return dict(name=name, baseMVA=float(cf.baseMVA), bus=bus, gen=gen, branch=br, bus_numbers=list(idx))
