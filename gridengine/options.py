"""Ways to make room for a cluster that does not fully fit (Certified Interconnection, Step 3).

    from gridengine import Engine, load_case, p1
    from gridengine.options import OptionsStudy
    eng = Engine(load_case("case118"))
    req = [dict(bus=10, mw=300, kind="gen"), dict(bus=25, mw=200, kind="load"), dict(bus=26, mw=80, kind="gen")]
    opt = OptionsStudy(eng, req, p1(eng.branches))
    opt.plain                                              # CapacityStudy.best_subset (all-or-nothing, firm)
    opt.best_subset_flexible(req, opt.conts, [1], 0.5)     # request 1 cut to 50% after any outage
    opt.best_subset_storage(req, opt.conts, 0.25)          # battery = 25% of each load request
    opt.best_switch()                                      # one branch opened for good
    opt.partial_mw()                                       # left-out requests at less than full size

The baseline is the plain cluster decision (CapacityStudy.best_subset): all-or-nothing per request, firm, fixed
topology. Each option relaxes one of those assumptions and reports the MW it admits.

Rules (stated, ours):
- Every option keeps CapacityStudy's incremental security rule (CapacityStudy._ok) and the same contingency set. The
  "before" grid for that rule is always the ORIGINAL grid with no requests, so an option is never excused for a
  violation it creates itself (a switch that overloads something on its own does not get that overload for free).
- Each option is a relaxation: the operator may always fall back to the plain best subset, so the search only looks
  for subsets with more MW than the plain one, and the option's MW is at least the plain MW by construction.
- Post-contingency curtailment (flexible load, or generation on a remedial action scheme): a request is at full size
  in the base case and at `keep` times its size in every contingency case. The balancing generators follow the
  reduced injection (same pro-rata balance as CapacityStudy), scenario by scenario, in one batch.
- Co-located storage at a load: the load's contingency size is reduced by the battery MW (keep = 1 - fraction, loads
  only). With fraction 0.5 this is the same rule as flexible load with keep = 0.5.
- One switching action: one in-service branch opened permanently, in the base case and every contingency. Candidates
  are the 20 most loaded branches (at the plain subset) in the plain subset's binding case, i.e. the case that fails
  worst when the whole cluster is added (CapacityStudy._binding). A candidate is skipped if opening it islands the
  grid, or if any contingency in the set islands the grid once it is open (a single outage would become a separation
  that the P1 definition excludes). Each remaining candidate gets the exact subset search.
- Partial MW: the requests left out of the plain subset are scaled one at a time, largest first, each on top of the
  admitted set plus the partial MW already granted, by bisection to 1% of the request (each step a full AC check
  under CapacityStudy.secure). Sequential, so the final combination is secure by construction (and re-checked).
"""
from __future__ import annotations

import copy

import networkx as nx
import numpy as np
from power_grid_model import ComponentType, DatasetType, PowerGridModel, initialize_array

from .capacity import CapacityStudy


def _key(requests):
    return tuple((int(r["bus"]), float(r["mw"]), str(r["kind"])) for r in requests)


