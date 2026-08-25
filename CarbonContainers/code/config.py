'''
CONFIG FILE FOR CARBON CONTAINERS
'''


'''
TEMPORAL CONFIG
'''
TEMPORAL_ADDRESS = "localhost:7233"
WORKFLOW_ID = "carbon-coordinator"


MIGRATION_MACHINES = {
    "127.0.0.1": {"host": "127.0.0.1", "cpu": 3, "memGB": 32, "basepow":4000 }  # 'cpu' an verfügbare VM-Cores anpassen (z.B. via nproc)
}

CO2_SIGNAL_KEY = "/users/jthiede/co2key.txt"

'''
FRONT END VALUES
'''

FRONT_IP = "localhost"
FRONT_PORT = "1994"


'''
RECORDS VALUES

'''
RECORD_IP = "localhost"
RECORD_PORT = "1996"
RECORD_FILE = "./conts.json"

'''
MONITOR VALUES
'''

IP = "localhost"
PORT = "1995"

'''
CONTROLLER VALUES
'''

CONTROLLER_PORT = "1997"
SSH_KEY_PATH = "/users/jthiede/id_rsa"
SSH_USER = "jthiede"
MIGRATION_PORT = 8888


'''
CARBON POLICY VALUES
'''

UPDATE_PERIOD = 10
MAX_FROZEN_CYCLES = 5


'''
LXC-C DAEMON VALUES
'''


HOST = "localhost"
PORT = 1994

WORKING_DIR = "./"

OUTPUT = "./logs/carbon"
M_OUTPUT = "./logs/migrations"


PROMETHEUS_PORT = 9100

import json
import time
import os
import yaml
from pydantic import BaseModel
from pathlib import Path


REGION_SCALING = {
    "fr": 1, 
    "de": 12, 
    "dk": 14
}

TARGET_DURATION_MIN = 30
INTERVAL_MIN = 5

class CarbonScenario(BaseModel):
    region: str = "fr"

def load_scenario_config():
    path = os.environ.get("SIM_PARAMETER_CONFIG_PATH")
    if not path:
        print("WARNUNG: SIM_PARAMETER_CONFIG_PATH nicht gesetzt, nutze Defaults")
        config = CarbonScenario()
    else:
        with open(path, encoding="utf-8") as config_file:
            raw = yaml.safe_load(config_file) or {}
        print(f"INFO: Konfiguration geladen: {path}")
        ci_scenario = raw.get("ci_scenario", {})
        config = CarbonScenario(**ci_scenario)

    region = config.region
    if region not in REGION_SCALING:
        valid_regions = ", ".join(REGION_SCALING)
        raise ValueError(f"Unbekannte Region '{region}'. Erlaubt: {valid_regions}")

    return region, REGION_SCALING[region]

DATA = None
SCALE = None

def load_data():
    global DATA, SCALE
    if DATA is not None:
        return DATA

    region, SCALE = load_scenario_config()
    path = Path(__file__).parent / f"ci_{region}.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = raw.get("data", raw) if isinstance(raw, dict) else raw

    if not isinstance(entries, list) or len(entries) == 0:
        raise ValueError(f"{path.name}: erwartet nicht-leere Liste von Messpunkten, bekommen: {type(entries)}")

    simulated_window_min = SCALE * TARGET_DURATION_MIN
    needed_points = int(simulated_window_min / INTERVAL_MIN) + 1

    if len(entries) < needed_points:
        raise ValueError(f"{path.name}: benötigt {needed_points} Messpunkte für SCALE={SCALE}. (Datei enthält nur {len(entries)})")

    entries = entries[:needed_points]

    parsed = []
    for i, entry in enumerate(entries):
        if "carbonIntensity" not in entry:
            raise ValueError(f"{path.name} Eintrag {i}: Feld 'carbonIntensity' fehlt")
        value = entry["carbonIntensity"]
        parsed.append(value)

    DATA = parsed

    return DATA

START_TIME = None
def getCarbonIntensity():
    # interpoliert zwischen werten
    global START_TIME
    data = load_data()

    now = time.monotonic()
    if START_TIME is None:
        START_TIME = now

    elapsed_real_min = (now - START_TIME) / 60
    simulated_min = min(elapsed_real_min * SCALE, TARGET_DURATION_MIN * SCALE)

    idx_float = simulated_min / INTERVAL_MIN
    idx_low = min(int(idx_float), len(data) - 1)
    idx_high = min(idx_low + 1, len(data) - 1)
    frac = idx_float - idx_low

    val_low = data[idx_low]
    val_high = data[idx_high]

    return round(val_low + (val_high - val_low) * frac)
