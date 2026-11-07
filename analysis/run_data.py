import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

WARMUP_SECONDS = 120
COMPLEXITY_LEVELS = ("high", "medium", "low")
WORK_PER_RESPONSE = {
    "cont1": {"low": 37, "medium": 67, "high": 135},
    "cont2": {"low": 67, "medium": 135, "high": 270},
    "cont3": {"low": 16, "medium": 36, "high": 67},
    "cont4": {"low": 37, "medium": 67, "high": 135},
}

COUNTERS = {
    "energy_j": ("total_joules.csv", 6, [2]),
    "E": ("total_carbon.csv", 6, [2]),
    "Q_att": ("service_requests_total.csv", 3, [1]),
    "N": ("service_successful_total.csv", 4, [1, 2]),
    "I_total": ("workflow_total.csv", 2, [3, 4, 5]),
    "I_succ": ("workflow_successful_total.csv", 2, [3, 4, 5]),
    "I_failed": ("workflow_failed_total.csv", 2, [3, 4, 5]),
    "D_sum_s": ("workflow_computation_seconds_sum.csv", 2, [3, 4, 5]),
    "n_D": ("workflow_computation_seconds_count.csv", 2, [3, 4, 5]),
}
WORKFLOW_COUNTERS = ["I_total", "I_succ", "I_failed", "D_sum_s", "n_D"]

SYSTEM_LABELS = {"base": "Baseline", "lxcc": "LXCC-only"}
METHOD_LABELS = {"carbon_pressure": "Carbon Pressure", "relative_consumption": "Relative Consumption"}
CI_LABELS = {"fr": "France", "de": "Germany", "dk": "Denmark"}
LOAD_LABELS = {"steady": "Steady", "fluctuation": "Fluctuating", "spike": "Spikes"}
COMBINED = [f"{method} {threshold}%" for threshold in (90, 80) for method in METHOD_LABELS.values()]
SELECTIONS = {
    "Baseline": ["Baseline"],
    "LXCC-only": ["LXCC-only"],
    "Combined": COMBINED,
    "p = 90%": [config for config in COMBINED if config.endswith("90%")],
    "p = 80%": [config for config in COMBINED if config.endswith("80%")],
    "Carbon Pressure": [config for config in COMBINED if config.startswith("Carbon Pressure")],
    "Relative Consumption": [config for config in COMBINED if config.startswith("Relative Consumption")],
    **{config: [config] for config in COMBINED},
}

METRICS = ["E_total", "C_workflow", "P_workflow", "D_workflow", "P_worker", "A_omitted", "eta", "K_total", *[f"P_{level}" for level in COMPLEXITY_LEVELS]]
RELATIVE = ["E_total", "C_workflow", "D_workflow", "eta", "K_total"]
DELTAS = [f"delta_{metric}" for metric in RELATIVE]
COLUMNS = [*METRICS, *DELTAS]
STATISTICS = ("", "_ci_low", "_ci_high", "_cv")
SCOPES = {"overall": [], "ci": ["ci"], "load": ["load"], "scenario": ["load", "ci"]}


def with_statistics(table, metrics):
    return table[[f"{metric}{suffix}" for metric in metrics for suffix in STATISTICS]]


def read_counter(path, value_column, label_columns):
    raw = pd.read_csv(path, skipinitialspace=True)
    labels = raw.iloc[:, label_columns].astype(str).apply(lambda column: column.str.strip().str.lower())
    return pd.DataFrame({
        "time": pd.to_datetime(raw.iloc[:, 0], utc=True, errors="coerce"),
        "value": pd.to_numeric(raw.iloc[:, value_column], errors="coerce"),
        "series": labels.agg("|".join, axis=1),
    }).dropna(subset=["time", "value"]).sort_values("time")

def counter_increase(values):
    differences = values.diff().dropna()
    resets = differences < 0
    if resets.any():
        print(f"WARNUNG: {resets.sum()} Counter-Reset(s) erkannt")
    return differences.where(~resets, values.loc[differences.index]).sum()

def container_table(increases):
    responses = increases["N"]
    responses.index = pd.MultiIndex.from_tuples(key.split("|") for key in responses.index)
    responses = responses.unstack(fill_value=0).reindex(columns=COMPLEXITY_LEVELS, fill_value=0)

    containers = pd.DataFrame({name: increases[name] for name in ("energy_j", "E", "Q_att")})
    responses = responses.reindex(containers.index, fill_value=0)
    work = pd.DataFrame(WORK_PER_RESPONSE).T.loc[containers.index]
    containers["Q_succ"] = responses.sum(axis=1)
    containers = containers.join(responses.add_prefix("N_"))
    containers["K"] = (responses * work).sum(axis=1)
    containers["K_max"] = containers["Q_succ"] * work["high"]
    return containers

def run_metrics(containers, workflow):
    return {
        "C_workflow": containers["E"].sum() / workflow["I_succ"],
        "P_workflow": 100 * workflow["I_succ"] / workflow["I_total"],
        "D_workflow": workflow["D_sum_s"] / workflow["n_D"],
        "P_worker": 100 * (containers["Q_succ"] / containers["Q_att"]).mean(),
        "A_omitted": 100 * (1 - containers["K"].sum() / containers["K_max"].sum()),
        "eta": containers["K"].sum() / containers["E"].sum(),
        **{f"P_{level}": 100 * containers[f"N_{level}"].sum() / containers["Q_succ"].sum()
           for level in COMPLEXITY_LEVELS},
    }


