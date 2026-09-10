"""
pip install temporalio httpx 
"""
import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from business_process import config


logger = logging.getLogger("ProcessWorkflow")

RETRY_POLICY = RetryPolicy(maximum_attempts=1)


async def record_workflow_metrics(status: str, total_computation_time_ms: float = 0):
    await workflow.execute_activity(
        "record_workflow_metrics",
        args=[status, total_computation_time_ms],
        start_to_close_timeout=timedelta(seconds=5),
        retry_policy=RETRY_POLICY,
    )


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

        for container_name in config.CONTAINER_NAMES:
            result = await run_request(container_name)

            if result.get("status") == "error":
                logger.warning("Request for %s failed: %s", container_name, result.get("error"))
                await record_workflow_metrics("failed")

                return { "status": "error", "error": f"Request for {container_name} failed: {result.get('error')}" }

            results[container_name] = {
                "mode": result.get("mode"),
                "computation_time_ms": result.get("computation_time_ms", 0),
            }
        total_computation_time_ms = round(sum(r.get("computation_time_ms", 0) for r in results.values()), 2)
        results["total_computation_time_ms"] = total_computation_time_ms
        logger.info("Workflow completed with results: %s", results)
        await record_workflow_metrics("successful", total_computation_time_ms)

        return results
