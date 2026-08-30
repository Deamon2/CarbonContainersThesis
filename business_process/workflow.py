"""
pip install temporalio httpx 
"""
import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from business_process import config
from business_process.metrics_server import metrics


logger = logging.getLogger("ProcessWorkflow")

RETRY_POLICY = RetryPolicy(maximum_attempts=1)


async def run_request(container_name: str):
    try:
        return await workflow.execute_activity(
            "request",
            args=[container_name],
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RETRY_POLICY,
        )
    except ActivityError as error:
        return { "status": "error", "error": str(error.cause) }


@workflow.defn
class ProcessWorkflow:

    @workflow.run
    async def run(self):
        results = {}
        metrics.update_workflow_requests()

        for container_name in config.CONTAINER_NAMES:
            result = await run_request(container_name)

            if result.get("status") == "error":
                logger.warning("Request for %s failed: %s", container_name, result.get("error"))
                metrics.update_workflow_failed_requests()

                return { "status": "error", "error": f"Request for {container_name} failed: {result.get('error')}" }

            results[container_name] = {
                "mode": result.get("mode"),
                "computation_time_ms": result.get("computation_time_ms", 0),
            }
        total_computation_time_ms = round(sum(r.get("computation_time_ms", 0) for r in results.values()), 2)
        results["total_computation_time_ms"] = total_computation_time_ms
        logger.info("Workflow completed with results: %s", results)
        metrics.update_workflow_successful_requests(total_computation_time_ms)

        return results
