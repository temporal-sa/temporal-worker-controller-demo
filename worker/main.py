"""Versioned Temporal worker — reads controller-injected env and exposes readiness on :8080."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from temporalio.client import Client
from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.worker import Worker, WorkerDeploymentConfig

from activity.demo_activity import probe_version, slow_step
from workflows.workflow_a import PinnedDemoWorkflow
from workflows.workflow_b import AutoUpgradeDemoWorkflow
from workflows.workflow_c import RollbackWorkflow, RolloutGateWorkflow


def _registered_workflows() -> list[type]:
    """Pinned + AutoUpgrade always; omit gate workflows on v-b (DEMO_OMIT_ROLLOUT_GATE=1)."""
    w: list[type] = [PinnedDemoWorkflow, AutoUpgradeDemoWorkflow]
    omit = os.environ.get("DEMO_OMIT_ROLLOUT_GATE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not omit:
        w.extend((RollbackWorkflow, RolloutGateWorkflow))
    return w


async def _readiness_server() -> None:
    await asyncio.sleep(5)

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read(4096)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "0.0.0.0", 8080)
    async with server:
        await server.serve_forever()


async def _connect_client() -> Client:
    address = os.environ["TEMPORAL_ADDRESS"]
    namespace = os.environ["TEMPORAL_NAMESPACE"]
    api_key = os.environ.get("TEMPORAL_API_KEY")
    if api_key:
        return await Client.connect(
            address,
            namespace=namespace,
            api_key=api_key,
            tls=True,
        )
    return await Client.connect(address, namespace=namespace)


async def main() -> None:
    deployment_name = os.environ["TEMPORAL_DEPLOYMENT_NAME"]
    build_id = os.environ["TEMPORAL_WORKER_BUILD_ID"]
    task_queue = os.environ["TEMPORAL_TASK_QUEUE"]

    asyncio.create_task(_readiness_server())

    temporal_client = await _connect_client()
    dep = WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(
            deployment_name=deployment_name,
            build_id=build_id,
        ),
        use_worker_versioning=True,
        default_versioning_behavior=VersioningBehavior.UNSPECIFIED,
    )
    worker = Worker(
        temporal_client,
        task_queue=task_queue,
        workflows=_registered_workflows(),
        activities=[probe_version, slow_step],
        deployment_config=dep,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
