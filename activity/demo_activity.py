"""Demo activities — import directly from this module (no package re-exports)."""

from __future__ import annotations

import asyncio
import os

from temporalio import activity


@activity.defn
async def probe_version() -> str:
    """Returns a payload that changes per worker image (not replay-safe across versions)."""
    ver = os.environ.get("DEMO_WORKER_VERSION", "unknown")
    return f"ok-{ver}"


@activity.defn
async def slow_step(seconds: int) -> str:
    """Simulates external latency inside an activity (pinned demos can overlap rollouts)."""
    await asyncio.sleep(max(1, min(seconds, 600)))
    return "slow-step-done"
