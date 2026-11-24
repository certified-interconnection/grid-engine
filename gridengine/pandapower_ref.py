"""Build a pandapower network from a neutral case.

This exists so that MATPOWER cases, which have no native pandapower model, can
still be cross-checked and timed against pandapower. It is a reference path
only: the engine is Power Grid Model.
"""

from __future__ import annotations

import math

import pandapower as pp

from .cases import GridCase


def to_pandapower(case: GridCase):
    net = pp.create_empty_network(sn_mva=case.base_mva, f_hz=case.freq_hz)
    bus_index: dict[int, int] = {}
    vn_kv: dict[int, float] = {}
    for bus in case.buses:
        bus_index[bus.id] = pp.create_bus(net, vn_kv=bus.vn_kv, name=bus.name)
        vn_kv[bus.id] = bus.vn_kv

    for branch in case.branches:
        if not branch.in_service:
            continue
        from_bus = bus_index[branch.from_bus]
        to_bus = bus_index[branch.to_bus]
        if branch.kind == "line":
            pp.create_line_from_parameters(
                net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=1.0,
                r_ohm_per_km=branch.r_ohm,
                x_ohm_per_km=branch.x_ohm,
                c_nf_per_km=branch.c_farad * 1e9,
                max_i_ka=branch.i_n_a / 1e3,
                name=branch.name,
            )
        elif branch.kind == "generic_branch":
            sn_mva = branch.rate_mva
            vk = math.hypot(branch.r_ohm, branch.x_ohm) * sn_mva / vn_kv[branch.from_bus] ** 2 * 100.0
            vkr = branch.r_ohm * sn_mva / vn_kv[branch.from_bus] ** 2 * 100.0
            if abs(branch.tap_ratio - 1.0) < 1e-12 and abs(branch.shift_degree) < 1e-12:
                pp.create_line_from_parameters(
                    net,
                    from_bus=from_bus,
                    to_bus=to_bus,
                    length_km=1.0,
                    r_ohm_per_km=branch.r_ohm,
                    x_ohm_per_km=branch.x_ohm,
                    c_nf_per_km=branch.b_siemens / (2.0 * math.pi * case.freq_hz) * 1e9,
                    max_i_ka=sn_mva / (math.sqrt(3.0) * vn_kv[branch.from_bus]),
                    name=branch.name,
                )
            else:
                pp.create_transformer_from_parameters(
                    net,
                    hv_bus=from_bus,
                    lv_bus=to_bus,
                    sn_mva=sn_mva,
                    vn_hv_kv=vn_kv[branch.from_bus],
                    vn_lv_kv=vn_kv[branch.from_bus] / branch.tap_ratio,
                    vk_percent=vk,
                    vkr_percent=vkr,
                    pfe_kw=0.0,
                    i0_percent=0.0,
                    shift_degree=branch.shift_degree,
                    name=branch.name,
                )
        elif branch.kind == "transformer":
            pp.create_transformer_from_parameters(
                net,
                hv_bus=from_bus,
                lv_bus=to_bus,
                sn_mva=branch.sn_mva,
                vn_hv_kv=branch.u1_kv,
                vn_lv_kv=branch.u2_kv,
                vk_percent=branch.vk_percent,
                vkr_percent=branch.vkr_percent,
                pfe_kw=0.0,
                i0_percent=0.0,
                shift_degree=branch.shift_degree,
                name=branch.name,
            )
        else:
            raise ValueError(f"unknown branch kind {branch.kind!r}")

    for shunt in case.shunts:
        if not shunt.in_service:
            continue
        pp.create_shunt(
            net,
            bus=bus_index[shunt.bus],
            q_mvar=shunt.q_mvar,
            p_mw=shunt.p_mw,
            name=shunt.name,
        )

    for load in case.loads:
        if not load.in_service:
            continue
        pp.create_load(net, bus=bus_index[load.bus], p_mw=load.p_mw, q_mvar=load.q_mvar, name=load.name)

    for gen in case.generators:
        if not gen.in_service:
            continue
        if gen.voltage_controlled:
            pp.create_gen(
                net,
                bus=bus_index[gen.bus],
                p_mw=gen.p_mw,
                vm_pu=gen.vm_pu,
                min_q_mvar=gen.q_min_mvar,
                max_q_mvar=gen.q_max_mvar,
                name=gen.name,
            )
        else:
            pp.create_sgen(net, bus=bus_index[gen.bus], p_mw=gen.p_mw, q_mvar=gen.q_mvar, name=gen.name)

    for source in case.sources:
        pp.create_ext_grid(
            net,
            bus=bus_index[source.bus],
            vm_pu=source.vm_pu,
            va_degree=source.va_degree,
            name=source.name,
        )
    return net


def run_pandapower(case: GridCase, net=None, angle: bool = True):
    net = to_pandapower(case) if net is None else net
    pp.runpp(
        net,
        calculate_voltage_angles=angle,
        tolerance_mva=1e-8,
        max_iteration=50,
        init="auto",
    )
    return net
