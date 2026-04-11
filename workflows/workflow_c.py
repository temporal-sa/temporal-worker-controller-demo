"""Rollback / rollout-gate workflow — single probe; Auto-Upgrade versioning.

TWD `spec.rollout.gate.workflowType` may be `RollbackWorkflow` (this repo) or
`RolloutGate` (common controller samples). Both types share the same implementation
so v-a handles either; v-b omits both when DEMO_OMIT_ROLLOUT_GATE is set.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import VersioningBehavior

with workflow.unsafe.imports_passed_through():
    from activity.demo_activity import probe_version


async def _rollback_probe_run() -> str:
    result = await workflow.execute_activity(
        probe_version,
        start_to_close_timeout=timedelta(seconds=10),
    )
    if not str(result).startswith("ok-"):
        raise workflow.ApplicationError(f"unexpected probe result: {result!r}")
    return result


@workflow.defn(name="RollbackWorkflow", versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class RollbackWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await _rollback_probe_run()


@workflow.defn(name="RolloutGate", versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class RolloutGateWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await _rollback_probe_run()
