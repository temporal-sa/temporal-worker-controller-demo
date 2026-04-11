"""Auto-upgrade short demo workflow."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import VersioningBehavior

with workflow.unsafe.imports_passed_through():
    from activity.demo_activity import probe_version


# Sleep between probes so you can finish promotion (B → Current) and often see a
# different build on the second activity. Safe only if every polling worker
# image (v-a, v-b) ships this same workflow definition—rebuild both tags from
# the same source; env-only differences (DEMO_WORKER_VERSION, RollbackWorkflow omit) are OK.
# Keep total run within namespace execution defaults when none is set on start (~210s with 30s activity timeouts).
_OBSERVE_UPGRADE_SLEEP = timedelta(seconds=150)


@workflow.defn(name="AutoUpgradeDemo", versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class AutoUpgradeDemoWorkflow:
    @workflow.run
    async def run(self) -> str:
        first = await workflow.execute_activity(
            probe_version,
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.sleep(_OBSERVE_UPGRADE_SLEEP)
        second = await workflow.execute_activity(
            probe_version,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return f"{first} -> {second}"
