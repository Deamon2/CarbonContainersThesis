import yaml
from typing import List
from pydantic import BaseModel

class CarbonWorkflowOptions(BaseModel):
    score_method: List[str] = ["relative_consumption"]
    high_threshold: List[float] = [0.9]
    low_threshold: List[float] = [0.7]


class SimConfig(BaseModel):
    carbon_workflow: CarbonWorkflowOptions


def load_sim_config(path: str):
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return SimConfig(**raw)


class CarbonWorkflowRunConfig(BaseModel):
    score_method: str
    high_threshold: float
    low_threshold: float


class ParameterConfig(BaseModel):
    carbon_workflow: CarbonWorkflowRunConfig


def build_parameter_config(sim_config: SimConfig):
    """Wählt aktuell aus jeder Liste den ersten Wert. TODO: durch echte Sweep Logik ersetzen"""
    cw = sim_config.carbon_workflow
    return ParameterConfig(
        carbon_workflow=CarbonWorkflowRunConfig(
            score_method=cw.score_method[0],
            high_threshold=cw.high_threshold[0],
            low_threshold=cw.low_threshold[0],
        )
    )
