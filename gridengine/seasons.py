"""Three load cases built from a base case. Simple, stated assumptions (not any operator's cases):

summer_peak : loads x1.00 (the base case is treated as summer peak)
winter_peak : loads x0.90 (each load keeps its power factor)
light_load  : loads x0.55
Generator active power is scaled by the same factor as total real load, so the slack picks up only losses.
Capacitive bus shunts (BS > 0) are scaled by the same factor, standing in for operators switching capacitor banks
out as load falls. Without this, the 2,000-bus Texas grid at light load keeps 18,300 MVAr of capacitors in service,
its peak voltage reaches 1.15 pu and one branch runs at 152% before any outage. Reactors (BS < 0) are left as is.
"""
from __future__ import annotations

import copy
import numpy as np

SEASONS = {"summer_peak": dict(p=1.00, pf=None), "winter_peak": dict(p=0.90, pf=None), "light_load": dict(p=0.55, pf=None)}


def apply_season(case: dict, season: str) -> dict:
    if season not in SEASONS:
        raise ValueError(f"unknown season {season!r}; choose from {list(SEASONS)}")
    s = SEASONS[season]
    c = copy.deepcopy(case)
    c["bus"][:, 2] *= s["p"]
    if s["pf"] is None:
        c["bus"][:, 3] *= s["p"]
    else:
        c["bus"][:, 3] = np.abs(c["bus"][:, 2]) * np.tan(np.arccos(s["pf"]))
    c["gen"][:, 1] *= s["p"]
    caps = c["bus"][:, 5] > 0
    c["bus"][caps, 5] *= s["p"]
    c["season"] = season
    return c
