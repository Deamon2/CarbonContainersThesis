from dataclasses import dataclass

@dataclass
class WorkerState:
    container_name: str
    current_carbon: float
    carbon_threshold: float
    cpu_percentage: float
    suspended: bool
    scale_direction: str | None = None
    prev_scale_direction: str | None = None
    warmup_cycles_remaining: int = 0        # gives services time afer suspend to stabilize


@dataclass
class AnalysisResult:
    action: str  # degrade | upgrade
    reason: str  # suspension | high_carbon | low_carbon
    candidates: list[str]  # ordered by priority, highest first
