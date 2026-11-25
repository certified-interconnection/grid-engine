"""How much can connect: per bus, per project, and for a whole cluster, under a contingency set.

    from gridengine import Engine, load_case, p1
    from gridengine.capacity import CapacityStudy
    eng = Engine(load_case("case118"))
    cs = CapacityStudy(eng, buses=[10, 25, 59])
    req = [dict(bus=10, mw=200, kind="gen"), dict(bus=25, mw=150, kind="load"), dict(bus=59, mw=300, kind="gen")]
    cs.individual(req, p1(eng.branches))      # each request alone: largest secure MW, and what binds
    cs.joint(req, p1(eng.branches))           # the whole cluster scaled together
    cs.admit(req, p1(eng.branches))           # all-or-nothing admission, largest first (cluster) or in queue order

Conventions (stated, not any operator's):
- A request is a constant-power injection at a bus: generation ("gen") or load ("load"), unity power factor by default.
- Balance: new generation displaces the existing generators in proportion to their output; new load is served by
  them in the same proportion ("gens"), as in a deliverability-style study. balance="slack" sends it all to the slack.
- Secure: every case in [base] + contingencies converges, no branch above its rating, voltages in the engine's band.
- Capacity: largest t in [0, 1] with t * request secure, by bisection to `tol` (fraction of the request).
- Screening: each bisection step only runs the contingencies that were near-binding at the full request; the final
  answer is always re-checked against the full set (and the screen widened if it fails), so it is exact for the set.
"""
from __future__ import annotations

import numpy as np
from power_grid_model import ComponentType, DatasetType, PowerGridModel, initialize_array
from power_grid_model.errors import PowerGridBatchError
from power_grid_model import CalculationMethod

PROBE0 = 700000


