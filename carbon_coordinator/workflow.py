"""
pip install temporalio pyyaml
"""

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from carbon_coordinator.model import WorkerState
from carbon_coordinator import config
from carbon_coordinator.analyze import analyze
from carbon_coordinator.execute import execute
from carbon_coordinator.plan import plan

logger = logging.getLogger("WorkflowCoordinator")

RETRY_POLICY = RetryPolicy(maximum_attempts=3)
UPDATE_PERIOD_S = config.UPDATE_PERIOD_S
DEFAULT_WARMUP_CYCLES = 3
MAX_WARMUP_CYCLES = 6

@workflow.defn
class CarbonCoordinatorWorkflow:

    def __init__(self):
        self.workers: dict[str, WorkerState] = {}
        self.changes: bool = False
        self.warmup_cycles_by_worker: dict[str, int] = {}
        self.last_action_by_worker: dict[str, str] = {}
        self.last_reason_by_worker: dict[str, str] = {}
        self.last_action_cycle_by_worker: dict[str, int] = {}
        self.last_degrade_reason_by_worker: dict[str, str] = {}
        self.analysis_cycle = 0


    def start_warmup(self, container_name: str, reason: str):
        state = self.workers.get(container_name)
        if state is None:
            return

        if container_name not in self.warmup_cycles_by_worker:
            self.warmup_cycles_by_worker[container_name] = DEFAULT_WARMUP_CYCLES

        state.warmup_cycles_remaining = self.warmup_cycles_by_worker[container_name]
        state.warmup_reason = reason
        state.warmup_cycles_elapsed = 0

    def reset_warmup(self, container_name: str):
        self.warmup_cycles_by_worker[container_name] = DEFAULT_WARMUP_CYCLES
        state = self.workers.get(container_name)
        if state is not None:
            state.warmup_cycles_remaining = 0
            state.warmup_reason = None
            state.warmup_cycles_elapsed = 0

    def record_action(self, container_name: str, action: str, reason: str):
        previous_action = self.last_action_by_worker.get(container_name)
        previous_reason = self.last_reason_by_worker.get(container_name)
        previous_action_cycle = self.last_action_cycle_by_worker.get(container_name)

        if action == "degrade" and reason in {"high_cpu", "suspension"}:
            is_cycle = (
                previous_action == "upgrade"
                and previous_reason == "low_carbon"
                and previous_action_cycle >= self.analysis_cycle - 2
                and self.last_degrade_reason_by_worker.get(container_name) == reason
            )
            if is_cycle:
                current_cycles = self.warmup_cycles_by_worker.setdefault(container_name, DEFAULT_WARMUP_CYCLES)
                self.warmup_cycles_by_worker[container_name] = min(current_cycles + 1, MAX_WARMUP_CYCLES)
                logger.info("Loop detected for %s: reason=%s, new warmup=%d",container_name,reason,self.warmup_cycles_by_worker[container_name])
            else:
                self.reset_warmup(container_name)
                self.last_degrade_reason_by_worker.pop(container_name, None)

            self.last_degrade_reason_by_worker[container_name] = reason
        elif action == "degrade":
            self.reset_warmup(container_name)
            self.last_degrade_reason_by_worker.pop(container_name, None)

        self.last_action_by_worker[container_name] = action
        self.last_reason_by_worker[container_name] = reason
        self.last_action_cycle_by_worker[container_name] = self.analysis_cycle


    @workflow.signal
    async def state_update(self, state: WorkerState):
        logger.debug("received state update for '%s'", state.container_name)

        previous_state = self.workers.get(state.container_name)
        if previous_state and previous_state.suspended and not state.suspended:
            state.warmup_cycles_remaining = self.warmup_cycles_by_worker.get(
                state.container_name, DEFAULT_WARMUP_CYCLES
            )
            state.warmup_reason = "suspension"
            state.warmup_cycles_elapsed = 0
        elif previous_state:
            state.warmup_cycles_remaining = previous_state.warmup_cycles_remaining
            state.warmup_reason = previous_state.warmup_reason
            state.warmup_cycles_elapsed = previous_state.warmup_cycles_elapsed

        self.workers[state.container_name] = state
        self.changes = True


    def decrement_warmup_cycles(self):
        for container_name, state in self.workers.items():
            if state.warmup_cycles_remaining <= 0:
                continue

            state.warmup_cycles_remaining -= 1
            state.warmup_cycles_elapsed += 1
            if state.warmup_cycles_remaining == 0:
                state.warmup_reason = None
                state.warmup_cycles_elapsed = 0


    @workflow.run
    async def run(self, evaluation_interval: int = UPDATE_PERIOD_S):
        logger.info("started with evaluation interval of %d seconds", evaluation_interval)
        while True:
            await workflow.sleep(timedelta(seconds=evaluation_interval))

            if not self.changes:
                continue
            self.changes = False
            self.analysis_cycle += 1

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

                self.record_action(container_name, analysis.action, analysis.reason)
                if analysis.action == "degrade" and analysis.reason in {"high_cpu", "suspension"}:
                    self.start_warmup(container_name, analysis.reason)
