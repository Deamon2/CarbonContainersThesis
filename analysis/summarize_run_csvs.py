"""
python3 summarize_run_csvs.py /mnt/e/thesis/CarbonContainersThesis/reports/20260922_015850_081cbd
"""

import pandas as pd

from run_data import CI_LABELS, COMBINED, LOAD_LABELS, cli, summarize, with_statistics

CONFIGURATIONS = ["Baseline", "LXCC-only", *COMBINED]
SYSTEMS = ["Baseline", "LXCC-only", "Combined", "p = 90%", "p = 80%", "Carbon Pressure", "Relative Consumption"]
SCENARIO_SYSTEMS = ["LXCC-only", "Combined"]
SYSTEM_TABLES = {
    "carbon_by_system": (SYSTEMS, ["delta_E_total"]),
    "workflow_quality_by_system": (SYSTEMS, ["P_workflow", "delta_D_workflow"]),
    "worker_quality_by_system": (SYSTEMS, ["P_worker", "A_omitted", "delta_K_total"]),
    "complexity_by_system": (SYSTEMS[2:], ["P_high", "P_medium", "P_low"]),
    "efficiency_by_system": (SYSTEMS, ["delta_C_workflow", "delta_eta"]),
}
SCENARIO_TABLES = {
    "carbon_by_scenario": ["delta_E_total"],
    "workflow_quality_by_scenario": ["P_workflow", "delta_D_workflow"],
    "efficiency_by_scenario": ["delta_C_workflow"],
}

CI_TABLE = [
    ("E_total", "E_total [mgCO2eq/run]", 1e3),
    ("C_workflow", "C_workflow [µgCO2eq]", 1e6),
    ("P_workflow", "P_workflow [%]", 1),
    ("D_workflow", "D_workflow [s]", 1),
    ("P_worker", "P_worker [%]", 1),
    ("A_omitted", "A_omitted [%]", 1),
    ("K_total", "K_total [10^6 compute units/run]", 1e-6),
    ("eta", "eta [compute units/mgCO2eq]", 1e-3),
]


def scenario_table(summaries, metrics):
    parts = [summaries[scope].loc[SCENARIO_SYSTEMS].rename_axis(["selection", "scenario"]) for scope in ("ci", "load")]
    table = with_statistics(pd.concat(parts), metrics).unstack("selection").swaplevel(axis=1)[SCENARIO_SYSTEMS]
    table.columns = [f"{system} | {statistic}" for system, statistic in table.columns]
    return table.reindex([*CI_LABELS.values(), *LOAD_LABELS.values()])


def main():
    analysis, containers, runs = cli(__doc__)
    summaries = summarize(runs)
    tables, data = analysis / "tables", analysis / "data"
    tables.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    for name, (systems, metrics) in SYSTEM_TABLES.items():
        with_statistics(summaries["overall"].loc[systems], metrics).to_csv(tables / f"{name}.csv")
    for name, metrics in SCENARIO_TABLES.items():
        scenario_table(summaries, metrics).to_csv(tables / f"{name}.csv")

    for ci in CI_LABELS.values():
        scenario = summaries["scenario"].xs(ci, level="ci").loc[CONFIGURATIONS]
        table = pd.DataFrame({header: scenario[metric] * factor for metric, header, factor in CI_TABLE})
        table.rename_axis(["system", "workload"]).to_csv(tables / f"carbon_intensity_{ci.lower()}.csv")

    containers.to_csv(data / "containers.csv", index=False)
    runs.to_csv(data / "runs.csv", index=False)
    summaries["scenario"].loc[CONFIGURATIONS].to_csv(data / "configurations.csv")
    summaries["overall"].to_csv(data / "systems.csv")
    print(f"Ergebnisse: {analysis}")


if __name__ == "__main__":
    main()
