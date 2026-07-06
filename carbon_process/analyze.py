import logging

from temporalio import activity

from carbon_process import config
from carbon_process.model import AnalysisResult, WorkerState

logger = logging.getLogger("analyze")

HIGH_THRESHOLD = config.HIGH_THRESHOLD
LOW_THRESHOLD  = config.LOW_THRESHOLD


@activity.defn
async def analyze(workers: dict[str, WorkerState]):

    results = []

    if not workers:
        return results

    # improve local worker performance by degrading
    for container_name, state in workers.items():
        if state.suspended:
            results.append(AnalysisResult(
                action="degrade",
                reason="suspension",
                candidates=[container_name],
            ))
            continue

        if state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core:
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

    sum_tresholds = sum(worker.carbon_threshold for worker in active_workers)

    scores = {
        container_name: (score := state.current_carbon / total_carbon)
        for container_name, state in workers.items()
        if not state.suspended 
        if not state.warmup_cycles_remaining > 0
        if not (state.cpu_percentage > 95 and state.current_cpu_core < state.max_cpu_core)
    }
    if not scores:
        return results

    # high process-wide carbon
    high_limit = sum_tresholds * HIGH_THRESHOLD
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
    low_limit = sum_tresholds * LOW_THRESHOLD
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
