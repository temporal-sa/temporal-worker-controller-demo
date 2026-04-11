"""Pinned long-running demo workflow."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import VersioningBehavior

with workflow.unsafe.imports_passed_through():
    from activity.demo_activity import probe_version


@workflow.defn(name="PinnedDemo", versioning_behavior=VersioningBehavior.PINNED)
class PinnedDemoWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(seconds=90))
        return await workflow.execute_activity(
            probe_version,
            start_to_close_timeout=timedelta(seconds=30),
        )