class CapacityStudy:
    def __init__(self, engine, buses, balance="gens", pf=1.0):
        self.eng = engine
        self.balance = balance
        self.buses = [int(b) for b in buses]
        self.pos = {b: k for k, b in enumerate(self.buses)}
        data = dict(engine.input)
        probe = initialize_array(DatasetType.input, ComponentType.sym_load, len(self.buses))
        probe["id"] = PROBE0 + np.arange(len(self.buses)); probe["node"] = self.buses
        probe["status"] = 1; probe["type"] = 0; probe["p_specified"] = 0.0; probe["q_specified"] = 0.0
        loads = engine.input["sym_load"]
        data["sym_load"] = np.concatenate([loads, probe])
        self.n_load0 = len(loads)
        self.input = data
        self.model = PowerGridModel(data)
        self.tanphi = float(np.tan(np.arccos(pf)))
        self.gen_p0 = data["sym_gen"]["p_specified"].copy() if "sym_gen" in data else np.zeros(0)
        self.solves = 0
        self._ucache = {}

    # --------------------------------------------------------------- batch evaluation
    def _injection(self, requests, scale):
        """Probe-load p (W) for each scenario row of `scale` (n_scen, n_req)."""
        scale = np.atleast_2d(scale)
        p = np.zeros((scale.shape[0], len(self.buses)))
        net = np.zeros(scale.shape[0])  # net new generation (W)
        for j, r in enumerate(requests):
            sgn = -1.0 if r["kind"] == "gen" else 1.0
            mw = scale[:, j] * r["mw"] * 1e6
            p[:, self.pos[int(r["bus"])]] += sgn * mw
            net += -sgn * mw
        return p, net

    def _evaluate(self, requests, scale, conts):
        """scale: (n_req,) one injection; conts: list of contingencies (index tuples); () = base case.
        Returns per-contingency dict from the engine's summary."""
        n = len(conts)
        p, net = self._injection(requests, np.asarray(scale)[None, :])
        key = tuple(conts)
        if key not in self._ucache:
            if len(self._ucache) > 64:
                self._ucache.clear()
            self._ucache[key] = self.eng._update(conts)
        upd = dict(self._ucache[key])
        sl = initialize_array(DatasetType.update, ComponentType.sym_load, (n, len(self.input["sym_load"])))
        sl["id"] = self.input["sym_load"]["id"][None, :]
        sl["p_specified"] = self.input["sym_load"]["p_specified"][None, :]
        sl["q_specified"] = self.input["sym_load"]["q_specified"][None, :]
        sl["p_specified"][:, self.n_load0:] = p[0][None, :]
        sl["q_specified"][:, self.n_load0:] = np.abs(p[0])[None, :] * self.tanphi * np.sign(p[0])[None, :]
        upd["sym_load"] = sl
        if self.balance == "gens" and len(self.gen_p0) and self.gen_p0.sum() > 0:
            g = initialize_array(DatasetType.update, ComponentType.sym_gen, (n, len(self.gen_p0)))
            g["id"] = self.input["sym_gen"]["id"][None, :]
            g["p_specified"] = (self.gen_p0 * max(1.0 - net[0] / self.gen_p0.sum(), 0.0))[None, :]
            upd["sym_gen"] = g
        failed = np.zeros(n, dtype=bool)
        try:
            out = self.model.calculate_power_flow(update_data=upd, calculation_method=CalculationMethod.newton_raphson,
                                                  error_tolerance=1e-8, max_iterations=30, continue_on_batch_error=True,
                                                  calculation_initialization=self.eng.init)
        except PowerGridBatchError as e:
            out = e.output
            failed[np.asarray(e.failed_scenarios, dtype=int)] = True
        self.solves += n
        return self.eng._summarize(out, single=False, failed=failed)

    # --------------------------------------------------------------- incremental security
    def _baseline(self, allc):
        """The grid before any request is added, on the same cases (zero injection)."""
        key = ("base",) + tuple(allc)
        if key not in self._ucache:
            r = self._evaluate([dict(bus=self.buses[0], mw=0.0, kind="gen")], [0.0], allc)
            self._ucache[key] = r
        return self._ucache[key]

    def _ok(self, r, z, tol=0.005):
        """A case passes if it is secure, or if it was already insecure without the requests and they don't make it
        worse (no new overload beyond the old loading, voltages no further outside the band). Studies charge a project
        only for violations it causes or worsens, so pre-existing problems don't zero every project."""
        lo, hi = self.eng.v_band
        worse = (r["max_loading"] > np.maximum(1.0, z["max_loading"]) + tol) |                 (r["vmin"] < np.minimum(lo, z["vmin"]) - tol) | (r["vmax"] > np.maximum(hi, z["vmax"]) + tol)
        return r["secure"] | (~z["secure"] & r["converged"] & ~worse)

    def _check(self, requests, scale, allc, idx=None):
        cases = allc if idx is None else [allc[i] for i in idx]
        r = self._evaluate(requests, scale, cases)
        z = self._baseline(allc)
        if idx is not None:
            z = {k: v[idx] for k, v in z.items()}
        return self._ok(r, z), r

    def secure(self, requests, scale, conts):
        ok, r = self._check(requests, scale, [()] + list(conts))
        return bool(ok.all()), r

    # --------------------------------------------------------------- capacity along a direction
    def capacity(self, requests, conts, mix=None, tol=0.01, screen_margin=0.9):
        """Largest t in [0, 1] with t * mix passing (see _ok). Returns dict with t, mw, binding."""
        k = len(requests)
        mix = np.ones(k) if mix is None else np.asarray(mix, float)
        allc = [()] + list(conts)
        total = float(sum(m * r["mw"] for m, r in zip(mix, requests)))
        ok, full = self._check(requests, mix, allc)
        z = self._baseline(allc)
        pre = int((~z["secure"]).sum())
        if ok.all():
            return dict(t=1.0, mw=total, binding=None, censored=True, pre_existing_violations=pre)
        near = (~ok) | (full["max_loading"] >= screen_margin) | ~full["converged"] | ~z["secure"]
        idx = list(np.nonzero(near)[0])
        while True:
            lo, hi = 0.0, 1.0
            while hi - lo > tol:
                mid = 0.5 * (lo + hi)
                if self._check(requests, mid * mix, allc, np.array(idx))[0].all():
                    lo = mid
                else:
                    hi = mid
            ok_lo, _ = self._check(requests, lo * mix, allc)
            if ok_lo.all():
                ok_hi, r_hi = self._check(requests, hi * mix, allc)
                return dict(t=lo, mw=lo * total, binding=self._binding(r_hi, ok_hi, allc), censored=False,
                            pre_existing_violations=pre)
            idx = sorted(set(idx) | set(np.nonzero(~ok_lo)[0]))

    def _binding(self, r, ok, allc):
        bad = np.nonzero(~ok)[0]
        if not len(bad):
            return None
        i = int(bad[np.argmax(r["max_loading"][bad])])
        c = allc[i]
        why = ("diverged" if not r["converged"][i] else "overload" if r["max_loading"][i] > 1 + 1e-9
               else "low voltage" if r["vmin"][i] < self.eng.v_band[0] else "high voltage")
        return dict(contingency=[self.eng.branches[b]["id"] for b in c] if c else "base",
                    reason=why, max_loading=float(r["max_loading"][i]), vmin=float(r["vmin"][i]), vmax=float(r["vmax"][i]))

    # --------------------------------------------------------------- studies
    def individual(self, requests, conts, tol=0.01):
        out = []
        for r in requests:
            c = self.capacity([r], conts, tol=tol)
            out.append(dict(bus=r["bus"], kind=r["kind"], mw=r["mw"], capacity_mw=c["mw"], fits=c["t"] >= 1.0,
                            binding=c["binding"]))
        return out

    def joint(self, requests, conts, tol=0.01):
        return self.capacity(requests, conts, tol=tol)

    def admit(self, requests, conts, order=None):
        """All-or-nothing admission in a fixed order: order=None is largest first; pass a queue order for first-come."""
        k = len(requests)
        order = list(np.argsort([-r["mw"] for r in requests])) if order is None else list(order)
        a = np.zeros(k)
        for j in order:
            trial = a.copy(); trial[j] = 1.0
            if self.secure(requests, trial, conts)[0]:
                a = trial
        return dict(admitted=[int(j) for j in np.nonzero(a)[0]], mw=float(sum(requests[j]["mw"] for j in np.nonzero(a)[0])))

    def best_subset(self, requests, conts, max_k=10):
        """Exact cluster decision: the subset with the most MW that passes, all-or-nothing per request.
        Subsets are tried in decreasing MW; the first that passes is optimal. Up to 2^K checks (K <= max_k)."""
        k = len(requests)
        if k > max_k:
            raise ValueError("too many requests for exact search")
        mw = np.array([r["mw"] for r in requests])
        subsets = sorted(range(1 << k), key=lambda m: -sum(mw[j] for j in range(k) if m >> j & 1))
        for n_checked, m in enumerate(subsets, 1):
            a = np.array([(m >> j) & 1 for j in range(k)], float)
            if m == 0 or self.secure(requests, a, conts)[0]:
                return dict(admitted=[j for j in range(k) if m >> j & 1], mw=float(mw @ a), checks=n_checked)

    def bus_map(self, conts, kind="gen", mw_max=500.0, tol=0.02, buses=None):
        """Hosting capacity (MW, capped at mw_max) at each bus for one new request of `kind`."""
        res = {}
        for b in (self.buses if buses is None else buses):
            c = self.capacity([dict(bus=b, mw=mw_max, kind=kind)], conts, tol=tol)
            res[int(b)] = dict(mw=c["mw"], capped=c.get("censored", False), binding=c["binding"])
        return res
