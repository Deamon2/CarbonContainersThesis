"""
pip install temporalio pyyaml
"""

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from carbon_process.model import WorkerState
from carbon_process import config
from carbon_process.analyze import analyze
from carbon_process.execute import execute
from carbon_process.plan import plan

logger = logging.getLogger("WorkflowCoordinator")

RETRY_POLICY = RetryPolicy(maximum_attempts=3)
UPDATE_PERIOD_S = config.UPDATE_PERIOD_S

@workflow.defn
class CarbonCoordinatorWorkflow:

    def __init__(self):
        self.workers: dict[str, WorkerState] = {}
        self.changes: bool = False


    @workflow.signal
    async def state_update(self, state: WorkerState):
        logger.debug("received state update for '%s'", state.container_name)

        previous_state = self.workers.get(state.container_name)
        if previous_state and previous_state.suspended and not state.suspended:
            state.warmup_cycles_remaining = 2

        self.workers[state.container_name] = state
        self.changes = True

    def decrement_warmup_cycles(self):
        for state in self.workers.values():
            if state.suspended or state.warmup_cycles_remaining <= 0:
                continue

            state.warmup_cycles_remaining -= 1


    @workflow.run
    async def run(self, evaluation_interval: int = UPDATE_PERIOD_S):
        logger.info("started with evaluation interval of %d seconds", evaluation_interval)
        while True:
            await workflow.sleep(timedelta(seconds=evaluation_interval))

            if not self.changes:
                continue
            self.changes = False

            # ANALYZE whether any changes are needed 
            analysis_results = await workflow.execute_activity(
                analyze,
                args=[self.workers],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RETRY_POLICY,
            )
            self.decrement_warmup_cycles()
            
            if not analysis_results:
                continue

            # PLAN and EXECUTE for each analysis result
            for analysis in analysis_results:
                # PLAN: Decide which changes should be made
                container_name, flag_name, flag_state, degradation_status = await workflow.execute_activity(
                    plan,
                    args=[analysis],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RETRY_POLICY,
                )

                if not flag_name:
                    continue

                # EXECUTE: Apply decisions and update Prometheus metrics
                result = await workflow.execute_activity(
                    execute,
                    args=[container_name, flag_name, flag_state, degradation_status],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RETRY_POLICY,
                )

                if not result:
                    continue
