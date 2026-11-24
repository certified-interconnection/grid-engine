"""Convert a neutral case to Power Grid Model input and run batch power flows."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from power_grid_model import (
    BranchSide,
    LoadGenType,
    PowerGridModel,
    WindingType,
    initialize_array,
)

from .cases import GridCase

SECURE_VM_MIN = 0.9
SECURE_VM_MAX = 1.1
SECURE_LOADING_MAX = 1.0

#: Stand-in for "no reactive limits" on a regulated generator. PGM needs finite
#: bounds; these are far outside any feasible operating point.
Q_LIMIT_DISABLED = 1e12

#: Power Grid Model puts the source's short-circuit impedance in series with the
#: slack. For a power flow the slack must be an ideal voltage source, so the
#: power flow build uses this very large short-circuit power (1e18 VA). The
#: short-circuit module passes its own, much smaller, documented value instead.
IDEAL_SOURCE_SK_MVA = 1e12

BRANCH_COMPONENTS = ("line", "transformer", "generic_branch")

_PF_OPTIONS = dict(
    symmetric=True,
    calculation_method="newton_raphson",
    error_tolerance=1e-8,
    max_iterations=50,
    continue_on_batch_error=True,
)


@dataclass
class ModelInput:
    """PGM input dataset plus the index maps needed to read results back."""

    data: dict
    bus_ids: list[int]
    branch_ids: list[int]
    branch_kind: dict[int, str]
    comp_branch_ids: dict[str, list[int]]

    @property
    def n_buses(self) -> int:
        return len(self.bus_ids)

    @property
    def n_branches(self) -> int:
        return len(self.branch_ids)


@dataclass
class PowerFlowResult:
    bus_ids: list[int]
    branch_ids: list[int]
    vm: np.ndarray
    va: np.ndarray
    loading: np.ndarray
    p_from: np.ndarray
    q_from: np.ndarray
    p_to: np.ndarray
    q_to: np.ndarray
    converged: bool = True

    @property
    def max_loading(self) -> float:
        return float(np.nanmax(self.loading)) if self.loading.size else 0.0

    @property
    def min_vm(self) -> float:
        return float(np.nanmin(self.vm))

    @property
    def max_vm(self) -> float:
        return float(np.nanmax(self.vm))


@dataclass
class ContingencyResult:
    """Batch result, one row per contingency."""

    contingency_ids: list[str]
    contingency_kinds: list[str]
    branch_ids: np.ndarray
    bus_ids: np.ndarray
    vm: np.ndarray  # (n_scenarios, n_buses)
    loading: np.ndarray  # (n_scenarios, n_branches)
    max_loading: np.ndarray
    worst_branch_id: np.ndarray
    min_vm: np.ndarray
    max_vm: np.ndarray
    worst_low_bus: np.ndarray
    worst_high_bus: np.ndarray
    secure: np.ndarray
    converged: np.ndarray

    def rows(self) -> list[dict]:
        out = []
        for k, cid in enumerate(self.contingency_ids):
            out.append(
                {
                    "id": cid,
                    "kind": self.contingency_kinds[k],
                    "max_loading": _num(self.max_loading[k]),
                    "worst_branch_id": int(self.worst_branch_id[k]),
                    "min_vm": _num(self.min_vm[k]),
                    "max_vm": _num(self.max_vm[k]),
                    "worst_low_bus": int(self.worst_low_bus[k]),
                    "worst_high_bus": int(self.worst_high_bus[k]),
                    "secure": bool(self.secure[k]),
                    "converged": bool(self.converged[k]),
                }
            )
        return out

    def summary(self) -> dict:
        n = len(self.contingency_ids)
        secure = int(np.sum(self.secure))
        converged = int(np.sum(self.converged))
        return {
            "scenarios": n,
            "secure": secure,
            "insecure": n - secure,
            "not_converged": n - converged,
            "max_loading": _num(np.nanmax(self.max_loading)) if n else None,
            "min_vm": _num(np.nanmin(self.min_vm)) if n else None,
            "max_vm": _num(np.nanmax(self.max_vm)) if n else None,
        }


def _num(value) -> float | None:
    """JSON-safe float (nan becomes None)."""
    if value is None:
        return None
    value = float(value)
    if math.isnan(value):
        return None
    return value


# --------------------------------------------------------------------------- #
# building the PGM input
# --------------------------------------------------------------------------- #


def build_input(
    case: GridCase,
    *,
    enforce_q_limits: bool = False,
    sk_mva: float | None = None,
) -> ModelInput:
    """Turn a :class:`GridCase` into a PGM input dataset.

    Mapping choices:

    * pandapower lines keep their per-km data, so they become ``line`` with the
      rated current ``i_n`` driving the loading percentage.
    * pandapower transformers become ``transformer``; the tap position is folded
      into ``u1``/``u2`` and the magnetizing branch is a separate ``shunt`` on
      the high voltage side, which is exactly how pandapower models it.
    * MATPOWER branches become ``generic_branch`` with the MVA rating as ``sn``,
      so loading is MVA based (MATPOWER rates are MVA, not current).
    * voltage controlled generators become ``sym_gen`` with zero reactive power
      plus a ``voltage_regulator`` that holds ``vm_pu``.
    * the slack source gets ``IDEAL_SOURCE_SK_MVA`` unless ``sk_mva`` is given,
      because PGM includes the source impedance in the power flow.
    """
    bus_vn = {b.id: b.vn_kv * 1e3 for b in case.buses}

    node = initialize_array("input", "node", len(case.buses))
    node["id"] = [b.id for b in case.buses]
    node["u_rated"] = [b.vn_kv * 1e3 for b in case.buses]
    data: dict[str, np.ndarray] = {"node": node}

    by_kind: dict[str, list] = {kind: [] for kind in BRANCH_COMPONENTS}
    for branch in case.branches:
        if branch.in_service:
            by_kind[branch.kind].append(branch)

    comp_branch_ids: dict[str, list[int]] = {kind: [] for kind in BRANCH_COMPONENTS}
    branch_kind: dict[int, str] = {}

    if by_kind["line"]:
        rows = by_kind["line"]
        arr = initialize_array("input", "line", len(rows))
        arr["id"] = [b.id for b in rows]
        arr["from_node"] = [b.from_bus for b in rows]
        arr["to_node"] = [b.to_bus for b in rows]
        arr["from_status"] = 1
        arr["to_status"] = 1
        arr["r1"] = [b.r_ohm for b in rows]
        arr["x1"] = [b.x_ohm for b in rows]
        arr["c1"] = [b.c_farad for b in rows]
        arr["tan1"] = [b.tan1 for b in rows]
        arr["i_n"] = [b.i_n_a for b in rows]
        data["line"] = arr
        comp_branch_ids["line"] = [b.id for b in rows]
        branch_kind.update({b.id: "line" for b in rows})

    if by_kind["transformer"]:
        rows = by_kind["transformer"]
        arr = initialize_array("input", "transformer", len(rows))
        arr["id"] = [b.id for b in rows]
        arr["from_node"] = [b.from_bus for b in rows]
        arr["to_node"] = [b.to_bus for b in rows]
        arr["from_status"] = 1
        arr["to_status"] = 1
        arr["u1"] = [b.u1_kv * 1e3 for b in rows]
        arr["u2"] = [b.u2_kv * 1e3 for b in rows]
        arr["sn"] = [b.sn_mva * 1e6 for b in rows]
        arr["uk"] = [b.vk_percent / 100.0 for b in rows]
        arr["pk"] = [b.vkr_percent / 100.0 for b in rows]
        arr["i0"] = 0.0
        arr["p0"] = 0.0
        arr["winding_from"] = WindingType.wye
        arr["winding_to"] = WindingType.wye
        arr["clock"] = [int(round(b.shift_degree / 30.0)) % 12 for b in rows]
        arr["tap_side"] = BranchSide.from_side
        arr["tap_pos"] = 0
        arr["tap_nom"] = 0
        arr["tap_min"] = 0
        arr["tap_max"] = 0
        arr["tap_size"] = 0.0
        arr["uk_min"] = arr["uk"]
        arr["uk_max"] = arr["uk"]
        arr["pk_min"] = arr["pk"]
        arr["pk_max"] = arr["pk"]
        data["transformer"] = arr
        comp_branch_ids["transformer"] = [b.id for b in rows]
        branch_kind.update({b.id: "transformer" for b in rows})

    if by_kind["generic_branch"]:
        rows = by_kind["generic_branch"]
        arr = initialize_array("input", "generic_branch", len(rows))
        arr["id"] = [b.id for b in rows]
        arr["from_node"] = [b.from_bus for b in rows]
        arr["to_node"] = [b.to_bus for b in rows]
        arr["from_status"] = 1
        arr["to_status"] = 1
        arr["r1"] = [b.r_ohm for b in rows]
        arr["x1"] = [b.x_ohm for b in rows]
        arr["g1"] = 0.0
        arr["b1"] = [b.b_siemens for b in rows]
        arr["k"] = [b.tap_ratio for b in rows]
        arr["theta"] = [math.radians(b.shift_degree) for b in rows]
        arr["sn"] = [b.rate_mva * 1e6 for b in rows]
        data["generic_branch"] = arr
        comp_branch_ids["generic_branch"] = [b.id for b in rows]
        branch_kind.update({b.id: "generic_branch" for b in rows})

    loads = [load for load in case.loads if load.in_service]
    if loads:
        arr = initialize_array("input", "sym_load", len(loads))
        arr["id"] = [load.id for load in loads]
        arr["node"] = [load.bus for load in loads]
        arr["status"] = 1
        arr["type"] = LoadGenType.const_power
        arr["p_specified"] = [load.p_mw * 1e6 for load in loads]
        arr["q_specified"] = [load.q_mvar * 1e6 for load in loads]
        data["sym_load"] = arr

    shunts = [shunt for shunt in case.shunts if shunt.in_service]
    if shunts:
        arr = initialize_array("input", "shunt", len(shunts))
        arr["id"] = [shunt.id for shunt in shunts]
        arr["node"] = [shunt.bus for shunt in shunts]
        arr["status"] = 1
        arr["g1"] = [shunt.p_mw * 1e6 / bus_vn[shunt.bus] ** 2 for shunt in shunts]
        arr["b1"] = [-shunt.q_mvar * 1e6 / bus_vn[shunt.bus] ** 2 for shunt in shunts]
        data["shunt"] = arr

    generators = [gen for gen in case.generators if gen.in_service]
    if generators:
        arr = initialize_array("input", "sym_gen", len(generators))
        arr["id"] = [gen.id for gen in generators]
        arr["node"] = [gen.bus for gen in generators]
        arr["status"] = 1
        arr["type"] = LoadGenType.const_power
        arr["p_specified"] = [gen.p_mw * 1e6 for gen in generators]
        arr["q_specified"] = [0.0 if gen.voltage_controlled else gen.q_mvar * 1e6 for gen in generators]
        data["sym_gen"] = arr

        regulated = [gen for gen in generators if gen.voltage_controlled]
        if regulated:
            reg = initialize_array("input", "voltage_regulator", len(regulated))
            reg["id"] = [10_000_000 + gen.id for gen in regulated]
            reg["regulated_object"] = [gen.id for gen in regulated]
            reg["status"] = 1
            reg["u_ref"] = [gen.vm_pu for gen in regulated]
            if enforce_q_limits:
                reg["q_min"] = [gen.q_min_mvar * 1e6 for gen in regulated]
                reg["q_max"] = [gen.q_max_mvar * 1e6 for gen in regulated]
            else:
                reg["q_min"] = -Q_LIMIT_DISABLED
                reg["q_max"] = Q_LIMIT_DISABLED
            data["voltage_regulator"] = reg

    sources = list(case.sources)
    if not sources:
        raise ValueError(f"{case.name}: no slack source")
    arr = initialize_array("input", "source", len(sources))
    arr["id"] = [source.id for source in sources]
    arr["node"] = [source.bus for source in sources]
    arr["status"] = 1
    arr["u_ref"] = [source.vm_pu for source in sources]
    arr["u_ref_angle"] = [math.radians(source.va_degree) for source in sources]
    arr["sk"] = [(sk_mva if sk_mva is not None else IDEAL_SOURCE_SK_MVA) * 1e6 for source in sources]
    arr["rx_ratio"] = 0.1
    arr["z01_ratio"] = 1.0
    data["source"] = arr

    branch_ids = [bid for kind in BRANCH_COMPONENTS for bid in comp_branch_ids[kind]]
    return ModelInput(
        data=data,
        bus_ids=[b.id for b in case.buses],
        branch_ids=branch_ids,
        branch_kind=branch_kind,
        comp_branch_ids=comp_branch_ids,
    )


def make_model(model_input: ModelInput, freq_hz: float = 50.0) -> PowerGridModel:
    return PowerGridModel(model_input.data, system_frequency=freq_hz)


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #


def _collect(mi: ModelInput, result: dict, n_scen: int | None) -> dict[str, np.ndarray]:
    """Stack per-component branch outputs into flat (n_scenarios, n_branches) arrays."""
    stacked: dict[str, list[np.ndarray]] = {key: [] for key in ("loading", "p_from", "q_from", "p_to", "q_to")}
    for comp in BRANCH_COMPONENTS:
        if comp not in mi.data:
            continue
        out = result[comp]
        for key in stacked:
            values = np.asarray(out[key])
            stacked[key].append(values.reshape(-1) if n_scen is None else values)
    if n_scen is None:
        return {key: (np.concatenate(parts) if parts else np.zeros(0)) for key, parts in stacked.items()}
    if not stacked["loading"]:
        zeros = np.zeros((n_scen, 0))
        return {key: zeros.copy() for key in stacked}
    return {key: np.concatenate(parts, axis=1) for key, parts in stacked.items()}


def run_power_flow(case: GridCase, *, enforce_q_limits: bool = False) -> PowerFlowResult:
    """Single intact AC power flow."""
    mi = build_input(case, enforce_q_limits=enforce_q_limits)
    model = make_model(mi, case.freq_hz)
    result = model.calculate_power_flow(**_PF_OPTIONS)
    node = result["node"]
    branches = _collect(mi, result, n_scen=None)
    return PowerFlowResult(
        bus_ids=mi.bus_ids,
        branch_ids=mi.branch_ids,
        vm=np.asarray(node["u_pu"], dtype=float),
        va=np.asarray(node["u_angle"], dtype=float),
        loading=branches["loading"],
        p_from=branches["p_from"],
        q_from=branches["q_from"],
        p_to=branches["p_to"],
        q_to=branches["q_to"],
        converged=bool(np.isfinite(node["u_pu"]).all()),
    )


def run_contingencies(
    case: GridCase,
    contingencies,
    *,
    enforce_q_limits: bool = False,
) -> ContingencyResult:
    """One batch power flow per contingency, branch status switched per scenario."""
    contingencies = list(contingencies)
    if not contingencies:
        raise ValueError("no contingencies given")
    mi = build_input(case, enforce_q_limits=enforce_q_limits)
    model = make_model(mi, case.freq_hz)
    update = branch_status_update(mi, contingencies)
    result = model.calculate_power_flow(update_data=update, **_PF_OPTIONS)

    n_scen = len(contingencies)
    branches = _collect(mi, result, n_scen=n_scen)
    node = result["node"]
    vm = np.asarray(node["u_pu"], dtype=float).reshape(n_scen, -1)
    loading = branches["loading"]

    converged = np.isfinite(loading).all(axis=1) & np.isfinite(vm).all(axis=1)
    with np.errstate(invalid="ignore"):
        max_loading = np.nanmax(loading, axis=1) if loading.shape[1] else np.zeros(n_scen)
        worst_branch = np.nanargmax(loading, axis=1) if loading.shape[1] else np.zeros(n_scen, dtype=int)
        min_vm = np.nanmin(vm, axis=1)
        max_vm = np.nanmax(vm, axis=1)
        worst_low = np.nanargmin(vm, axis=1)
        worst_high = np.nanargmax(vm, axis=1)
    branch_ids = np.asarray(mi.branch_ids)
    bus_ids = np.asarray(mi.bus_ids)
    secure = (
        converged
        & (max_loading <= SECURE_LOADING_MAX + 1e-12)
        & (min_vm >= SECURE_VM_MIN - 1e-12)
        & (max_vm <= SECURE_VM_MAX + 1e-12)
    )
    return ContingencyResult(
        contingency_ids=[c.id for c in contingencies],
        contingency_kinds=[c.kind for c in contingencies],
        branch_ids=branch_ids,
        bus_ids=bus_ids,
        vm=vm,
        loading=loading,
        max_loading=max_loading,
        worst_branch_id=branch_ids[worst_branch],
        min_vm=min_vm,
        max_vm=max_vm,
        worst_low_bus=bus_ids[worst_low],
        worst_high_bus=bus_ids[worst_high],
        secure=secure,
        converged=converged,
    )


def branch_status_update(mi: ModelInput, contingencies) -> dict:
    """Sparse batch update switching both ends of every outaged branch to 0."""
    per_comp: dict[str, dict] = {
        comp: {"ids": [], "indptr": [0]} for comp in BRANCH_COMPONENTS if comp in mi.data
    }
    for contingency in contingencies:
        for comp, payload in per_comp.items():
            for branch_id in contingency.branch_ids:
                if mi.branch_kind.get(branch_id) == comp:
                    payload["ids"].append(branch_id)
            payload["indptr"].append(len(payload["ids"]))

    update: dict[str, dict] = {}
    for comp, payload in per_comp.items():
        if not payload["ids"]:
            continue
        arr = initialize_array("update", comp, len(payload["ids"]))
        arr["id"] = payload["ids"]
        arr["from_status"] = 0
        arr["to_status"] = 0
        update[comp] = {
            "indptr": np.asarray(payload["indptr"], dtype=np.int64),
            "data": arr,
        }
    return update
