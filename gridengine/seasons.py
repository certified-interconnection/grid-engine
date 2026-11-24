"""Three simple, public load cases derived from a base case.

These are stated modelling choices, not PJM's cases:

``summer_peak``
    Every load exactly as in the base case (factor 1.00). Generators unchanged.
``winter_peak``
    Load active power times 0.90, and each load's reactive power reset so the
    load power factor is 0.97, keeping the direction (inductive or capacitive)
    of the base case reactive power. Generators unchanged.
``light_load``
    Load active and reactive power times 0.55. Non-slack generators are
    re-dispatched pro rata: every voltage controlled generator is scaled by the
    same factor, chosen so total scheduled generation equals 0.55 of the base
    case load. Fixed-Q injections (pandapower sgen) are scaled by 0.55 too.
    The slack source absorbs the losses.

Reactive power limits of the regulated generators are not enforced, matching
pandapower's default power flow.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .cases import Generator, GridCase, Load

SUMMER_PEAK = "summer_peak"
WINTER_PEAK = "winter_peak"
LIGHT_LOAD = "light_load"
SEASON_NAMES = (SUMMER_PEAK, WINTER_PEAK, LIGHT_LOAD)

SUMMER_LOAD_FACTOR = 1.00
WINTER_LOAD_FACTOR = 0.90
WINTER_POWER_FACTOR = 0.97
LIGHT_LOAD_FACTOR = 0.55


def season_parameters() -> dict:
    """The assumptions, as recorded in results files and the README."""
    return {
        SUMMER_PEAK: {"load_factor": SUMMER_LOAD_FACTOR, "power_factor": None, "gen_redispatch": False},
        WINTER_PEAK: {
            "load_factor": WINTER_LOAD_FACTOR,
            "power_factor": WINTER_POWER_FACTOR,
            "gen_redispatch": False,
        },
        LIGHT_LOAD: {"load_factor": LIGHT_LOAD_FACTOR, "power_factor": None, "gen_redispatch": True},
    }


def build_season(case: GridCase, season: str) -> GridCase:
    if season not in SEASON_NAMES:
        raise ValueError(f"unknown season {season!r}, expected one of {SEASON_NAMES}")
    if season == SUMMER_PEAK:
        return replace(case, name=f"{case.name}:{season}")

    if season == WINTER_PEAK:
        tan_phi = math.tan(math.acos(WINTER_POWER_FACTOR))
        loads = []
        for load in case.loads:
            p_mw = load.p_mw * WINTER_LOAD_FACTOR
            if load.q_mvar == 0.0:
                q_mvar = 0.0
            else:
                sign = 1.0 if load.q_mvar > 0 else -1.0
                q_mvar = sign * abs(p_mw) * tan_phi
            loads.append(replace(load, p_mw=p_mw, q_mvar=q_mvar))
        return replace(case, name=f"{case.name}:{season}", loads=loads)

    # light load
    loads = [
        replace(load, p_mw=load.p_mw * LIGHT_LOAD_FACTOR, q_mvar=load.q_mvar * LIGHT_LOAD_FACTOR)
        for load in case.loads
    ]
    base_load_mw = sum(load.p_mw for load in case.loads if load.in_service)
    scheduled_gen_mw = sum(
        gen.p_mw for gen in case.generators if gen.in_service and gen.voltage_controlled
    )
    if scheduled_gen_mw > 0.0:
        gen_factor = LIGHT_LOAD_FACTOR * base_load_mw / scheduled_gen_mw
    else:
        gen_factor = 0.0
    generators: list[Generator] = []
    for gen in case.generators:
        if gen.voltage_controlled:
            generators.append(replace(gen, p_mw=gen.p_mw * gen_factor))
        else:
            generators.append(
                replace(
                    gen,
                    p_mw=gen.p_mw * LIGHT_LOAD_FACTOR,
                    q_mvar=gen.q_mvar * LIGHT_LOAD_FACTOR,
                )
            )
    return replace(
        case,
        name=f"{case.name}:{season}",
        loads=loads,
        generators=generators,
    )
