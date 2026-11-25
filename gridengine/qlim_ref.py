"""Reference AC power flow WITH generator reactive limits, for checking grid-engine's q_limits option.
MATPOWER's own outer loop (runpf with ENFORCE_Q_LIMS=1): solve with PYPOWER, find generators beyond QMIN/QMAX, fix
them at the limit (their bus becomes PQ, the fixed Q added as a negative load), repeat until none is violated.
PYPOWER's built-in version fails on current numpy (float indices), so this re-implements that loop around runpf."""
import numpy as np
from pypower.api import runpf, ppoption

OPT = ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, ENFORCE_Q_LIMS=0, PF_MAX_IT=50)


def solve_qlim(case, out_branches=(), max_rounds=30):
    bus = case["bus"].copy(); gen = case["gen"].copy(); br = case["branch"].copy()
    for b in out_branches:
        br[b, 10] = 0
    gen = gen[gen[:, 7] > 0]
    ref = int(np.nonzero(bus[:, 1] == 3)[0][0])
    fixed = np.zeros(len(gen), bool)
    for _ in range(max_rounds):
        ppc = dict(version="2", baseMVA=case["baseMVA"], bus=bus.copy(), gen=gen.copy(), branch=br.copy())
        ppc["bus"][:, 0] += 1; ppc["gen"][:, 0] += 1; ppc["branch"][:, 0] += 1; ppc["branch"][:, 1] += 1
        # fixed generators: bus to PQ (unless slack), their Q as negative load, generator off
        for k in np.nonzero(fixed)[0]:
            b = int(gen[k, 0])
            ppc["bus"][b, 3] -= gen[k, 2]
            ppc["bus"][b, 2] -= gen[k, 1]
            ppc["gen"][k, 7] = 0
            if b != ref and not ((gen[:, 0] == b) & ~fixed).any():
                ppc["bus"][b, 1] = 1
        r, ok = runpf(ppc, OPT)
        if not ok:
            return None, False
        q = r["gen"][:, 2]
        viol = ~fixed & (gen[:, 0] != ref) & ((q > gen[:, 3] + 1e-6) | (q < gen[:, 4] - 1e-6))
        if not viol.any():
            solve_qlim.fixed_buses = sorted(set(gen[fixed, 0].astype(int).tolist()))
            return r["bus"][:, 7], True
        # fix the worst violators at their limits (MATPOWER fixes all violators each round)
        gen[viol, 2] = np.where(q[viol] > gen[viol, 3], gen[viol, 3], gen[viol, 4])
        gen[viol, 1] = r["gen"][viol, 1]
        fixed |= viol
    return None, False
