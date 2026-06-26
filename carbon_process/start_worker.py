import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from carbon_process.analyze import analyze
from carbon_process.execute import execute
from carbon_process.workflow import CarbonCoordinatorWorkflow
from carbon_process.plan import plan


TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "feature-degradation"


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("start_worker")

    client = await Client.connect(TEMPORAL_ADDRESS)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CarbonCoordinatorWorkflow],
        activities=[analyze, plan, execute],
    )

    logger.info("Worker started")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
