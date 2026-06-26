'''
pip install locust nest_asyncio temporalio
'''

import asyncio
import nest_asyncio
import time
import uuid
import logging

from locust import User, task, events, LoadTestShape, constant_throughput

from temporalio.client import Client
from business_process.workflow import ProcessWorkflow


nest_asyncio.apply()


TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "process-tasks"
WORKFLOW_ID_PREFIX = "process"


logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
logger = logging.getLogger("locust")


client = None
client_lock = asyncio.Lock()

async def get_client():
    global client
    if client is not None:
        return client

    async with client_lock:
        if client is None:
            client = await Client.connect(TEMPORAL_ADDRESS)
        return client

class WorkflowUser(User):

    TARGET_RPS = 4
    REQUEST_TIMEOUT_S = 10

    wait_time = constant_throughput(1 / REQUEST_TIMEOUT_S)

    @task
    def run_workflow(self):
        asyncio.run(self.execute_workflow())

    async def execute_workflow(self):
        workflow_id = f"{WORKFLOW_ID_PREFIX}-{uuid.uuid4()}"
        start_ms = time.perf_counter() * 1000

        try:
            client = await get_client()

            handle = await client.start_workflow(
                ProcessWorkflow.run,
                id=workflow_id,
                task_queue=TASK_QUEUE,
            )
            result = await handle.result()

            elapsed = (time.perf_counter() * 1000) - start_ms

            events.request.fire(
                request_type="temporal",
                name="ProcessWorkflow.run",
                response_time=elapsed,
                response_length=0,
                exception=None,
            )

            logger.info("Workflow %s finished in %.1f ms: %s", workflow_id, elapsed, result)

        except Exception as exc:
            elapsed = time.perf_counter() * 1000 - start_ms
            events.request.fire(
                request_type="temporal",
                name="ProcessWorkflow.run",
                response_time=elapsed,
                response_length=0,
                exception=exc,
            )

            logger.warning("Workflow %s failed after %.1f ms: %s", workflow_id, elapsed, exc)


class WorkflowShape(LoadTestShape):
    def tick(self):
        user_count = WorkflowUser.TARGET_RPS * WorkflowUser.REQUEST_TIMEOUT_S
        return user_count, WorkflowUser.TARGET_RPS
