'''
pip install locust nest_asyncio temporalio
'''

import asyncio
import logging
from random import random
import time
import uuid
import nest_asyncio

from locust import User, task, events, LoadTestShape, constant_throughput

from temporalio.client import Client
from business_process.workflow import ProcessWorkflow
from business_process import locust_shapes


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

    pacing_granularity_s = 20.0  # -> 0.05 rps/User

    wait_time = constant_throughput(1 / pacing_granularity_s)

    def on_start(self):
        time.sleep(random.uniform(0, self.pacing_granularity_s))

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


SHAPES = {
    "constant": locust_shapes.ConstantLoadShape,
    "steady": locust_shapes.SteadyLoadShape,
    "fluctuation": locust_shapes.FluctuationLoadShape,
    "spike": locust_shapes.SpikeLoadShape,
}


@events.init_command_line_parser.add_listener
def add_shape_argument(parser):
    parser.add_argument(
        "--shape",
        default="constant",
    )


class DynamicLoadShape(LoadTestShape):
    def __init__(self):
        super().__init__()
        self.selected_shape = None

    def get_selected_shape(self):
        if self.selected_shape is None:
            shape_name = self.runner.environment.parsed_options.shape
            self.selected_shape = SHAPES[shape_name]()
            self.selected_shape.runner = self.runner
        return self.selected_shape

    def tick(self):
        return self.get_selected_shape().tick()
