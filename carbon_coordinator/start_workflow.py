import asyncio
import logging

from temporalio.client import Client

from carbon_coordinator.workflow import CarbonCoordinatorWorkflow

TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "feature-degradation"
WORKFLOW_ID = "carbon-coordinator"


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("start_workflow")

    client = await Client.connect(TEMPORAL_ADDRESS)

    handle = await client.start_workflow(
        CarbonCoordinatorWorkflow.run,
        id=WORKFLOW_ID,
        task_queue=TASK_QUEUE,
    )
    logger.info("Workflow started")


if __name__ == "__main__":
    asyncio.run(main())
