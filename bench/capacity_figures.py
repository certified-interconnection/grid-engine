"""Maps and a GIF from results/capacity_<case>.json (written by bench/capacity_study.py).
  results/capacity_<case>_<kind>.gif   every bus colored by how much new generation (or load) it can take,
                                       cycling seasons, with no outages (N-0) and under every single outage (P1)
  results/capacity_<case>_summary.json  numbers quoted in the README, computed here
Layout: a force-directed drawing of the network (the test grids have no real coordinates), fixed seed.
Usage: python bench/capacity_figures.py case118"""
import json, os, sys
import numpy as np
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.animation import PillowWriter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gridengine import Engine, load_case

CASE = sys.argv[1] if len(sys.argv) > 1 else "case118"
R = json.load(open(f"results/capacity_{CASE}.json"))
CAP = R["map_cap_mw"]
SEQ = LinearSegmentedColormap.from_list("blue", ["#e8f0fb", "#9ec5f4", "#5598e7", "#256abf", "#0d366b"])
INK, MUTED, EDGE = "#1a1a1a", "#6f6f6a", "#c9c6be"
SEASON_NAME = {"summer_peak": "summer peak", "winter_peak": "winter peak", "light_load": "light load"}

eng = Engine(load_case(CASE))
G = nx.Graph([(b["f"], b["t"]) for b in eng.branches])
pos = nx.kamada_kawai_layout(G)

summary = {}
for kind in ("gen", "load"):
    rows = [m for m in R["map"] if m["kind"] == kind]
    frames = [(s, k) for s in SEASON_NAME for k in ("N0", "P1")]
    stats = {}
    for s, k in frames:
        v = np.array([m[k]["mw"] for m in rows if m["season"] == s])
        stats[f"{s}/{k}"] = dict(median_mw=float(np.median(v)), share_at_cap=float(np.mean(v >= CAP - 1e-6)),
                                 share_zero=float(np.mean(v <= 1e-6)))
    for s in SEASON_NAME:
        n0 = {m["bus"]: m["N0"]["mw"] for m in rows if m["season"] == s}
        p1 = {m["bus"]: m["P1"]["mw"] for m in rows if m["season"] == s}
        drop = [1 - p1[b] / n0[b] for b in n0 if n0[b] > 1e-6]
        stats[f"{s}/median_loss_N0_to_P1"] = float(np.median(drop))
        reasons = {}
        for m in rows:
            if m["season"] == s and m["P1"]["binding"]:
                r = m["P1"]["binding"]["reason"]; reasons[r] = reasons.get(r, 0) + 1
        stats[f"{s}/P1_binding_reasons"] = reasons
    summary[kind] = stats

    fig, ax = plt.subplots(figsize=(7.2, 7.6))
    writer = PillowWriter(fps=0.8)
    with writer.saving(fig, f"results/capacity_{CASE}_{kind}.gif", dpi=110):
        for s, k in frames:
            ax.clear(); ax.set_axis_off()
            mw = {m["bus"]: m[k]["mw"] for m in rows if m["season"] == s}
            nx.draw_networkx_edges(G, pos, ax=ax, edge_color=EDGE, width=0.8)
            nodes = list(G.nodes)
            vals = np.array([mw.get(n, 0.0) for n in nodes])
            sc = ax.scatter([pos[n][0] for n in nodes], [pos[n][1] for n in nodes], c=vals, cmap=SEQ, vmin=0, vmax=CAP,
                            s=46, edgecolors=INK, linewidths=0.5, zorder=3)
            what = "new generation" if kind == "gen" else "new load"
            cond = "no outages (N-0)" if k == "N0" else "every single-line outage (P1)"
            ax.set_title(f"{CASE}: MW of {what} each bus can take\n{SEASON_NAME[s]}, {cond}", fontsize=11, color=INK,
                         family="monospace")
            st = stats[f"{s}/{k}"]
            ax.text(0.0, -0.02, f"median {st['median_mw']:.0f} MW   at the {CAP:.0f} MW cap: {100*st['share_at_cap']:.0f}%   "
                    f"zero: {100*st['share_zero']:.0f}%", transform=ax.transAxes, fontsize=9, color=MUTED, family="monospace")
            if not hasattr(ax, "_cb"):
                cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.01); cb.set_label("MW", color=MUTED); ax._cb = cb
            writer.grab_frame()
    plt.close(fig)

# clusters
cl = R["clusters"]
cs = {}
for cond in ("P1", "P1+P7"):
    rows = [c[cond] for c in cl]
    req = np.array([sum(r["mw"] for r in c["requests"]) for c in cl])
    cs[cond] = dict(
        n=len(rows),
        joint_over_sum_individual_median=float(np.median([r["joint_mw"] / r["sum_individual_mw"] for r in rows if r["sum_individual_mw"] > 1e-6])),
        total_mw=dict(requested=float(req.sum()), fits_alone_promise=float(sum(r["fits_alone_mw"] for r in rows)),
                      first_come=float(sum(r["queue"]["mw"] for r in rows)), largest_first=float(sum(r["largest_first"]["mw"] for r in rows)),
                      best_subset=float(sum(r["cluster"]["mw"] for r in rows))),
        share_best_beats_first_come=float(np.mean([r["cluster"]["mw"] > r["queue"]["mw"] + 1e-6 for r in rows])),
        share_fits_alone_overpromises=float(np.mean([r["fits_alone_mw"] > r["cluster"]["mw"] + 1e-6 for r in rows])),
        mean_checks_best_subset=float(np.mean([r["cluster"]["checks"] for r in rows])))
summary["clusters"] = cs
json.dump(summary, open(f"results/capacity_{CASE}_summary.json", "w"), indent=1)
print(json.dumps(summary["clusters"], indent=1))
