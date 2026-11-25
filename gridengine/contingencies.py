"""NERC TPL-001-style contingency sets on a branch list (our stated definitions, not any operator's study files).

P1 : every single branch outage that does not island the grid
P7 : every pair of branches that share both end buses (a stand-in for common-tower double circuits)
N2 : a seeded random sample of non-islanding branch pairs
A contingency is a tuple of branch keys; a branch key is (component, id) with component "line" or "transformer".
"""
from __future__ import annotations

import itertools
import networkx as nx
import numpy as np


def branch_table(input_data):
    """List of dicts (component, id, from_node, to_node) for every in-service line and transformer."""
    out = []
    for comp in ("generic_branch",):
        if comp not in input_data:
            continue
        a = input_data[comp]
        for row in a:
            if row["from_status"] and row["to_status"]:
                out.append(dict(component=comp, id=int(row["id"]), f=int(row["from_node"]), t=int(row["to_node"])))
    return out


def _graph(branches, drop=()):
    G = nx.MultiGraph()
    for i, b in enumerate(branches):
        G.add_node(b["f"]); G.add_node(b["t"])
        if i not in drop:
            G.add_edge(b["f"], b["t"], key=i)
    return G


def _islands(branches, drop):
    return nx.number_connected_components(_graph(branches, drop)) > nx.number_connected_components(_graph(branches))


def p1(branches):
    G = _graph(branches)
    bridges = set()
    for u, v in nx.bridges(nx.Graph(G)):
        if G.number_of_edges(u, v) == 1:
            bridges.add(frozenset((u, v)))
    return [(i,) for i, b in enumerate(branches) if frozenset((b["f"], b["t"])) not in bridges]


def p7(branches):
    by_pair = {}
    for i, b in enumerate(branches):
        by_pair.setdefault(frozenset((b["f"], b["t"])), []).append(i)
    out = []
    for idx in by_pair.values():
        for a, b in itertools.combinations(idx, 2):
            if not _islands(branches, (a, b)):
                out.append((a, b))
    return out


def n2_sample(branches, n=200, seed=0):
    rng = np.random.default_rng(seed)
    m = len(branches)
    seen, out, tries = set(), [], 0
    while len(out) < n and tries < 50 * n:
        tries += 1
        a, b = sorted(rng.choice(m, 2, replace=False).tolist())
        if (a, b) in seen:
            continue
        seen.add((a, b))
        if not _islands(branches, (a, b)):
            out.append((a, b))
    return out
