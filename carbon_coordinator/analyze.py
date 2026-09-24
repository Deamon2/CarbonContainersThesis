import logging

from temporalio import activity

from carbon_coordinator.config import CONFIG
from carbon_coordinator.model import AnalysisResult, WorkerState

logger = logging.getLogger("analyze")

HIGH_THRESHOLD = CONFIG.high_threshold
LOW_THRESHOLD  = HIGH_THRESHOLD * 0.75      # verringert ozillation zwischen upgrade und degrade
SCORE_METHOD = CONFIG.score_method

@activity.defn
async def analyze(workers: dict[str, WorkerState]) -> list[AnalysisResult]:

    results = []

    if not workers:
        return results

    excluded_workers = []
    # improve local worker performance by degrading
    for container_name, state in workers.items():
        
        if state.suspended:
            if state.warmup_reason == "suspension" and state.warmup_cycles_remaining > 0:
                continue
            results.append(AnalysisResult(
                action="degrade",
                reason="suspension",
                candidates=[container_name],
            ))
            excluded_workers.append(container_name)
            continue

        if state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core:
            if state.warmup_reason == "high_cpu" and state.warmup_cycles_elapsed < 2:
                continue
            logger.info("High CPU for %s: %.1f%%", container_name, state.cpu_percentage)
            results.append(AnalysisResult(
                action="degrade",
                reason="high_cpu",
                candidates=[container_name],
            ))
            excluded_workers.append(container_name)

    
    active_workers = [
        worker
        for worker in workers.values()
        if not worker.suspended 
    ]
    if not active_workers:
        return results

    total_carbon = sum(worker.current_carbon for worker in active_workers)
    if total_carbon == 0:
        return results

    if SCORE_METHOD == "relative_consumption":
        scores = {
            container_name: (score := state.current_carbon / total_carbon)
            for container_name, state in workers.items()
            if not container_name in excluded_workers
        }
    elif SCORE_METHOD == "carbon_pressure":
        scores = {
            container_name: (score:= state.current_carbon / state.carbon_threshold)
            for container_name, state in workers.items()
            if not container_name in excluded_workers 
        }
    if not scores:
        return results

    # high process-wide carbon
    sum_thresholds = sum(worker.carbon_threshold for worker in active_workers)
    high_limit = sum_thresholds * HIGH_THRESHOLD
    if total_carbon >= high_limit:
        candidates = sorted(
            list(scores),
            key=lambda container_name: scores[container_name],
            reverse=True
        )
        logger.info("High Carbon (%.7f >= %.7f): candidates %s", total_carbon, high_limit, candidates)
        if candidates:
            results.append(AnalysisResult(
                action="degrade",
                reason="high_carbon",
                candidates=candidates
            ))

    # low process-wide carbon
    low_limit = sum_thresholds * LOW_THRESHOLD
    if total_carbon <= low_limit:
        candidates = sorted(
            list(scores),
            key=lambda container_name: scores[container_name]
        )
        logger.info("Low Carbon (%.7f <= %.7f): candidates %s", total_carbon, low_limit, candidates)
        if candidates:
            results.append(AnalysisResult(
                action="upgrade",
                reason="low_carbon",
                candidates=[
                    container_name
                    for container_name in candidates
                    if not (
                        workers[container_name].warmup_cycles_remaining > 0
                        and workers[container_name].warmup_reason in {"high_cpu", "suspension"}
                    )
                ],
            ))

    if not results:
        logger.info("no action needed (%.7f < %.7f < %.7f)", low_limit, total_carbon, high_limit)

    try:
        from carbon_coordinator.metrics_server import metrics
        metrics.update_process_upgrade_threshold(low_limit)
        metrics.update_process_degrade_threshold(high_limit)
    except Exception:
        logger.debug("Prometheus metrics update failed")
 

    return results
