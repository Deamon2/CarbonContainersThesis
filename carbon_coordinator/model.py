from dataclasses import dataclass

@dataclass
class WorkerState:
    container_name: str
    current_carbon: float
    carbon_threshold: float
    cpu_percentage: float
    current_cpu_core: int
    max_cpu_core: int
    suspended: bool
    warmup_cycles_remaining: int = 0
    warmup_reason: str | None = None
    warmup_cycles_elapsed: int = 0


@dataclass
class AnalysisResult:
    action: str  # degrade | upgrade
    reason: str  # suspension | high_cpu | high_carbon | low_carbon
    candidates: list[str]  # ordered by priority, highest first
