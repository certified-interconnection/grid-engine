"""NERC TPL-001 style contingency sets on the branch list.

All sets use only in-service branches, and every contingency is checked so that
it does not island the grid (removing it keeps both ends of every outaged
branch connected to each other).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

from .cases import GridCase

P1 = "P1"
P7 = "P7"
N2 = "N2"

DEFAULT_SEED = 20241124
DEFAULT_N2_SIZE = 200


@dataclass(frozen=True)
class Contingency:
    id: str
    kind: str
    branch_ids: tuple[int, ...]
    label: str = ""

    def __post_init__(self) -> None:
        if not self.branch_ids:
            raise ValueError("a contingency needs at least one branch")


def adjacency(case: GridCase) -> dict[int, list[tuple[int, int]]]:
    """Bus id -> [(neighbour bus id, branch id)] over in-service branches."""
    adj: dict[int, list[tuple[int, int]]] = {bus.id: [] for bus in case.buses}
    for branch in case.branches:
        if not branch.in_service:
            continue
        if branch.from_bus not in adj or branch.to_bus not in adj:
            continue
        adj[branch.from_bus].append((branch.to_bus, branch.id))
        adj[branch.to_bus].append((branch.from_bus, branch.id))
    return adj


def connected(
    adj: dict[int, list[tuple[int, int]]],
    start: int,
    target: int,
    excluded: set[int],
) -> bool:
    if start == target:
        return True
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for neighbour, branch_id in adj[node]:
            if branch_id in excluded:
                continue
            if neighbour == target:
                return True
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return False


def islands(case: GridCase, branch_ids, adj=None) -> bool:
    """True if removing ``branch_ids`` disconnects the grid."""
    adj = adjacency(case) if adj is None else adj
    excluded = set(branch_ids)
    ends = {branch.id: (branch.from_bus, branch.to_bus) for branch in case.branches}
    for branch_id in excluded:
        from_bus, to_bus = ends[branch_id]
        if not connected(adj, from_bus, to_bus, excluded):
            return True
    return False


def p1(case: GridCase, adj=None) -> list[Contingency]:
    """Single branch outages; bridges that would island the grid are skipped."""
    adj = adjacency(case) if adj is None else adj
    out: list[Contingency] = []
    for branch in case.in_service_branches():
        if islands(case, [branch.id], adj):
            continue
        out.append(Contingency(id=f"P1-{branch.id}", kind=P1, branch_ids=(branch.id,), label=branch.name))
    return out


def p7(case: GridCase, adj=None) -> list[Contingency]:
    """Common-corridor double outages: pairs of branches with the same two ends."""
    adj = adjacency(case) if adj is None else adj
    corridors: dict[frozenset[int], list[int]] = {}
    for branch in case.in_service_branches():
        corridors.setdefault(frozenset((branch.from_bus, branch.to_bus)), []).append(branch.id)
    out: list[Contingency] = []
    for ends, branch_ids in corridors.items():
        if len(branch_ids) < 2:
            continue
        for pair in itertools.combinations(sorted(branch_ids), 2):
            if islands(case, pair, adj):
                continue
            out.append(
                Contingency(
                    id=f"P7-{pair[0]}-{pair[1]}",
                    kind=P7,
                    branch_ids=pair,
                    label=f"corridor {sorted(ends)}",
                )
            )
    out.sort(key=lambda c: c.id)
    return out


def n2(
    case: GridCase,
    size: int = DEFAULT_N2_SIZE,
    seed: int = DEFAULT_SEED,
    adj=None,
    max_attempts_factor: int = 20,
) -> list[Contingency]:
    """Seeded random sample of non-islanding branch pairs.

    Pairs are drawn without replacement from the in-service branches until
    ``size`` non-islanding pairs are found, or until ``max_attempts_factor *
    size`` distinct pairs have been tried.
    """
    adj = adjacency(case) if adj is None else adj
    branch_ids = [branch.id for branch in case.in_service_branches()]
    if len(branch_ids) < 2:
        return []
    rng = random.Random(seed)
    seen: set[tuple[int, int]] = set()
    out: list[Contingency] = []
    attempts = 0
    limit = max_attempts_factor * size
    while len(out) < size and attempts < limit:
        i = rng.randrange(len(branch_ids))
        j = rng.randrange(len(branch_ids))
        if i == j:
            continue
        a, b = (i, j) if i < j else (j, i)
        if (a, b) in seen:
            continue
        seen.add((a, b))
        attempts += 1
        pair = (branch_ids[a], branch_ids[b])
        if islands(case, pair, adj):
            continue
        out.append(
            Contingency(
                id=f"N2-{pair[0]}-{pair[1]}",
                kind=N2,
                branch_ids=pair,
                label=f"seeded random pair, seed {seed}",
            )
        )
    out.sort(key=lambda c: c.branch_ids)
    return out


def build_sets(
    case: GridCase,
    *,
    seed: int = DEFAULT_SEED,
    n2_size: int = DEFAULT_N2_SIZE,
    include: tuple[str, ...] = (P1, P7, N2),
) -> dict[str, list[Contingency]]:
    """All requested sets, sharing one adjacency structure."""
    adj = adjacency(case)
    sets: dict[str, list[Contingency]] = {}
    if P1 in include:
        sets[P1] = p1(case, adj)
    if P7 in include:
        sets[P7] = p7(case, adj)
    if N2 in include:
        sets[N2] = n2(case, size=n2_size, seed=seed, adj=adj)
    return sets


def skipped_bridges(case: GridCase) -> list[int]:
    """Branch ids whose single outage would island the grid."""
    adj = adjacency(case)
    return [branch.id for branch in case.in_service_branches() if islands(case, [branch.id], adj)]
