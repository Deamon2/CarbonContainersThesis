import logging

from temporalio import activity

from carbon_process.config import CONFIG
from carbon_process.model import AnalysisResult, WorkerState

logger = logging.getLogger("analyze")

HIGH_THRESHOLD = CONFIG.high_threshold
LOW_THRESHOLD  = HIGH_THRESHOLD - 0.2
SCORE_METHOD = CONFIG.score_method

@activity.defn
async def analyze(workers: dict[str, WorkerState]):

    results = []

    if not workers:
        return results

    # improve local worker performance by degrading
    for container_name, state in workers.items():
        
        if state.warmup_cycles_remaining > 0:
            continue

        if state.suspended:
            results.append(AnalysisResult(
                action="degrade",
                reason="suspension",
                candidates=[container_name],
            ))
            continue

        if state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core:
            logger.info("High CPU for %s: %.1f%%", container_name, state.cpu_percentage)
            results.append(AnalysisResult(
                action="degrade",
                reason="high_cpu",
                candidates=[container_name],
            ))

    
    active_workers = [
        worker
        for worker in workers.values()
        if not worker.suspended 
        if not worker.warmup_cycles_remaining > 0
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
            if not state.suspended 
            if not state.warmup_cycles_remaining > 0
            if not (state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core)
        }
    elif SCORE_METHOD == "carbon_pressure":
        scores = {
            container_name: (score:= state.current_carbon / state.carbon_threshold)
            for container_name, state in workers.items()
            if not state.suspended 
            if not state.warmup_cycles_remaining > 0
            if not (state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core)
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
        logger.info("High Carbon (%.2f >= %.2f): candidates %s", total_carbon, high_limit, candidates)
        if candidates:
            results.append(AnalysisResult(
                action="degrade",
                reason="high_carbon",
                candidates=candidates,
            ))

    # low process-wide carbon
    low_limit = sum_thresholds * LOW_THRESHOLD
    if total_carbon <= low_limit:
        candidates = sorted(
            list(scores),
            key=lambda container_name: scores[container_name]
        )
        logger.info("Low Carbon (%.2f <= %.2f): candidates %s", total_carbon, low_limit, candidates)
        if candidates:
            results.append(AnalysisResult(
                action="upgrade",
                reason="low_carbon",
                candidates=candidates,
            ))

    if not results:
        logger.info("no action needed (%.2f < %.2f < %.2f)", low_limit, total_carbon, high_limit)

    try:
        from carbon_process.metrics_server import metrics
        metrics.update_process_upgrade_threshold(low_limit)
        metrics.update_process_degrade_threshold(high_limit)
    except Exception:
        logger.debug("Prometheus metrics update failed")
 

    return results
