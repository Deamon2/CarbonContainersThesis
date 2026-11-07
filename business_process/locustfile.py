'''
pip install gevent locust temporalio
locust -f business_process/locustfile.py --headless
'''

import asyncio
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import gevent
from locust import LoadTestShape, User, constant, events, task
from temporalio.client import Client

from business_process import locust_shapes
from business_process.workflow import ProcessWorkflow

TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "process-tasks"
WORKFLOW_ID_PREFIX = "process"
SHUTDOWN_TIMEOUT_SECONDS = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("locust")


@dataclass
class WorkflowResult:
    workflow_id: str
    scheduled_at: float
    started_at: float
    finished_at: float
    result: object = None
    error: Optional[BaseException] = None

class WorkflowExecutor:
    """ Führt temporal Workflows aus """
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.client: Optional[Client] = None
        self.thread: Optional[threading.Thread] = None
        self.ready = threading.Event()
        self.startup_error: Optional[Exception] = None
        self.results: "queue.SimpleQueue[WorkflowResult]" = queue.SimpleQueue()

    def start(self):
        if self.thread:
            return
        self.thread = threading.Thread(target=self.run_temporal_loop, daemon=True, name="temporal-load-executor")
        self.thread.start()
        self.ready.wait()
        if self.startup_error:
            raise self.startup_error

    def run_temporal_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.client = self.loop.run_until_complete(Client.connect(TEMPORAL_ADDRESS))
        except Exception as exc:
            self.startup_error = exc
            self.ready.set()
            self.loop.close()
            return
        self.ready.set()
        self.loop.run_forever()
        self.loop.close()

    def submit(self, scheduled_at: float):
        if not self.client:
            raise RuntimeError("Temporal executor is not ready")
        future = asyncio.run_coroutine_threadsafe(self.execute_workflow(scheduled_at), self.loop)
        future.add_done_callback(self.handle_completion)

    async def execute_workflow(self, scheduled_at: float):
        workflow_id = f"{WORKFLOW_ID_PREFIX}-{uuid.uuid4()}"
        started_at = time.perf_counter()
        try:
            handle = await self.client.start_workflow(ProcessWorkflow.run, id=workflow_id, task_queue=TASK_QUEUE)
            result = await handle.result()
            return WorkflowResult(workflow_id, scheduled_at, started_at, time.perf_counter(), result=result)
        except Exception as exc:
            return WorkflowResult(workflow_id, scheduled_at, started_at, time.perf_counter(), error=exc)

    def handle_completion(self, future: "asyncio.Future[WorkflowResult]"):
        try:
            self.results.put(future.result())
        except Exception as exc:
            self.results.put(WorkflowResult("unknown", 0.0, 0.0, time.perf_counter(), error=exc))

    def stop(self, timeout: float = SHUTDOWN_TIMEOUT_SECONDS):
        if self.loop and not self.loop.is_closed():
            shutdown = asyncio.run_coroutine_threadsafe(self.await_pending_tasks(timeout), self.loop)
            shutdown.result(timeout + 1)
        if self.thread:
            self.thread.join(timeout=timeout)
        self.loop = None
        self.client = None
        self.thread = None
        self.ready.clear()

    async def await_pending_tasks(self, timeout: float):
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks(self.loop) if t is not current]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=timeout)
        asyncio.get_running_loop().stop()


class OpenLoopScheduler:
    """ Scheduled Workflow Executions basierend auf LoadShapes rps Vorgaben """

    def __init__(self, executor: WorkflowExecutor):
        self.executor = executor
        self.target_rps = 0.0
        self.running = False
        self.greenlet = None

    def start(self):
        if not self.greenlet:
            self.running = True
            self.greenlet = gevent.spawn(self.scheduling_loop)

    def stop(self):
        self.running = False
        if self.greenlet:
            self.greenlet.join(timeout=5)
        self.greenlet = None
        self.drain_results()

    def scheduling_loop(self):
        next_start = time.perf_counter()
        while self.running:
            self.drain_results()
            rps = self.target_rps
            if rps <= 0:
                next_start = time.perf_counter()
                gevent.sleep(0.05)
                continue

            interval = 1.0 / rps
            next_start, skipped = self.advance_schedule(next_start, interval, time.perf_counter())
            if skipped:
                logger.warning("Skipped %d overdue workflow slots", skipped)

            gevent.sleep(max(0.0, next_start - time.perf_counter()))
            if not self.running:
                break

            self.submit_scheduled_workflow(next_start)
            next_start += interval
        self.drain_results()

    def advance_schedule(self, next_start: float, interval: float, now: float):
        if now <= next_start + interval:
            return next_start, 0
        skipped = int((now - next_start) // interval)
        return next_start + skipped * interval, skipped

    def submit_scheduled_workflow(self, scheduled_at: float):
        try:
            self.executor.submit(scheduled_at)
            error = None
        except Exception as exc:
            error = exc
        events.request.fire(
            request_type="temporal",
            name="ProcessWorkflow.enqueue",
            response_time=(time.perf_counter() - scheduled_at) * 1000,
            response_length=0,
            exception=error,
        )

    def drain_results(self):
        while True:
            try:
                outcome = self.executor.results.get_nowait()
            except queue.Empty:
                return
            events.request.fire(
                request_type="temporal",
                name="ProcessWorkflow.run",
                response_time=(outcome.finished_at - outcome.started_at) * 1000,
                response_length=0,
                exception=outcome.error,
            )
            if outcome.error:
                logger.warning("Workflow %s failed: %s", outcome.workflow_id, outcome.error)
            else:
                logger.info(
                    "Workflow %s finished in %.1f ms (scheduler delay %.1f ms): %s",
                    outcome.workflow_id,
                    (outcome.finished_at - outcome.started_at) * 1000,
                    (outcome.started_at - outcome.scheduled_at) * 1000,
                    outcome.result,
                )


executor = WorkflowExecutor()
scheduler = OpenLoopScheduler(executor)


@events.test_start.add_listener
def start_open_loop(_environment=None, **_kwargs):
    executor.start()
    scheduler.start()


@events.test_stop.add_listener
def stop_open_loop(_environment=None, **_kwargs):
    scheduler.stop()
    executor.stop()


class SchedulerUser(User):
    # dummy user für Locust
    wait_time = constant(3600)

    @task
    def idle(self):
        pass


SHAPES = {
    "constant": locust_shapes.ConstantLoadShape,
    "steady": locust_shapes.SteadyLoadShape,
    "fluctuation": locust_shapes.FluctuationLoadShape,
    "spike": locust_shapes.SpikeLoadShape,
}


@events.init_command_line_parser.add_listener
def add_shape_argument(parser):
    parser.add_argument("--shape", choices=SHAPES, default="constant")


class DynamicLoadShape(LoadTestShape):
    def __init__(self):
        super().__init__()
        self.selected_shape = None

    def tick(self):
        if self.selected_shape is None:
            self.selected_shape = SHAPES[self.runner.environment.parsed_options.shape]()
        rps = self.selected_shape.tick(self.get_run_time())
        scheduler.target_rps = 0.0 if rps is None else rps
        return None if rps is None else (1, 1, [SchedulerUser])
