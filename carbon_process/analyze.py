import logging

from temporalio import activity

from carbon_process import config
from carbon_process.model import AnalysisResult, WorkerState

logger = logging.getLogger("analyze")

HIGH_THRESHOLD = config.HIGH_THRESHOLD
LOW_THRESHOLD  = config.LOW_THRESHOLD


def carbon_ratio(worker: WorkerState):
    if not worker.carbon_threshold:
        logger.warning("worker %s has no carbon threshold", worker.container_name)
        return None
    return worker.current_carbon / worker.carbon_threshold


@activity.defn
async def analyze(workers: dict[str, WorkerState]):

    results = []

    if not workers:
        return results

    suspended_workers = [
        container_name
        for container_name, state in workers.items()
        if state.suspended
    ]
    for container_name in suspended_workers:
        results.append(AnalysisResult(
            action="degrade",
            reason="suspension",
            candidates=[container_name],
        ))
        
    ratios = {
        container_name: ratio
        for container_name, state in workers.items()
        if not state.suspended and not state.warmup_cycles_remaining > 0
        if (ratio := carbon_ratio(state)) is not None
    }

    # überlastung durch degreade verhindern 
    for container_name, state in workers.items():
        if state.prev_scale_direction == "down" and state.cpu_percentage > 95 and not state.suspended:
            results.append(AnalysisResult(
                action="degrade",
                reason="high_cpu",
                candidates=[container_name],
            ))
            ratios.pop(container_name, None)

    if not ratios:
        return results

    avg_ratio = sum(ratios.values()) / len(ratios)

    active_workers = [
        worker
        for worker in workers.values()
        if not worker.suspended and not worker.warmup_cycles_remaining > 0
    ]

    logger.debug("process carbon ratio: %.2f (workers: %d)", avg_ratio, len(active_workers))

    total_carbon = sum(worker.current_carbon for worker in active_workers)
    process_threshold = sum(worker.carbon_threshold for worker in active_workers if worker.carbon_threshold)

    # high process-wide carbon
    high_limit = process_threshold * HIGH_THRESHOLD
    if total_carbon >= high_limit:
        candidates = sorted(
            list(ratios),
            key=lambda container_name: ratios[container_name],
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
    low_limit = process_threshold * LOW_THRESHOLD
    if total_carbon <= low_limit:
        candidates = sorted(
            list(ratios),
            key=lambda container_name: ratios[container_name]
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
