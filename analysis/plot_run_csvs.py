"""
python3 plot_run_csvs.py /mnt/e/thesis/CarbonContainersThesis/reports/20260922_015850_081cbd
"""

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap

from run_data import cli, summarize

COLORS = {
    "Baseline": "#8b7159", "LXCC-only": "#445e8a", "p = 90%": "#5f9e6e",
    "p = 80%": "#9285c2", "Carbon Pressure": "#b45457", "Relative Consumption": "#e09569",
}
GREEN_TO_RED = LinearSegmentedColormap.from_list("better_worse", ["#16805B", "white", "#B42318"])
HEATMAP_SYSTEMS = {"LXCC-only": "lxcc", "Combined": "combined"}
GUIDE_LINE = {"linestyle": "--", "linewidth": 1, "color": "#999999"}


def save(fig, data, path):
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    data.to_csv(path.with_suffix(".csv"))
    plt.close(fig)


def heatmaps(scenario, metric, path):
    limit = scenario.loc[list(HEATMAP_SYSTEMS), metric].abs().max()
    for system, suffix in HEATMAP_SYSTEMS.items():
        fig, ax = plt.subplots(figsize=(5, 3.2))
        data = scenario.loc[system, metric].unstack("ci")
        sns.heatmap(data, annot=True, fmt="+.1f", cmap=GREEN_TO_RED, vmin=-limit, vmax=limit, cbar_kws={"label": "Change to Baseline (%)"}, ax=ax)
        ax.set(xlabel="", ylabel="")
        ax.tick_params(axis="y", rotation=0)
        save(fig, data, path.with_name(f"{path.name}_{suffix}"))


def ci_error(row, metric):
    return [[row[metric] - row[f"{metric}_ci_low"]], [row[f"{metric}_ci_high"] - row[metric]]]


def scatter(overall, x, y, xlabel, ylabel, path, diagonal=False, baseline_line=False):
    fig, ax = plt.subplots(figsize=(6, 4.5))
    if diagonal:
        ax.axline((0, 0), slope=1, label="Proportional change", **GUIDE_LINE)
    for system, color in COLORS.items():
        row = overall.loc[system]
        ax.errorbar(row[x], row[y], xerr=ci_error(row, x), yerr=ci_error(row, y), fmt="o", markersize=8, capsize=3, color=color, label=system)
    if baseline_line:
        baseline = overall.loc["Baseline", y]
        ax.axline((0, baseline), slope=baseline / 100, label="Baseline carbon per workflow", **GUIDE_LINE)
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.legend()
    columns = [f"{metric}{suffix}" for metric in (x, y) for suffix in ("", "_ci_low", "_ci_high")]
    save(fig, overall.loc[list(COLORS), columns], path)


def main():
    analysis, _, runs = cli(__doc__)
    summaries = summarize(runs)
    figures = analysis / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams["pdf.fonttype"] = 42

    heatmaps(summaries["scenario"], "delta_C_workflow", figures / "heatmap_carbon_per_workflow")
    carbon_label = "Total carbon emissions vs. Baseline (%)"
    scatter(summaries["overall"], "delta_E_total", "P_workflow", carbon_label, "Workflow success rate (%)", figures / "carbon_vs_workflow_success", baseline_line=True)
    scatter(summaries["overall"], "delta_E_total", "delta_K_total", carbon_label, "Successful computation vs. Baseline (%)", figures / "carbon_vs_computation", diagonal=True)
    print(f"Abbildungen: {figures}")


if __name__ == "__main__":
    main()
