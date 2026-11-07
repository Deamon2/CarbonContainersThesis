import sys
from pathlib import Path

import pandas as pd


CONTAINERS = ["cont1", "cont2", "cont3", "cont4"]


def calculate_p75(csv_path: Path):
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    start = df["timestamp"].min() + pd.Timedelta(minutes=2)
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= df["timestamp"].max())]

    df["current_carbon"] = pd.to_numeric(df["current_carbon"], errors="coerce")
    return df.groupby("container_name")["current_carbon"].quantile(0.75)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"Aufruf: python {Path(sys.argv[0]).name} <current_carbon.csv oder configuration_dir>")

    input_path = Path(sys.argv[1])
    if input_path.is_file():
        csv_paths = [input_path]
    else:
        csv_paths = sorted(input_path.glob("*/data/current_carbon.csv"))

    if not csv_paths:
        raise SystemExit(f"Keine CSV-Datei oder passenden CSV-Dateien unter {input_path} gefunden.")

    p75_per_run = [calculate_p75(csv_path).to_dict() for csv_path in csv_paths]

    print(f"Runs verarbeitet: {len(csv_paths)}")
    for container in CONTAINERS:
        values = [run[container] for run in p75_per_run]
        if len(values) == 1:
            print(f"{container}: {values[0]}")
        else:
            average = sum(values) / len(csv_paths)
            print(f"{container}: {' | '.join(map(str, values))} | Durchschnitt: {average}")


if __name__ == "__main__":
    main()
