"""Step 3 report: results/options_<case>.json -> RESULTS_OPTIONS.md (one table) and results/options_<case>.png
(grouped bars, total MW per option).
Usage: python bench/options_report.py [case118]"""
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CASE = sys.argv[1] if len(sys.argv) > 1 else "case118"
SRC = f"results/options_{CASE}.json"
LABEL = {"plain": "Plain best subset", "flex_load_50": "Flexible load, keep 50%", "flex_load_0": "Flexible load, keep 0%",
         "storage_25": "Storage 25% of load", "storage_50": "Storage 50% of load", "ras_gen_0": "Generation RAS, keep 0%",
         "switch": "Best single switch", "partial": "Partial MW"}


def main():
    d = json.load(open(SRC))
    s = d["summary"]
    n, nnf = s["n_clusters"], s["n_not_fit"]
    rows = [("plain", s["plain_mw"], 0.0, None, None, 0)]
    for k in d["options"]:
        o = s["options"][k]
        rows.append((k, o["total_mw"], o["gain_mw"], o["clusters_with_gain"], o["share_not_fit"], o["rechecks_failed"]))
    lines = [f"# Step 3: ways to make room ({CASE}, P1)", "",
             f"Source: `{SRC}` (written by `bench/options_study.py`; this file by `bench/options_report.py`).", "",
             f"{n} clusters from `{d['source']}`, {nnf} of them do not fully fit as a plain all-or-nothing subset. "
             f"Requested in total: {s['requested_mw']:.1f} MW. Plain best subset matches Step 2 in "
             f"{s['plain_matches_step2']} of {n} clusters. Generator reactive limits: {d['q_limits']}. "
             f"All re-checks passed: {s['all_rechecks_pass']}.", "",
             "| Option | Total MW admitted | Gain over plain (MW) | Clusters with a gain | Share of clusters that don't fit | Re-checks failed |",
             "|---|---:|---:|---:|---:|---:|"]
    for k, tot, g, c, sh, rf in rows:
        lines.append(f"| {LABEL[k]} | {tot:.1f} | {g:.1f} | {'' if c is None else c} | "
                     f"{'' if sh is None else f'{100 * sh:.1f}%'} | {rf} |")
    lines += ["", "Storage 50% uses the same rule as flexible load keep 50% (load cut by half after an outage), so the two "
              "rows are equal by construction. Partial MW counts the fractional MW of left-out requests on top of the plain "
              "subset. Each option can fall back to the plain subset, so no option is below it.", ""]
    open("RESULTS_OPTIONS.md", "w").write("\n".join(lines))

    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor="white")
    ax.set_facecolor("white")
    names = [LABEL[r[0]] for r in rows]
    plain = [s["plain_mw"]] * len(rows)
    tot = [r[1] for r in rows]
    x = range(len(rows))
    w = 0.38
    ax.bar([i - w / 2 for i in x], plain, w, color="#2a78d6", label="Plain best subset")
    ax.bar([i + w / 2 for i in x], tot, w, color="#eb6834", label="With the option")
    ax.set_xticks(list(x)); ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel(f"Total MW admitted, {n} clusters")
    ax.set_title(f"{CASE}, P1: MW admitted per option")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(f"results/options_{CASE}.png", dpi=150, facecolor="white")
    print("wrote RESULTS_OPTIONS.md and", f"results/options_{CASE}.png")


if __name__ == "__main__":
    main()
