"""Batch AC power flow and short circuit on Power Grid Model.

    eng = Engine(net)                       # pandapower net (any season)
    res = eng.contingency_analysis(p1(eng.branches))
    res["secure"]                           # per contingency: no branch over 100% loading, voltages in band
"""
from __future__ import annotations

import time
import numpy as np
from power_grid_model import (CalculationInitialization, CalculationMethod, CalculationType, ComponentType, DatasetType, PowerGridModel,
                              initialize_array)
from power_grid_model.errors import PowerGridBatchError

from .contingencies import branch_table

V_BAND = (0.90, 1.10)


U_NODE = 100e3   # every node at 100 kV; impedances converted on a 100 MVA / 100 ohm base (as in PGM's own IEEE cases)


def _convert(case):
    """MATPOWER arrays -> Power Grid Model input. Branches become generic_branch (tap ratio, phase shift and
    RATE_A kept), PV generators sym_gen + voltage_regulator, the slack a stiff source, fixed shunts as shunt.
    All nodes at 100 kV on a 100 MVA base, as in Power Grid Model's own IEEE validation cases."""
    bus, gen, br = case["bus"], case["gen"], case["branch"]
    mva = case["baseMVA"]
    zb = U_NODE ** 2 / (mva * 1e6)
    nb = bus.shape[0]
    node = initialize_array(DatasetType.input, ComponentType.node, nb)
    node["id"] = np.arange(nb); node["u_rated"] = U_NODE
    brr = br[br[:, 10] > 0]
    gb = initialize_array(DatasetType.input, ComponentType.generic_branch, len(brr))
    gb["id"] = 100000 + np.arange(len(brr))
    gb["from_node"] = brr[:, 0].astype(int); gb["to_node"] = brr[:, 1].astype(int)
    gb["from_status"] = 1; gb["to_status"] = 1
    gb["r1"] = brr[:, 2] * zb; gb["x1"] = brr[:, 3] * zb; gb["g1"] = 0.0; gb["b1"] = brr[:, 4] / zb
    gb["k"] = np.where(brr[:, 8] != 0, brr[:, 8], 1.0); gb["theta"] = np.deg2rad(brr[:, 9])
    gb["sn"] = np.where(brr[:, 5] > 0, brr[:, 5] * 1e6, 1e15)
    ld = bus[(bus[:, 2] != 0) | (bus[:, 3] != 0)]
    load = initialize_array(DatasetType.input, ComponentType.sym_load, len(ld))
    load["id"] = 200000 + ld[:, 0].astype(int); load["node"] = ld[:, 0].astype(int); load["status"] = 1; load["type"] = 0
    load["p_specified"] = ld[:, 2] * 1e6; load["q_specified"] = ld[:, 3] * 1e6
    ref = int(np.nonzero(bus[:, 1] == 3)[0][0])
    g_on = gen[gen[:, 7] > 0]
    pv = sorted(set(g_on[:, 0].astype(int)) - {ref})
    sg = initialize_array(DatasetType.input, ComponentType.sym_gen, len(pv))
    vr = initialize_array(DatasetType.input, ComponentType.voltage_regulator, len(pv))
    for k, b in enumerate(pv):
        rows = g_on[g_on[:, 0] == b]
        sg["id"][k] = 300000 + b; sg["node"][k] = b; sg["status"][k] = 1; sg["type"][k] = 0
        sg["p_specified"][k] = rows[:, 1].sum() * 1e6; sg["q_specified"][k] = 0.0
        vr["id"][k] = 400000 + b; vr["regulated_object"][k] = 300000 + b; vr["status"][k] = 1; vr["u_ref"][k] = rows[0, 5]
    src = initialize_array(DatasetType.input, ComponentType.source, 1)
    src["id"] = 600000; src["node"] = ref; src["status"] = 1
    src["u_ref"] = g_on[g_on[:, 0] == ref][0, 5] if (g_on[:, 0] == ref).any() else bus[ref, 7]
    src["sk"] = 1e40; src["rx_ratio"] = 0.1; src["z01_ratio"] = 1.0
    shb = bus[(bus[:, 4] != 0) | (bus[:, 5] != 0)]
    sh = initialize_array(DatasetType.input, ComponentType.shunt, len(shb))
    sh["id"] = 500000 + shb[:, 0].astype(int); sh["node"] = shb[:, 0].astype(int); sh["status"] = 1
    sh["g1"] = shb[:, 4] / mva / zb; sh["b1"] = shb[:, 5] / mva / zb; sh["g0"] = sh["g1"]; sh["b0"] = sh["b1"]
    data = {"node": node, "generic_branch": gb, "sym_load": load, "source": src}
    if pv:
        data["sym_gen"] = sg; data["voltage_regulator"] = vr
    if len(shb):
        data["shunt"] = sh
    return data


