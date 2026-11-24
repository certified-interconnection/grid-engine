"""Case loading: pandapower networks and MATPOWER files into one neutral model.

The neutral model keeps every branch, load, generator and shunt in SI units with
provenance (source table and row index) so that any result can be traced back to
the original data set and re-checked with pandapower.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: pandapower.networks functions we accept by name.
PP_NETWORKS = {
    "case30": "case30",
    "case118": "case118",
    "case300": "case300",
    "case_illinois200": "case_illinois200",
}


class IdAllocator:
    """Give every PGM component a unique, increasing integer id."""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        return value


@dataclass(frozen=True)
class Bus:
    id: int
    name: str
    vn_kv: float


@dataclass(frozen=True)
class Branch:
    """A line, a transformer or a MATPOWER generic branch.

    ``kind`` selects which fields matter:

    * ``line``: ``r_ohm``, ``x_ohm``, ``c_farad``, ``tan1``, ``i_n_a``, ``length_km``
    * ``transformer``: ``sn_mva``, ``u1_kv``, ``u2_kv``, ``vk_percent``,
      ``vkr_percent``, ``shift_degree``, ``tap_ratio``
    * ``generic_branch``: ``r_ohm``, ``x_ohm``, ``b_siemens``, ``tap_ratio``,
      ``shift_degree``, ``rate_mva``
    """

    id: int
    name: str
    from_bus: int
    to_bus: int
    kind: str
    in_service: bool = True
    # line data (total values for the whole branch)
    r_ohm: float = 0.0
    x_ohm: float = 0.0
    c_farad: float = 0.0
    tan1: float = 0.0
    b_siemens: float = 0.0
    i_n_a: float = 0.0
    length_km: float = 0.0
    # transformer data
    sn_mva: float = 0.0
    u1_kv: float = 0.0
    u2_kv: float = 0.0
    vk_percent: float = 0.0
    vkr_percent: float = 0.0
    shift_degree: float = 0.0
    tap_ratio: float = 1.0
    # rating used for the loading percentage
    rate_mva: float = 0.0
    # provenance
    table: str = ""
    index: int = -1


@dataclass(frozen=True)
class Load:
    id: int
    bus: int
    name: str
    p_mw: float
    q_mvar: float
    in_service: bool = True
    table: str = ""
    index: int = -1


@dataclass(frozen=True)
class Shunt:
    """Constant-impedance shunt, powers absorbed at 1.0 pu (positive = absorbed)."""

    id: int
    bus: int
    name: str
    p_mw: float
    q_mvar: float
    in_service: bool = True
    table: str = ""
    index: int = -1


@dataclass(frozen=True)
class Generator:
    """A generator. ``vm_pu`` is None for a fixed-Q injection (pandapower sgen)."""

    id: int
    bus: int
    name: str
    p_mw: float
    vm_pu: float | None = None
    q_mvar: float = 0.0
    q_min_mvar: float = -1e9
    q_max_mvar: float = 1e9
    in_service: bool = True
    table: str = ""
    index: int = -1

    @property
    def voltage_controlled(self) -> bool:
        return self.vm_pu is not None


@dataclass(frozen=True)
class Source:
    """Slack voltage source."""

    id: int
    bus: int
    name: str
    vm_pu: float
    va_degree: float = 0.0
    sk_mva: float = 1000.0
    table: str = ""
    index: int = -1


@dataclass
class GridCase:
    name: str
    base_mva: float
    freq_hz: float
    buses: list[Bus]
    branches: list[Branch]
    loads: list[Load]
    shunts: list[Shunt]
    generators: list[Generator]
    sources: list[Source]
    source_note: str = ""

    @property
    def n_buses(self) -> int:
        return len(self.buses)

    @property
    def n_branches(self) -> int:
        return len(self.branches)

    def bus_map(self) -> dict[int, Bus]:
        return {b.id: b for b in self.buses}

    def branch_map(self) -> dict[int, Branch]:
        return {b.id: b for b in self.branches}

    def in_service_branches(self) -> list[Branch]:
        return [b for b in self.branches if b.in_service]

    def describe(self) -> dict:
        return {
            "name": self.name,
            "buses": len(self.buses),
            "branches": len(self.branches),
            "lines": sum(1 for b in self.branches if b.kind == "line"),
            "transformers": sum(1 for b in self.branches if b.kind == "transformer"),
            "generic_branches": sum(1 for b in self.branches if b.kind == "generic_branch"),
            "loads": len(self.loads),
            "shunts": len(self.shunts),
            "generators": len(self.generators),
            "voltage_controlled_generators": sum(1 for g in self.generators if g.voltage_controlled),
            "sources": len(self.sources),
            "base_mva": self.base_mva,
            "freq_hz": self.freq_hz,
        }


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #


def load_case(name: str) -> GridCase:
    """Load a case by pandapower network name or by MATPOWER file name.

    ``name`` may be ``case30``/``case118``/``case300``/``case_illinois200`` or a
    MATPOWER file name such as ``case_ACTIVSg2000`` (looked up in ``data/``).
    """
    if name in PP_NETWORKS:
        return load_pandapower_case(name)
    stem = name[:-2] if name.endswith(".m") else name
    for candidate in (DATA_DIR / f"{stem}.m", DATA_DIR / stem, Path(name)):
        if candidate.exists():
            return load_matpower(candidate)
    raise ValueError(
        f"unknown case {name!r}: expected one of {sorted(PP_NETWORKS)} or a MATPOWER file in {DATA_DIR}"
    )


def available_cases() -> dict[str, str]:
    """Names that :func:`load_case` can load on this machine."""
    out = {name: "pandapower.networks" for name in PP_NETWORKS}
    if DATA_DIR.is_dir():
        for path in sorted(DATA_DIR.glob("*.m")):
            out[path.stem] = str(path)
    return out


# --------------------------------------------------------------------------- #
# pandapower
# --------------------------------------------------------------------------- #


def load_pandapower_case(name: str) -> GridCase:
    import pandapower.networks as pn

    net = getattr(pn, PP_NETWORKS[name])()
    freq_hz = float(net.get("f_hz", 50.0))
    base_mva = float(net.get("sn_mva", 1.0))

    for table in ("bus", "load", "gen", "sgen", "trafo", "line"):
        if table in net and len(net[table]) and not bool(net[table]["in_service"].all()):
            raise NotImplementedError(f"{name}: out-of-service {table} elements are not supported")

    ids = IdAllocator()
    bus_id = {idx: ids() for idx in net.bus.index}
    buses = [
        Bus(bus_id[idx], str(net.bus.at[idx, "name"]), float(net.bus.at[idx, "vn_kv"]))
        for idx in net.bus.index
    ]

    branches: list[Branch] = []
    for idx in net.line.index:
        row = net.line.loc[idx]
        length = float(row.length_km)
        parallel = float(row.parallel) if "parallel" in row and not _isnan(row.parallel) else 1.0
        df = float(row.df) if "df" in row and not _isnan(row.df) else 1.0
        branches.append(
            Branch(
                id=ids(),
                name=str(row["name"]),
                from_bus=bus_id[int(row.from_bus)],
                to_bus=bus_id[int(row.to_bus)],
                kind="line",
                r_ohm=float(row.r_ohm_per_km) * length / parallel,
                x_ohm=float(row.x_ohm_per_km) * length / parallel,
                c_farad=float(row.c_nf_per_km) * length * parallel * 1e-9,
                tan1=_tan_delta(
                    float(row.g_us_per_km) * length * parallel * 1e-6,
                    float(row.c_nf_per_km) * length * parallel * 1e-9,
                    freq_hz,
                ),
                i_n_a=float(row.max_i_ka) * 1000.0 * df * parallel,
                length_km=length,
                rate_mva=0.0,
                table="line",
                index=int(idx),
            )
        )

    shunts: list[Shunt] = []
    for idx in net.shunt.index:
        row = net.shunt.loc[idx]
        step = float(row.step) if "step" in row and not _isnan(row.step) else 1.0
        shunts.append(
            Shunt(
                id=ids(),
                bus=bus_id[int(row.bus)],
                name=str(row["name"]),
                p_mw=float(row.p_mw) * step,
                q_mvar=float(row.q_mvar) * step,
                table="shunt",
                index=int(idx),
            )
        )

    for idx in net.trafo.index:
        row = net.trafo.loc[idx]
        parallel = float(row.parallel) if not _isnan(row.parallel) else 1.0
        sn_mva = float(row.sn_mva) * parallel
        vn_hv = float(row.vn_hv_kv)
        vn_lv = float(row.vn_lv_kv)
        tap_side = row.tap_side if isinstance(row.tap_side, str) else None
        tap_pos = 0.0 if _isnan(row.tap_pos) else float(row.tap_pos)
        tap_neutral = 0.0 if _isnan(row.tap_neutral) else float(row.tap_neutral)
        tap_step = 0.0 if _isnan(row.tap_step_percent) else float(row.tap_step_percent)
        tap_step_deg = 0.0 if _isnan(row.tap_step_degree) else float(row.tap_step_degree)
        delta = (tap_pos - tap_neutral) * tap_step / 100.0
        shift = float(row.shift_degree) if not _isnan(row.shift_degree) else 0.0
        if tap_side == "hv":
            u1_kv, u2_kv = vn_hv * (1.0 + delta), vn_lv
            shift += (tap_pos - tap_neutral) * tap_step_deg
        elif tap_side == "lv":
            u1_kv, u2_kv = vn_hv, vn_lv * (1.0 + delta)
        else:
            u1_kv, u2_kv = vn_hv, vn_lv
        branches.append(
            Branch(
                id=ids(),
                name=str(row["name"]),
                from_bus=bus_id[int(row.hv_bus)],
                to_bus=bus_id[int(row.lv_bus)],
                kind="transformer",
                sn_mva=sn_mva,
                u1_kv=u1_kv,
                u2_kv=u2_kv,
                vk_percent=float(row.vk_percent) if not _isnan(row.vk_percent) else 0.0,
                vkr_percent=float(row.vkr_percent) if not _isnan(row.vkr_percent) else 0.0,
                shift_degree=shift,
                tap_ratio=u1_kv / vn_hv if vn_hv else 1.0,
                rate_mva=sn_mva,
                table="trafo",
                index=int(idx),
            )
        )
        # magnetizing branch, exactly as pandapower models it (hv side, on vn_hv)
        pfe_mw = float(row.pfe_kw) * parallel / 1000.0
        i0 = abs(float(row.i0_percent)) if not _isnan(row.i0_percent) else 0.0
        s0_mva = i0 / 100.0 * sn_mva
        q0_mvar = math.sqrt(max(s0_mva**2 - pfe_mw**2, 0.0)) if s0_mva else 0.0
        if pfe_mw or q0_mvar:
            shunts.append(
                Shunt(
                    id=ids(),
                    bus=bus_id[int(row.hv_bus)],
                    name=f"{row['name']} magnetizing",
                    p_mw=pfe_mw,
                    q_mvar=q0_mvar,
                    table="trafo_magnetizing",
                    index=int(idx),
                )
            )

    loads: list[Load] = []
    for idx in net.load.index:
        row = net.load.loc[idx]
        if not _isnan(row.const_z_p_percent) and float(row.const_z_p_percent) or not _isnan(
            row.const_i_p_percent
        ) and float(row.const_i_p_percent):
            raise NotImplementedError("only constant-power loads are supported")
        loads.append(
            Load(
                id=ids(),
                bus=bus_id[int(row.bus)],
                name=str(row["name"]),
                p_mw=float(row.p_mw),
                q_mvar=float(row.q_mvar),
                table="load",
                index=int(idx),
            )
        )

    generators: list[Generator] = []
    sources: list[Source] = []
    for idx in net.ext_grid.index:
        row = net.ext_grid.loc[idx]
        sources.append(
            Source(
                id=ids(),
                bus=bus_id[int(row.bus)],
                name=str(row["name"]),
                vm_pu=float(row.vm_pu),
                va_degree=float(row.va_degree) if not _isnan(row.va_degree) else 0.0,
                sk_mva=float(row.get("s_sc_max_mva")) if "s_sc_max_mva" in row and not _isnan(row.get("s_sc_max_mva")) else 1000.0,
                table="ext_grid",
                index=int(idx),
            )
        )
    for idx in net.gen.index:
        row = net.gen.loc[idx]
        if bool(row.get("slack", False)):
            sources.append(
                Source(
                    id=ids(),
                    bus=bus_id[int(row.bus)],
                    name=str(row["name"]),
                    vm_pu=float(row.vm_pu),
                    sk_mva=1000.0,
                    table="gen",
                    index=int(idx),
                )
            )
            continue
        generators.append(
            Generator(
                id=ids(),
                bus=bus_id[int(row.bus)],
                name=str(row["name"]),
                p_mw=float(row.p_mw),
                vm_pu=float(row.vm_pu),
                q_min_mvar=float(row.min_q_mvar) if not _isnan(row.min_q_mvar) else -1e9,
                q_max_mvar=float(row.max_q_mvar) if not _isnan(row.max_q_mvar) else 1e9,
                table="gen",
                index=int(idx),
            )
        )
    for idx in net.sgen.index:
        row = net.sgen.loc[idx]
        generators.append(
            Generator(
                id=ids(),
                bus=bus_id[int(row.bus)],
                name=str(row["name"]),
                p_mw=float(row.p_mw),
                vm_pu=None,
                q_mvar=float(row.q_mvar),
                table="sgen",
                index=int(idx),
            )
        )

    return GridCase(
        name=name,
        base_mva=base_mva,
        freq_hz=freq_hz,
        buses=buses,
        branches=branches,
        loads=loads,
        shunts=shunts,
        generators=generators,
        sources=sources,
        source_note="pandapower.networks",
    )


def _tan_delta(g_siemens: float, c_farad: float, freq_hz: float) -> float:
    """Dielectric loss tangent from a shunt conductance and capacitance."""
    b_siemens = 2.0 * math.pi * freq_hz * c_farad
    if b_siemens <= 0.0:
        return 0.0
    return g_siemens / b_siemens


def _isnan(value) -> bool:
    try:
        return value is None or math.isnan(float(value))
    except (TypeError, ValueError):
        return True


# --------------------------------------------------------------------------- #
# MATPOWER
# --------------------------------------------------------------------------- #


def _mpc_matrix(text: str, name: str) -> list[list[float]]:
    match = re.search(rf"mpc\.{name}\s*=\s*\[(.*?)\];", text, re.S)
    if match is None:
        raise ValueError(f"mpc.{name} not found")
    rows: list[list[float]] = []
    body = re.sub(r"%[^\n]*", "", match.group(1))
    for raw in body.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        values = [float(v) for v in re.split(r"[,\s]+", raw) if v]
        if values:
            rows.append(values)
    return rows


def load_matpower(path: str | Path) -> GridCase:
    """Load a MATPOWER case file into the neutral model.

    Series impedances are given in per unit on ``baseMVA`` and the from-bus
    voltage base; they are converted to ohms with that base. A branch's
    off-nominal ratio becomes ``k = tap * vn_from / vn_to`` because MATPOWER's
    ratio is 1:1 in per unit rather than in kV.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    base_mva_match = re.search(r"mpc\.baseMVA\s*=\s*([0-9eE+\-.]+)", text)
    if base_mva_match is None:
        raise ValueError(f"{path}: mpc.baseMVA not found")
    base_mva = float(base_mva_match.group(1))
    bus_rows = _mpc_matrix(text, "bus")
    gen_rows = _mpc_matrix(text, "gen")
    branch_rows = _mpc_matrix(text, "branch")

    ids = IdAllocator()
    bus_id: dict[int, int] = {}
    buses: list[Bus] = []
    vn_kv: dict[int, float] = {}
    for row in bus_rows:
        number = int(row[0])
        if int(row[1]) == 4:  # isolated bus
            continue
        bus_id[number] = ids()
        vn_kv[number] = float(row[9])
        buses.append(Bus(bus_id[number], f"bus {number}", float(row[9])))

    loads: list[Load] = []
    shunts: list[Shunt] = []
    sources: list[Source] = []
    for row in bus_rows:
        number = int(row[0])
        if number not in bus_id:
            continue
        pd_mw, qd_mvar = float(row[2]), float(row[3])
        gs_mw, bs_mvar = float(row[4]), float(row[5])
        if pd_mw or qd_mvar:
            loads.append(
                Load(
                    id=ids(),
                    bus=bus_id[number],
                    name=f"load at bus {number}",
                    p_mw=pd_mw,
                    q_mvar=qd_mvar,
                    table="bus",
                    index=number,
                )
            )
        if gs_mw or bs_mvar:
            shunts.append(
                Shunt(
                    id=ids(),
                    bus=bus_id[number],
                    name=f"shunt at bus {number}",
                    p_mw=gs_mw,
                    q_mvar=-bs_mvar,
                    table="bus",
                    index=number,
                )
            )
        if int(row[1]) == 3:
            sources.append(
                Source(
                    id=ids(),
                    bus=bus_id[number],
                    name=f"slack at bus {number}",
                    vm_pu=float(row[7]),
                    va_degree=float(row[8]),
                    sk_mva=1000.0,
                    table="bus",
                    index=number,
                )
            )

    generators: list[Generator] = []
    for position, row in enumerate(gen_rows):
        number = int(row[0])
        if number not in bus_id or int(row[7]) == 0:
            continue
        bus_row = next(r for r in bus_rows if int(r[0]) == number)
        if int(bus_row[1]) == 3:
            continue  # slack machine is represented by the source
        generators.append(
            Generator(
                id=ids(),
                bus=bus_id[number],
                name=f"gen {position} at bus {number}",
                p_mw=float(row[1]),
                vm_pu=float(row[5]),
                q_min_mvar=float(row[4]),
                q_max_mvar=float(row[3]),
                table="gen",
                index=position,
            )
        )

    branches: list[Branch] = []
    for position, row in enumerate(branch_rows):
        fbus, tbus = int(row[0]), int(row[1])
        if fbus not in bus_id or tbus not in bus_id:
            continue
        if int(row[10]) == 0:
            continue
        z_base = vn_kv[fbus] ** 2 / base_mva
        ratio = float(row[8]) if len(row) > 8 else 0.0
        tap = ratio if ratio != 0.0 else 1.0
        angle = float(row[9]) if len(row) > 9 else 0.0
        rate_a = float(row[5]) if len(row) > 5 else 0.0
        rate_c = float(row[7]) if len(row) > 7 else 0.0
        rate = rate_a if rate_a > 0 else rate_c
        if rate <= 0:
            raise ValueError(f"{path.name}: branch {position} has no MVA rating")
        branches.append(
            Branch(
                id=ids(),
                name=f"branch {position}",
                from_bus=bus_id[fbus],
                to_bus=bus_id[tbus],
                kind="generic_branch",
                r_ohm=float(row[2]) * z_base,
                x_ohm=float(row[3]) * z_base,
                b_siemens=float(row[4]) / z_base,
                tap_ratio=tap * vn_kv[fbus] / vn_kv[tbus],
                shift_degree=angle,
                rate_mva=rate,
                table="branch",
                index=position,
            )
        )

    return GridCase(
        name=path.stem,
        base_mva=base_mva,
        freq_hz=60.0,
        buses=buses,
        branches=branches,
        loads=loads,
        shunts=shunts,
        generators=generators,
        sources=sources,
        source_note=f"MATPOWER file {path.name}",
    )


def with_name(case: GridCase, name: str) -> GridCase:
    """Copy of ``case`` with a new name."""
    return replace(case, name=name)
