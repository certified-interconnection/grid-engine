"""DC power flow: the linear baseline that screening tools (and PJM's DFAX-based steps) rely on.

Same case arrays and ratings as the AC engine (so ratings synthesized by Engine are reused).
  flows(case, outage=())            -> MW on every in-service branch (outaged ones 0)
  security(case, contingencies)     -> per contingency: max loading |f| / RATE_A and secure (thermal only, DC has no voltage)
  capacity(case, bus, kind, conts)  -> largest MW of new generation / load at `bus` with every case thermally secure,
                                       balanced by existing generators pro rata (the AC capacity layer's convention)
DC assumptions (standard): flat 1 pu voltages, no losses, no reactive power, branch flow = (theta_f - theta_t - shift) / (x * tap).
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

TOL = 0.005   # same loading tolerance as CapacityStudy._ok


def _parts(case):
    bus, gen, br = case["bus"], case["gen"], case["branch"]
    on = np.nonzero(br[:, 10] > 0)[0]
    nb = bus.shape[0]
    ref = int(np.nonzero(bus[:, 1] == 3)[0][0])
    tap = np.where(br[on, 8] != 0, br[on, 8], 1.0)
    b = 1.0 / (br[on, 3] * tap)
    shift = np.deg2rad(br[on, 9])
    f = br[on, 0].astype(int); t = br[on, 1].astype(int)
    rate = br[on, 5]
    g_on = gen[gen[:, 7] > 0]
    pg = np.zeros(nb); np.add.at(pg, g_on[:, 0].astype(int), g_on[:, 1])
    p = (pg - bus[:, 2] - bus[:, 4]) / case["baseMVA"]          # injections in pu (GS as constant-power at 1 pu)
    return dict(nb=nb, ref=ref, b=b, shift=shift, f=f, t=t, rate=rate, p=p, on=on, base=case["baseMVA"],
                gen_bus=g_on[:, 0].astype(int), gen_p=g_on[:, 1])


def _solve(P, d, drop):
    keep = np.ones(len(d["b"]), bool); keep[list(drop)] = False
    f, t, b, s = d["f"][keep], d["t"][keep], d["b"][keep], d["shift"][keep]
    nb = d["nb"]
    B = sp.coo_matrix((np.r_[b, b, -b, -b], (np.r_[f, t, f, t], np.r_[f, t, t, f])), shape=(nb, nb)).tocsc()
    pinj = np.atleast_2d(P).T if P.ndim == 1 else P.T          # (nb, n_rhs)
    sh = np.zeros(nb); np.add.at(sh, f, -b * s); np.add.at(sh, t, b * s)
    rhs = pinj - sh[:, None]
    idx = np.r_[0:d["ref"], d["ref"] + 1:nb]
    th = np.zeros((nb, rhs.shape[1]))
    th[idx] = spla.splu(B[idx][:, idx]).solve(rhs[idx])
    flow = np.zeros((len(d["b"]), rhs.shape[1]))
    flow[keep] = b[:, None] * (th[f] - th[t] - s[:, None])
    return flow * d["base"]                                       # MW, (n_branch, n_rhs)


def flows(case, outage=()):
    d = _parts(case)
    return _solve(d["p"], d, outage)[:, 0]


def security(case, contingencies):
    d = _parts(case)
    rate = np.where(d["rate"] > 0, d["rate"], np.inf)
    allc = [()] + list(contingencies)
    lmax = np.array([np.max(np.abs(_solve(d["p"], d, c)[:, 0]) / rate) for c in allc])
    return dict(max_loading=lmax[1:], secure=lmax[1:] <= 1.0 + 1e-9, base_max_loading=float(lmax[0]))


def _direction(d, bus, kind):
    """Injection change (pu) per MW of the request, balanced by existing generators pro rata."""
    v = np.zeros(d["nb"])
    sgn = 1.0 if kind == "gen" else -1.0
    v[bus] += sgn / d["base"]
    w = d["gen_p"] / d["gen_p"].sum()
    np.add.at(v, d["gen_bus"], -sgn * w / d["base"])
    return v


def capacity(case, bus, kind, contingencies, mw_max):
    """Largest MW in [0, mw_max] keeping every case (base + contingencies) within ratings, in DC. Exact (linear).
    Branches already over their rating before the request may not get worse (the AC layer's incremental rule)."""
    d = _parts(case)
    rate = np.where(d["rate"] > 0, d["rate"], np.inf)
    v = _direction(d, bus, kind)
    t = mw_max
    for c in [()] + list(contingencies):
        F = _solve(np.vstack([d["p"], v]), d, c)
        f0, df = F[:, 0], F[:, 1]
        lim = np.maximum(rate, np.abs(f0)) + TOL * rate   # already-overloaded branches may not get worse beyond TOL (as in the AC layer)
        with np.errstate(divide="ignore", invalid="ignore"):
            up = np.where(df > 1e-12, (lim - f0) / df, np.inf)
            dn = np.where(df < -1e-12, (-lim - f0) / df, np.inf)
        t = min(t, float(np.min(np.minimum(up, dn))))
        if t <= 0:
            return 0.0
    return max(t, 0.0)