class Engine:
    def __init__(self, case, v_band=V_BAND):
        """case: dict from load_case (optionally passed through apply_season)."""
        self.case = case
        self.input = _convert(case)
        self.model = PowerGridModel(self.input)
        self.branches = branch_table(self.input)
        self.v_band = v_band
        self.init = CalculationInitialization.flat   # PGM's default (linear) start diverges on some outage cases
        self.ratings = "published"
        if (self.input["generic_branch"]["sn"] >= 1e14).any():
            self._synthetic_ratings()

    def _synthetic_ratings(self, margin=0.7):
        """For branches with no published rating (RATE_A = 0), set rating = worst apparent power over the base case
        and every single-branch outage, divided by `margin`. A stated, reproducible rule (not a real thermal limit)."""
        from .contingencies import p1
        gb = self.input["generic_branch"]
        base = self.model.calculate_power_flow(calculation_method=CalculationMethod.newton_raphson, error_tolerance=1e-8,
                                               max_iterations=30, calculation_initialization=self.init)
        worst = np.maximum(base["generic_branch"]["s_from"], base["generic_branch"]["s_to"])
        conts = p1(self.branches)
        for s in range(0, len(conts), 500):
            upd = self._update(conts[s:s + 500])
            out = self.model.calculate_power_flow(update_data=upd, calculation_method=CalculationMethod.newton_raphson,
                                                  error_tolerance=1e-8, max_iterations=30, continue_on_batch_error=True,
                                                  calculation_initialization=self.init)
            sb = np.nan_to_num(np.maximum(out["generic_branch"]["s_from"], out["generic_branch"]["s_to"]), nan=0.0)
            worst = np.maximum(worst, sb.max(axis=0))
        missing = gb["sn"] >= 1e14
        rating = np.maximum(worst / margin, 0.2 * np.median(worst[worst > 0]) / margin)
        gb["sn"][missing] = rating[missing]
        self.model = PowerGridModel(self.input)
        # write the ratings back into the case (MVA, RATE_A column) so seasonal variants reuse the same limits
        on = np.nonzero(self.case["branch"][:, 10] > 0)[0]
        self.case["branch"][on, 5] = gb["sn"] / 1e6
        self.ratings = f"synthetic: worst N-1 flow / {margin} for {int(missing.sum())} unrated branches"

    # ------------------------------------------------------------------ power flow
    def base_case(self):
        out = self.model.calculate_power_flow(calculation_method=CalculationMethod.newton_raphson, error_tolerance=1e-8,
                                              max_iterations=30, calculation_initialization=self.init)
        return self._summarize(out, single=True)

    def contingency_analysis(self, contingencies, chunk=500):
        """contingencies: list of tuples of indices into self.branches. Returns per-contingency arrays."""
        t0 = time.perf_counter()
        parts = []
        for s in range(0, len(contingencies), chunk):
            parts.append(self._batch(contingencies[s:s + chunk]))
        res = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]} if parts else {}
        res["seconds"] = time.perf_counter() - t0
        res["n"] = len(contingencies)
        return res

    def _update(self, conts):
        n = len(conts)
        update = {}
        for comp in ("generic_branch",):
            ids = self.input[comp]["id"]
            arr = initialize_array(DatasetType.update, comp, (n, len(ids)))
            arr["id"] = ids[None, :]
            arr["from_status"] = self.input[comp]["from_status"][None, :]
            arr["to_status"] = self.input[comp]["to_status"][None, :]
            pos = {int(i): k for k, i in enumerate(ids)}
            for s_, c in enumerate(conts):
                for bi in c:
                    b = self.branches[bi]
                    arr["from_status"][s_, pos[b["id"]]] = 0
                    arr["to_status"][s_, pos[b["id"]]] = 0
            update[comp] = arr
        return update

    def _batch(self, conts):
        n = len(conts)
        update = self._update(conts)
        failed = np.zeros(n, dtype=bool)
        try:
            out = self.model.calculate_power_flow(update_data=update, calculation_method=CalculationMethod.newton_raphson,
                                                  error_tolerance=1e-8, max_iterations=30, continue_on_batch_error=True,
                                                  calculation_initialization=self.init)
        except PowerGridBatchError as e:
            out = e.output if hasattr(e, "output") else None
            failed[np.asarray(e.failed_scenarios, dtype=int)] = True
            if out is None:
                raise
        return self._summarize(out, single=False, failed=failed)

    def _summarize(self, out, single, failed=None):
        u = out["node"]["u_pu"]
        loads = []
        for comp in ("generic_branch",):
            if comp in out:
                l = out[comp]["loading"]
                loads.append(l)
        L = np.concatenate(loads, axis=-1)
        if single:
            u, L = u[None, :], L[None, :]
        L = np.nan_to_num(L, nan=0.0)
        vmin, vmax, lmax = u.min(axis=1), u.max(axis=1), L.max(axis=1)
        conv = np.isfinite(vmin) & (vmin > 0)
        if failed is not None:
            conv &= ~failed
        secure = conv & (lmax <= 1.0 + 1e-9) & (vmin >= self.v_band[0]) & (vmax <= self.v_band[1])
        return dict(converged=conv, secure=secure, max_loading=lmax, vmin=vmin, vmax=vmax,
                    n_overloaded=(L > 1.0 + 1e-9).sum(axis=1))

    # ------------------------------------------------------------------ short circuit
    def short_circuit(self, nodes=None):
        """Three-phase fault current (kA) at each node, one batch scenario per faulted node."""
        node_ids = self.input["node"]["id"] if nodes is None else np.asarray(nodes)
        n = len(node_ids)
        fault = initialize_array(DatasetType.input, ComponentType.fault, 1)
        fault["id"] = int(max(int(self.input[c]["id"].max()) for c in self.input if len(self.input[c])) + 1)
        fault["status"] = 0
        fault["fault_type"] = 0          # three phase
        fault["fault_object"] = int(node_ids[0])
        data = dict(self.input); data["fault"] = fault
        m = PowerGridModel(data)
        upd = initialize_array(DatasetType.update, ComponentType.fault, (n, 1))
        upd["id"] = fault["id"][0]; upd["status"] = 1; upd["fault_object"] = node_ids[:, None]
        out = m.calculate_short_circuit(update_data={"fault": upd})
        return dict(node=node_ids, i_f_ka=out["fault"]["i_f"][:, 0, 0] / 1e3 if out["fault"]["i_f"].ndim == 3 else out["fault"]["i_f"][:, 0] / 1e3)