class OptionsStudy:
    def __init__(self, engine, requests, conts):
        """engine: gridengine.Engine; requests: list of dict(bus, mw, kind); conts: the contingency set (tuples of
        indices into engine.branches) the plain best subset is judged on."""
        self.eng = engine
        self.requests = [dict(bus=int(r["bus"]), mw=float(r["mw"]), kind=str(r["kind"])) for r in requests]
        self.conts = [tuple(int(i) for i in c) for c in conts]
        self.buses = sorted({r["bus"] for r in self.requests})
        self.cs = CapacityStudy(engine, self.buses)
        self._plain = {}
        self._sw = {}
        self.sw_solves = 0

    # ------------------------------------------------------------------ plain baseline
    def plain_subset(self, requests, conts):
        k = (_key(requests), tuple(conts))
        if k not in self._plain:
            self._plain[k] = self.cs.best_subset(requests, conts)
        return self._plain[k]

    @property
    def plain(self):
        return self.plain_subset(self.requests, self.conts)

    @staticmethod
    def _vec(admitted, k):
        a = np.zeros(k)
        a[list(admitted)] = 1.0
        return a

    # ------------------------------------------------------------------ batch evaluation, one scale row per case
    def _eval_rows(self, cs, requests, scales, cases):
        """Like CapacityStudy._evaluate, but scenario i uses its own row scales[i] (n_cases, n_req). Runs through
        Engine.run, so the engine's options (generator reactive limits) apply."""
        scales = np.atleast_2d(np.asarray(scales, dtype=float))
        n = len(cases)
        p, net = cs._injection(requests, scales)
        cache = cs.__dict__.setdefault("_rowcache", {})
        key = tuple(cases)
        if key not in cache:
            if len(cache) > 32:
                cache.clear()
            cache[key] = cs.eng._update(cases)
        upd = dict(cache[key])
        sl = initialize_array(DatasetType.update, ComponentType.sym_load, (n, len(cs.input["sym_load"])))
        sl["id"] = cs.input["sym_load"]["id"][None, :]
        sl["p_specified"] = cs.input["sym_load"]["p_specified"][None, :]
        sl["q_specified"] = cs.input["sym_load"]["q_specified"][None, :]
        sl["p_specified"][:, cs.n_load0:] = p
        sl["q_specified"][:, cs.n_load0:] = np.abs(p) * cs.tanphi * np.sign(p)
        upd["sym_load"] = sl
        if cs.balance == "gens" and len(cs.gen_p0) and cs.gen_p0.sum() > 0:
            g = initialize_array(DatasetType.update, ComponentType.sym_gen, (n, len(cs.gen_p0)))
            g["id"] = cs.input["sym_gen"]["id"][None, :]
            g["p_specified"] = cs.gen_p0[None, :] * np.maximum(1.0 - net[:, None] / cs.gen_p0.sum(), 0.0)
            upd["sym_gen"] = g
        out, failed = cs.eng.run(model=cs.model, update=upd, n=n)
        cs.solves += n
        return cs.eng._summarize(out, single=False, failed=failed), out

    def _allc(self, conts):
        return [()] + list(conts)

    def _ok_rows(self, cs, requests, a, keepvec, conts, idx=None):
        """Pass/fail per case: base case at scale a, contingencies at a * keepvec. The "before" grid is the original
        engine with no requests (self.cs._baseline), whatever engine `cs` wraps."""
        allc = self._allc(conts)
        idx = np.arange(len(allc)) if idx is None else np.asarray(idx, dtype=int)
        cases = [allc[i] for i in idx]
        scales = np.repeat(np.asarray(a, float)[None, :], len(idx), axis=0)
        scales[idx > 0] *= np.asarray(keepvec, float)[None, :]
        r, _ = self._eval_rows(cs, requests, scales, cases)
        z = self.cs._baseline(allc)
        z = {k: v[idx] for k, v in z.items()}
        return self.cs._ok(r, z)

    def _passes(self, cs, requests, a, keepvec, conts, hot):
        """Exact check with a screen: the cases that failed recently (`hot`, a list kept by the caller) are tried
        first; a subset is accepted only after the full set passes."""
        if hot:
            ok = self._ok_rows(cs, requests, a, keepvec, conts, idx=hot)
            if not ok.all():
                return False
        ok = self._ok_rows(cs, requests, a, keepvec, conts)
        if ok.all():
            return True
        for i in np.nonzero(~ok)[0][:4]:
            if int(i) not in hot:
                hot.insert(0, int(i))
        del hot[12:]
        return False

    # ------------------------------------------------------------------ exact search above a floor
    @staticmethod
    def _search(requests, ok, floor_mw, max_k=10):
        """The subset with the most MW that passes `ok`, among subsets with more MW than floor_mw (the plain subset,
        always available). Subsets are tried in decreasing MW, so the first that passes is optimal. Returns None if
        nothing above the floor passes."""
        k = len(requests)
        if k > max_k:
            raise ValueError("too many requests for exact search")
        mw = np.array([r["mw"] for r in requests], dtype=float)
        subsets = sorted(range(1 << k), key=lambda m: -sum(mw[j] for j in range(k) if m >> j & 1))
        checks = 0
        for m in subsets:
            a = np.array([(m >> j) & 1 for j in range(k)], dtype=float)
            if float(mw @ a) <= floor_mw + 1e-9:
                break
            checks += 1
            if ok(a):
                return dict(admitted=[j for j in range(k) if m >> j & 1], mw=float(mw @ a), checks=checks)
        return dict(admitted=None, mw=None, checks=checks)

    # ------------------------------------------------------------------ post-contingency curtailment
    def secure_flexible(self, requests, scale, conts, keepvec):
        """Independent re-check through CapacityStudy's own code path: the base case at `scale`, and the
        contingencies at scale * keepvec, each judged by CapacityStudy._check (same baseline, same _ok)."""
        allc = self._allc(conts)
        a = np.asarray(scale, float)
        ok_b, _ = self.cs._check(requests, a, allc, np.array([0]))
        if len(allc) == 1:
            return bool(ok_b.all())
        ok_c, _ = self.cs._check(requests, a * np.asarray(keepvec, float), allc, np.arange(1, len(allc)))
        return bool(ok_b.all() and ok_c.all())

    def best_subset_flexible(self, requests, conts, flexible_idx, keep, max_k=10, relax=True):
        """Best subset when the requests in flexible_idx are at full size in the base case and at `keep` times their
        size after any outage. relax=True (the option): the plain best subset stays available, so only subsets above
        it are searched. relax=False: the plain search order from the empty floor under the flexible rule alone."""
        requests = [dict(r) for r in requests]
        flexible = sorted({int(j) for j in flexible_idx})
        keepvec = np.ones(len(requests))
        keepvec[flexible] = float(keep)
        plain = self.plain_subset(requests, conts)
        hot = []
        ok = lambda a: self._passes(self.cs, requests, a, keepvec, conts, hot)
        if relax:
            ex = self._search(requests, ok, plain["mw"], max_k=max_k)
        else:
            ex = self._search(requests, ok, 0.0, max_k=max_k)
            if ex["admitted"] is None:
                ex.update(admitted=[], mw=0.0)
        used = ex["admitted"] is not None and (not relax or ex["mw"] > plain["mw"] + 1e-9)
        out = dict(rule="flexible", keep=float(keep), flexible=flexible, keep_vector=keepvec.tolist(),
                   checks=int(ex["checks"]), option_used=bool(relax and used))
        if ex["admitted"] is None:
            out.update(admitted=list(plain["admitted"]), mw=float(plain["mw"]))
        else:
            out.update(admitted=list(ex["admitted"]), mw=float(ex["mw"]))
        out["gain_mw"] = float(out["mw"] - plain["mw"])
        return out

    def best_subset_storage(self, requests, conts, battery_frac, max_k=10):
        """Battery of battery_frac x the load at every load request: the load's contingency size is its size minus
        the battery MW (keep = 1 - battery_frac, loads only)."""
        loads = [j for j, r in enumerate(requests) if r["kind"] == "load"]
        out = self.best_subset_flexible(requests, conts, loads, max(0.0, 1.0 - float(battery_frac)), max_k=max_k)
        out.update(rule="storage", battery_frac=float(battery_frac))
        return out

    def best_subset_ras(self, requests, conts, keep=0.0, max_k=10):
        """Remedial action scheme on every generation request: cut to `keep` of its size after any outage."""
        gens = [j for j, r in enumerate(requests) if r["kind"] == "gen"]
        out = self.best_subset_flexible(requests, conts, gens, keep, max_k=max_k)
        out.update(rule="ras")
        return out

    def recheck_flexible(self, rec, requests=None, conts=None):
        requests = self.requests if requests is None else requests
        conts = self.conts if conts is None else conts
        a = self._vec(rec["admitted"], len(requests))
        if rec.get("option_used"):
            return self.secure_flexible(requests, a, conts, rec["keep_vector"])
        return bool(self.cs.secure(requests, a, conts)[0])

    # ------------------------------------------------------------------ one switching action
    def binding_case(self):
        """The plain subset's binding case: the case that fails worst (CapacityStudy._binding) when every request
        is added at full size. None if the whole cluster passes."""
        allc = self._allc(self.conts)
        ok, r = self.cs._check(self.requests, np.ones(len(self.requests)), allc)
        if ok.all():
            return None
        bad = np.nonzero(~ok)[0]
        i = int(bad[np.argmax(r["max_loading"][bad])])
        b = self.cs._binding(r, ok, allc)
        b["index"] = i
        return b

    def switched(self, branch_idx):
        """A CapacityStudy on a copy of the engine with branch `branch_idx` open (status 0 in a copied input, a new
        Power Grid Model). The original Engine and its input arrays are not touched. Branch indexing is unchanged,
        so the same contingency tuples apply; outaging the already-open branch is the switched base case."""
        k = int(branch_idx)
        if k not in self._sw:
            e2 = copy.copy(self.eng)
            inp = dict(self.eng.input)
            gb = inp["generic_branch"].copy()
            pos = int(np.nonzero(gb["id"] == self.eng.branches[k]["id"])[0][0])
            gb["from_status"][pos] = 0
            gb["to_status"][pos] = 0
            inp["generic_branch"] = gb
            e2.input = inp
            e2.model = PowerGridModel(inp)
            if len(self._sw) > 4:
                self.sw_solves += sum(c.solves for c in self._sw.values())
                self._sw.clear()
            self._sw[k] = CapacityStudy(e2, self.buses)
        return self._sw[k]

    def _islanding(self, k, conts):
        """True if opening branch k islands the grid, or makes any contingency in `conts` island it."""
        G = nx.MultiGraph()
        for i, b in enumerate(self.eng.branches):
            G.add_node(b["f"]); G.add_node(b["t"])
            if i != k:
                G.add_edge(b["f"], b["t"], key=i)
        if not nx.is_connected(G):
            return True
        H = nx.Graph()
        H.add_nodes_from(G.nodes)
        mult = {}
        for u, v, i in G.edges(keys=True):
            e = frozenset((u, v)); mult[e] = mult.get(e, 0) + 1; H.add_edge(u, v)
        bridges = {frozenset(e) for e in nx.bridges(H) if mult[frozenset(e)] == 1}
        for c in conts:
            for i in c:
                if i != k and frozenset((self.eng.branches[i]["f"], self.eng.branches[i]["t"])) in bridges:
                    if len(c) == 1:
                        return True
            if len(c) > 1:
                H2 = G.copy()
                for i in c:
                    if i != k:
                        H2.remove_edge(self.eng.branches[i]["f"], self.eng.branches[i]["t"], key=i)
                if not nx.is_connected(H2):
                    return True
        return False

    def secure_switched(self, branch_idx, scale, conts=None):
        """Independent re-check through CapacityStudy._evaluate on the switched engine, judged by CapacityStudy._ok
        against the original grid's no-request baseline."""
        conts = self.conts if conts is None else conts
        allc = self._allc(conts)
        cs2 = self.switched(branch_idx)
        r = cs2._evaluate(self.requests, np.asarray(scale, float), allc)
        return bool(self.cs._ok(r, self.cs._baseline(allc)).all())

    def best_switch(self, top=20, max_k=10, only=None):
        """Open one branch for good. Every eligible candidate among the `top` most loaded branches in the binding
        case gets the exact subset search above the best MW found so far (plain subset first), so the reported switch
        is the exact best among the candidates. `only` restricts the candidates (used by tests)."""
        plain = self.plain
        a = self._vec(plain["admitted"], len(self.requests))
        bind = self.binding_case()
        res = dict(rule="switch", mw=float(plain["mw"]), gain_mw=0.0, admitted=list(plain["admitted"]),
                   branch=None, option_used=False, binding_case=None, candidates=[], skipped_islanding=0)
        if bind is None:
            return res
        allc = self._allc(self.conts)
        res["binding_case"] = bind["contingency"]
        _, out = self._eval_rows(self.cs, self.requests, a[None, :], [allc[bind["index"]]])
        loading = np.nan_to_num(out["generic_branch"]["loading"][0], nan=0.0)
        pos = {int(i): j for j, i in enumerate(self.cs.input["generic_branch"]["id"])}
        lb = np.array([loading[pos[b["id"]]] for b in self.eng.branches])
        if bind["index"] > 0:
            for i in allc[bind["index"]]:
                lb[i] = -1.0     # an outaged branch carries nothing; opening it is not a new action
        cand = [int(i) for i in np.argsort(-lb)[:int(top)]]
        if only is not None:
            cand = [int(i) for i in only]
        best_mw, ones = float(plain["mw"]), np.ones(len(self.requests))
        for k in cand:
            b = self.eng.branches[k]
            row = dict(branch=k, branch_id=int(b["id"]), from_bus=int(b["f"]), to_bus=int(b["t"]),
                       loading=float(lb[k]))
            if self._islanding(k, self.conts):
                row["skipped"] = "islanding"
                res["skipped_islanding"] += 1
                res["candidates"].append(row)
                continue
            cs2 = self.switched(k)
            hot = []
            ok = lambda s, cs2=cs2, hot=hot: self._passes(cs2, self.requests, s, ones, self.conts, hot)
            ex = self._search(self.requests, ok, best_mw, max_k=max_k)
            row.update(checks=int(ex["checks"]), mw=ex["mw"])
            if ex["admitted"] is not None:
                best_mw = ex["mw"]
                res.update(mw=float(ex["mw"]), admitted=list(ex["admitted"]), branch=k, branch_id=int(b["id"]),
                           from_bus=int(b["f"]), to_bus=int(b["t"]), option_used=True)
            res["candidates"].append(row)
        res["gain_mw"] = float(res["mw"] - plain["mw"])
        return res

    def recheck_switch(self, rec):
        a = self._vec(rec["admitted"], len(self.requests))
        if rec.get("option_used"):
            return self.secure_switched(rec["branch"], a)
        return bool(self.cs.secure(self.requests, a, self.conts)[0])

    # ------------------------------------------------------------------ partial MW
    def partial_mw(self, tol=0.01):
        """Left-out requests scaled one at a time, largest first, on top of the admitted set and the partial MW
        already granted (bisection to `tol` of the request; every step a full CapacityStudy.secure check)."""
        plain = self.plain
        k = len(self.requests)
        sc = self._vec(plain["admitted"], k)
        excluded = sorted((j for j in range(k) if j not in set(plain["admitted"])), key=lambda j: -self.requests[j]["mw"])
        recs = []
        for j in excluded:
            def ok(s):
                x = sc.copy(); x[j] = s
                return self.cs.secure(self.requests, x, self.conts)[0]
            if ok(1.0):
                t = 1.0       # can only happen if the plain subset was not optimal; kept for completeness
            else:
                lo, hi = 0.0, 1.0
                while hi - lo > tol:
                    mid = 0.5 * (lo + hi)
                    if ok(mid):
                        lo = mid
                    else:
                        hi = mid
                t = lo
            sc[j] = t
            r = self.requests[j]
            recs.append(dict(index=int(j), bus=r["bus"], kind=r["kind"], mw=r["mw"], t=float(t), extra_mw=float(t * r["mw"])))
        extra = float(sum(x["extra_mw"] for x in recs))
        return dict(rule="partial", mw=float(plain["mw"] + extra), gain_mw=extra, admitted=list(plain["admitted"]),
                    per_request=recs, scale=sc.tolist(), option_used=extra > 0, tol=float(tol))

    def recheck_partial(self, rec):
        return bool(self.cs.secure(self.requests, np.asarray(rec["scale"], float), self.conts)[0])

    # ------------------------------------------------------------------ everything for one cluster
    def record(self, top=20, max_k=10, tol=0.01):
        """Every option for this cluster: MW, gain over the plain best subset, and a re-check of the admitted set
        under the option's own rule (independent code path where one exists)."""
        reqs, conts = self.requests, self.conts
        plain = self.plain
        total = float(sum(r["mw"] for r in reqs))
        loads = [j for j, r in enumerate(reqs) if r["kind"] == "load"]
        gens = [j for j, r in enumerate(reqs) if r["kind"] == "gen"]
        out = dict(plain=dict(admitted=list(plain["admitted"]), mw=float(plain["mw"]), checks=int(plain["checks"]),
                              recheck=bool(self.cs.secure(reqs, self._vec(plain["admitted"], len(reqs)), conts)[0])),
                   total_mw=total, fits=bool(plain["mw"] >= total - 1e-9), options={})
        o = out["options"]

        def same(note):
            return dict(mw=float(plain["mw"]), gain_mw=0.0, admitted=list(plain["admitted"]), option_used=False,
                        recheck=out["plain"]["recheck"], note=note)

        if out["fits"]:
            for n in ("flex_load_50", "flex_load_0", "storage_25", "storage_50", "ras_gen_0", "switch", "partial"):
                o[n] = same("cluster fits: nothing to gain")
            return out
        for name, idx, keep in (("flex_load_50", loads, 0.5), ("flex_load_0", loads, 0.0), ("storage_25", loads, 0.75),
                                ("ras_gen_0", gens, 0.0)):
            if not idx:
                o[name] = same("no request of this kind in the cluster")
                continue
            rec = self.best_subset_flexible(reqs, conts, idx, keep, max_k=max_k)
            rec["recheck"] = self.recheck_flexible(rec)
            o[name] = rec
        o["storage_50"] = dict(o["flex_load_50"], note="same rule as flex_load_50 (keep 0.5 on loads after an outage)")
        sw = self.best_switch(top=top, max_k=max_k)
        sw["recheck"] = self.recheck_switch(sw)
        o["switch"] = sw
        pt = self.partial_mw(tol=tol)
        pt["recheck"] = self.recheck_partial(pt)
        o["partial"] = pt
        out["solves"] = int(self.cs.solves + self.sw_solves + sum(c.solves for c in self._sw.values()))
        return out
