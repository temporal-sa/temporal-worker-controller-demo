"""Scenario D — Pinned workflow that continue-as-new with AUTO_UPGRADE.

Generation 0 is PINNED (decorator default), so the workflow stays on the build
that started it through the 2 minute 30 second timer. When the timer fires, it
calls ``continue_as_new`` with ``initial_versioning_behavior=AUTO_UPGRADE`` so
the next run's first task can land on whichever build is Current at that
moment. Generation 1 probes the worker version and completes.

Demo idea: start Scenario D, roll forward v-a -> v-b during the 2:30 wait.
Gen 0 finishes on the pinned starting build; gen 1 begins on Current (often the
newer build), demonstrating that continue-as-new is a safe handoff boundary
between worker versions.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import VersioningBehavior

with workflow.unsafe.imports_passed_through():
    from activity.demo_activity import probe_version


_CAN_TIMER = timedelta(seconds=150)


@workflow.defn(name="PinnedCanDemo", versioning_behavior=VersioningBehavior.PINNED)
class PinnedCanDemoWorkflow:
    @workflow.run
    async def run(self, generation: int = 0) -> str:
        probe = await workflow.execute_activity(
            probe_version,
            start_to_close_timeout=timedelta(seconds=30),
        )
        if generation == 0:
            await workflow.sleep(_CAN_TIMER)
            workflow.continue_as_new(
                1,
                initial_versioning_behavior=workflow.ContinueAsNewVersioningBehavior.AUTO_UPGRADE,
            )
        return f"gen={generation} probe={probe}"
