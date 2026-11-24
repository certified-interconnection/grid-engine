"""Three-phase short-circuit current at every bus with Power Grid Model.

The only voltage sources in the input are the ``source`` components (the slack),
so these currents are the source-driven contribution through the network. PGM's
IEC 60909 calculation is used with the maximum voltage factor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from power_grid_model import CalculationMethod, FaultPhase, FaultType, PowerGridModel, initialize_array

from .cases import GridCase
from .pgm import build_input

#: Default short-circuit power of a slack source when the case gives none.
DEFAULT_SK_MVA = 1000.0


@dataclass
class ShortCircuitResult:
    bus_ids: np.ndarray
    i_f_ka: np.ndarray
    sk_mva: float
    fault_type: str = "three_phase"

    @property
    def max_bus(self) -> int:
        return int(self.bus_ids[int(np.argmax(self.i_f_ka))])

    @property
    def max_current_ka(self) -> float:
        return float(np.max(self.i_f_ka))

    def rows(self) -> list[dict]:
        return [
            {"bus_id": int(bus), "i_f_ka": float(current)}
            for bus, current in zip(self.bus_ids, self.i_f_ka)
        ]


def run_short_circuit(
    case: GridCase,
    *,
    sk_mva: float | None = None,
    fault_type: str = "three_phase",
) -> ShortCircuitResult:
    """Maximum three-phase fault current at every bus."""
    if fault_type != "three_phase":
        raise NotImplementedError("only three-phase faults are reported")
    mi = build_input(case, sk_mva=sk_mva if sk_mva is not None else DEFAULT_SK_MVA)
    model_input = dict(mi.data)

    source_sk = float(np.atleast_1d(model_input["source"]["sk"])[0])

    fault = initialize_array("input", "fault", len(mi.bus_ids))
    fault["id"] = [1_000_000 + bus_id for bus_id in mi.bus_ids]
    fault["status"] = 0
    fault["fault_type"] = FaultType.three_phase
    fault["fault_phase"] = FaultPhase.abc
    fault["fault_object"] = mi.bus_ids
    fault["r_f"] = 0.0
    fault["x_f"] = 0.0
    model_input["fault"] = fault

    model = PowerGridModel(model_input, system_frequency=case.freq_hz)

    indptr = np.arange(len(mi.bus_ids) + 1, dtype=np.int64)
    data = initialize_array("update", "fault", len(mi.bus_ids))
    data["id"] = fault["id"]
    data["status"] = 1
    update = {"fault": {"indptr": indptr, "data": data}}

    result = model.calculate_short_circuit(
        calculation_method=CalculationMethod.iec60909,
        update_data=update,
        continue_on_batch_error=True,
    )
    out = result["fault"]
    current = np.asarray(out["i_f"], dtype=float)
    # PGM returns (n_scenarios, n_faults, n_phases); scenario k energises fault k,
    # so the fault current of bus k is the k-th entry of scenario k.
    if current.ndim == 3:
        current = np.stack([current[i, i, :] for i in range(len(mi.bus_ids))]).max(axis=1)
    elif current.ndim == 2:
        current = np.diagonal(current)
    current = np.asarray(current, dtype=float)
    return ShortCircuitResult(
        bus_ids=np.asarray(mi.bus_ids),
        i_f_ka=current / 1e3,
        sk_mva=source_sk / 1e6,
        fault_type=fault_type,
    )


def theoretical_slack_current_ka(sk_mva: float, vn_kv: float, c: float = 1.0) -> float:
    """Bolted three-phase fault current at a bus fed only by a source of ``sk_mva``.

    ``c`` defaults to 1.0 because Power Grid Model 1.13.217 reports the current
    for the source internal voltage it is given; with ``u_ref = 1.0`` the
    measured value at the source bus is ``sk / (sqrt(3) * u_rated)`` to better
    than 0.1 percent (see ``tests/test_shortcircuit.py``).
    """
    return c * sk_mva / (math.sqrt(3.0) * vn_kv)
