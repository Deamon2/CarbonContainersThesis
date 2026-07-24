import os
import yaml
from pydantic import BaseModel


UPDATE_PERIOD_S = 10
CONFIG_PATH = "flag_config.yaml"
PROMETHEUS_PORT = 9101


class CarbonWorkflowConfig(BaseModel):
    score_method: str = "relative_consumption"
    high_threshold: float = 0.9
    low_threshold: float = 0.7

def load():
    path = os.environ.get("SIM_PARAMETER_CONFIG_PATH")
    if not path:
        print("WARNUNG: SIM_PARAMETER_CONFIG_PATH nicht gesetzt, nutze Defaults")
        return CarbonWorkflowConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
        print(f"INFO: Konfiguration geladen: {path} ")
    return CarbonWorkflowConfig(**raw.get("carbon_workflow", {}))


CONFIG = load()