def process_run(data_dir):
    frames = {}
    for name, (file, value_column, label_columns) in COUNTERS.items():
        frames[name] = read_counter(data_dir / file, value_column, label_columns)

    populated = [frame for frame in frames.values() if not frame.empty]
    start = max(frame["time"].min() for frame in populated) + pd.Timedelta(seconds=WARMUP_SECONDS)
    end = min(frame["time"].max() for frame in populated)
    increases = {}
    for name, frame in frames.items():
        in_window = frame[frame["time"].between(start, end)]
        increases[name] = in_window.groupby("series")["value"].apply(counter_increase)

    containers = container_table(increases)
    workflow = {name: increases[name].sum() for name in WORKFLOW_COUNTERS}
    if workflow["I_total"] != workflow["I_succ"] + workflow["I_failed"]:
        print(f"WARNUNG: {data_dir}: I_total != I_succ + I_failed")
    totals = containers.sum().rename({"E": "E_total", "K": "K_total"})
    with np.errstate(divide="ignore", invalid="ignore"):
        metrics = run_metrics(containers, workflow)
    return containers.rename_axis("container").reset_index(), {**totals, **workflow, **metrics}

def param(params, *names):
    for name in names:
        if name in params:
            return params[name]
    suffixes = tuple(f"_{name}" for name in names)
    matches = [value for key, value in params.items() if key.endswith(suffixes)]
    if len(matches) != 1:
        raise KeyError(f"Parameter {names} nicht eindeutig gefunden")
    return matches[0]

def configuration_meta(config_dir):
    config = yaml.safe_load((config_dir / "parameter_config.yaml").read_text("utf-8"))
    params = pd.json_normalize(config, sep="_").iloc[0].to_dict()
    system = str(param(params, "test_system", "test_systems", "system")).lower()
    if system == "combined":
        threshold = float(param(params, "carbon_workflow_high_threshold"))
        method = METHOD_LABELS[param(params, "carbon_workflow_score_method")]
        system = f"{method} {threshold:.0%}"
    return {
        "cell": config_dir.name,
        "system": SYSTEM_LABELS.get(system, system),
        "load": LOAD_LABELS[str(param(params, "load_shape_scenario")).lower()],
        "ci": CI_LABELS[str(param(params, "ci_scenario_region")).lower()],
    }

def load_runs(root):
    containers, runs = [], []
    for config_dir in sorted(root.glob("configuration_*")):
        meta = configuration_meta(config_dir)
        for run_dir in sorted(config_dir.glob("run_*")):
            per_container, per_run = process_run(run_dir / "data")
            containers.append(per_container.assign(**meta, run=run_dir.name))
            runs.append({**meta, "run": run_dir.name, **per_run})
    if not runs:
        raise FileNotFoundError(f"Keine Runs unter {root}")

    runs = pd.DataFrame(runs).replace([np.inf, -np.inf], np.nan)
    runs["load"] = pd.Categorical(runs["load"], LOAD_LABELS.values())
    runs["ci"] = pd.Categorical(runs["ci"], CI_LABELS.values())
    print(f"{len(runs)} Runs geladen")
    containers = pd.concat(containers, ignore_index=True)
    ids = ["cell", "system", "load", "ci", "run"]
    return containers[[*ids, *containers.columns.drop(ids)]], runs

def cli(description):
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report_dir", type=Path)
    root = parser.parse_args().report_dir.resolve()
    containers, runs = load_runs(root)
    return root / "analysis", containers, runs


def add_deltas(runs):
    scenario_keys = ["load", "ci"]
    baseline = runs[runs["system"] == "Baseline"].groupby(scenario_keys, observed=True)[RELATIVE].mean()
    reference = baseline.reindex(pd.MultiIndex.from_frame(runs[scenario_keys])).to_numpy()
    runs = runs.copy()
    runs[DELTAS] = 100 * (runs[RELATIVE].to_numpy() / reference - 1)
    return runs

def cell_statistics(runs):
    cells = runs.groupby(["system", "load", "ci"], observed=True)[COLUMNS]
    run_count = cells.count()
    cv = 100 * cells.std() / cells.mean()
    cv[DELTAS] = cv[RELATIVE].to_numpy()
    statistics = {"mean": cells.mean(), "se2": cells.var() / run_count, "df": run_count - 1, "cv": cv}

    by_selection = {}
    for name, frame in statistics.items():
        members = {selection: frame.loc[configs] for selection, configs in SELECTIONS.items()}
        by_selection[name] = pd.concat(members, names=["selection"])
    return by_selection

def summarize(runs):
    cells = cell_statistics(add_deltas(runs))
    summaries = {}
    for scope, levels in SCOPES.items():
        def grouped(frame):
            return frame.groupby(level=["selection", *levels], observed=True, sort=False)

        mean = grouped(cells["mean"]).mean()
        se2_sum = grouped(cells["se2"]).sum()
        standard_error = np.sqrt(se2_sum) / grouped(cells["mean"]).count()
        degrees_of_freedom = se2_sum ** 2 / grouped(cells["se2"] ** 2 / cells["df"]).sum()  # Welch-Satterthwaite
        half_width = (standard_error * stats.t.ppf(0.975, degrees_of_freedom)).where(standard_error > 0, 0)
        table = pd.concat([
            mean,
            (mean - half_width).add_suffix("_ci_low"),
            (mean + half_width).add_suffix("_ci_high"),
            grouped(cells["cv"]).mean().add_suffix("_cv"),
        ], axis=1)
        summaries[scope] = with_statistics(table, COLUMNS)
    return summaries
