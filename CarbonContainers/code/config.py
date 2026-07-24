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

UPDATE_PERIOD = 15
MAX_FROZEN_CYCLES = 5


'''
LXC-C DAEMON VALUES
'''


HOST = "localhost"
PORT = 1994

WORKING_DIR = "./"

OUTPUT = "./logs/carbon"
M_OUTPUT = "./logs/migrations"


'''
CARBON DATA FUNCTION: REPLACE WITH YOUR IMPLEMENTATION

    Ensure input signature remains with NO PARAMETERS

    Ensure output is an INT representing CARBON INTENSITY in units: (Grams CO2 / kilowatt*hour)
'''

import json
from pathlib import Path
INTENSITY_FILE = Path(__file__).resolve().parent / "carbon_intensity.json"
PROMETHEUS_PORT = 9100

# gCO2/kWh 
def getCarbonIntensity():
    intensity = 100 
    try:
        if INTENSITY_FILE.exists():
            data = json.loads(INTENSITY_FILE.read_text())
            intensity = int(data.get('intensity', intensity))
    except Exception as error:
        print(f"Could not load intensity state: {error}")

    return intensity
