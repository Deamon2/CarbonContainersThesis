import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from business_process.workflow import ProcessWorkflow
from business_process.request import request
from business_process.metrics_server import record_workflow_metrics


TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "process-tasks"

async def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("start_worker")

    client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ProcessWorkflow],
        activities=[request, record_workflow_metrics],
        identity=f"process-worker-{os.getpid()}",
    )

    logger.info("Worker started")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
