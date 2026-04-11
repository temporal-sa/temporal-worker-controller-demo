"""Dev-only API: start demo workflows and surface TemporalWorkerDeployment status from Kubernetes."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from temporalio.client import Client
from temporalio.common import (
    PinnedVersioningOverride,
    WorkerDeploymentVersion,
)

from workflows.workflow_a import PinnedDemoWorkflow
from workflows.workflow_b import AutoUpgradeDemoWorkflow
from workflows.workflow_c import RollbackWorkflow


def _load_kube() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await asyncio.to_thread(_load_kube)
    app.state.temporal_client = await _connect_temporal()
    yield


app = FastAPI(title="worker-controller-demo API", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _summarize_twd_status(status: dict[str, Any]) -> tuple[str, str, bool]:
    """Returns (phase_id, human_summary, rollout_complete_heuristic)."""
    conditions_list = status.get("conditions") or []
    by_type = {c.get("type"): c for c in conditions_list if c.get("type")}
    progressing = by_type.get("Progressing", {})
    ready = by_type.get("Ready", {})
    prog_status = progressing.get("status")
    ready_status = ready.get("status")
    reason = progressing.get("reason") or ""

    target = status.get("targetVersion") or {}
    t_build = target.get("buildID") or "?"
    t_state = target.get("status") or ""
    ramp = target.get("rampPercentage")

    current = status.get("currentVersion") or {}
    c_build = current.get("buildID") if isinstance(current, dict) else None

    if reason == "WaitingForPollers":
        return (
            "waiting_pollers",
            "Target worker Deployment exists; waiting for pods to poll Temporal and register the new build.",
            False,
        )
    if reason == "WaitingForPromotion":
        return (
            "waiting_promotion",
            "Version registered (often Inactive) or rollback workflow not finished; promotion to Current/Ramping has not finished yet.",
            False,
        )
    if reason == "Ramping":
        pct = ramp if ramp is not None else "?"
        return (
            "ramping",
            f"Progressive rollout: ~{pct}% of new workflows routed to target build {t_build} (Temporal Current/Ramp split).",
            False,
        )
    if (
        ready_status == "True"
        and prog_status == "False"
        and reason == "RolloutComplete"
    ):
        cur = c_build or t_build
        return (
            "steady",
            f"Rollout complete. Current build: {cur}. New workflows use this version unless a new target is introduced.",
            True,
        )
    if reason == "TemporalConnectionNotFound":
        return ("error", "TemporalConnection reference missing or not found.", False)
    if reason == "AuthSecretInvalid":
        return ("error", "Temporal auth secret invalid or certificate problem.", False)
    if reason == "TemporalClientCreationFailed":
        return ("error", "Controller cannot reach Temporal (network or TLS).", False)

    return (
        "other",
        f"Progressing={prog_status} Ready={ready_status} reason={reason or 'n/a'} "
        f"targetStatus={t_state} targetBuild={t_build}",
        prog_status == "False" and ready_status == "True",
    )


def _fetch_twd() -> dict[str, Any]:
    ns = os.environ["K8S_NAMESPACE"]
    name = os.environ["K8S_TWD_NAME"]
    api = client.CustomObjectsApi()
    return api.get_namespaced_custom_object(
        group="temporal.io",
        version="v1alpha1",
        namespace=ns,
        plural="temporalworkerdeployments",
        name=name,
    )


async def _connect_temporal() -> Client:
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


def _temporal_client(request: Request) -> Client:
    return request.app.state.temporal_client


async def _pinned_override_from_twd_current() -> PinnedVersioningOverride | None:
    """Pin new PinnedDemo runs to the TWD *current* build so ramping does not send them to B.

    Without this, Pinned and Auto-Upgrade share the same Current-vs-Ramping lottery for the
    first task (workflow ID + ramp %), so Scenario A can start on v-b even when v-a is Current.
    """
    try:
        obj = await asyncio.to_thread(_fetch_twd)
    except ApiException:
        return None
    status = obj.get("status") or {}
    current = status.get("currentVersion")
    if not isinstance(current, dict):
        return None
    build_id = current.get("buildID")
    if not build_id or not isinstance(build_id, str):
        return None
    dep_name = (
        os.environ.get("TEMPORAL_DEPLOYMENT_NAME", "").strip()
        or os.environ.get("K8S_TWD_NAME", "").strip()
    )
    if not dep_name:
        return None
    return PinnedVersioningOverride(
        version=WorkerDeploymentVersion(
            deployment_name=dep_name,
            build_id=build_id,
        )
    )


async def _pinned_override_from_twd_target() -> PinnedVersioningOverride | None:
    """Pin RollbackWorkflow to the TWD *target* build (candidate / v-b during ramp).

    Scenario A pins to *current* so the first task stays on stable A. Scenario C pins to
    *target* so the gate runs on the version receiving rollout traffic. If v-b omits
    RollbackWorkflow (DEMO_OMIT_ROLLOUT_GATE), the workflow stalls or times out there
    instead of succeeding on v-a by accident.
    """
    try:
        obj = await asyncio.to_thread(_fetch_twd)
    except ApiException:
        return None
    status = obj.get("status") or {}
    target = status.get("targetVersion")
    if not isinstance(target, dict):
        return None
    build_id = target.get("buildID")
    if not build_id or not isinstance(build_id, str):
        return None
    dep_name = (
        os.environ.get("TEMPORAL_DEPLOYMENT_NAME", "").strip()
        or os.environ.get("K8S_TWD_NAME", "").strip()
    )
    if not dep_name:
        return None
    return PinnedVersioningOverride(
        version=WorkerDeploymentVersion(
            deployment_name=dep_name,
            build_id=build_id,
        )
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/deployment/status")
async def deployment_status() -> dict[str, Any]:
    try:
        obj = await asyncio.to_thread(_fetch_twd)
    except ApiException as e:
        raise HTTPException(status_code=502, detail=f"kubernetes: {e.reason}") from e
    status = obj.get("status") or {}
    phase, summary, complete = _summarize_twd_status(status)
    return {
        "phase": phase,
        "summary": summary,
        "rolloutComplete": complete,
        "status": status,
    }


@app.post("/api/scenarios/{scenario}")
async def start_scenario(
    scenario: str, tc: Client = Depends(_temporal_client)
) -> dict[str, str]:
    s = scenario.lower()
    # Prefer pinned | auto | rollback in the UI (clearer than /b for proxies); keep a|b|c for scripts.
    alias = {"a": "pinned", "b": "auto", "c": "rollback"}
    s = alias.get(s, s)
    if s not in {"pinned", "auto", "rollback"}:
        raise HTTPException(
            status_code=400,
            detail="scenario must be pinned, auto, rollback (or legacy a, b, c)",
        )
    task_queue = os.environ["TEMPORAL_TASK_QUEUE"]
    suffix = uuid.uuid4().hex[:8]
    if s == "pinned":
        wid = f"pinned-demo-{suffix}"
        pin = await _pinned_override_from_twd_current()
        start_kw: dict[str, Any] = {"id": wid, "task_queue": task_queue}
        if pin is not None:
            start_kw["versioning_override"] = pin
        await tc.start_workflow(PinnedDemoWorkflow.run, **start_kw)
        return {"workflow_id": wid, "workflow_type": "PinnedDemo"}
    if s == "auto":
        wid = f"auto-demo-{suffix}"
        # Do not pass a long execution_timeout here: some servers reject starts above a namespace max.
        # Keep AutoUpgradeDemo total duration under common defaults (~see workflow_b sleep).
        await tc.start_workflow(
            AutoUpgradeDemoWorkflow.run,
            id=wid,
            task_queue=task_queue,
        )
        return {"workflow_id": wid, "workflow_type": "AutoUpgradeDemo"}
    wid = f"rollback-demo-{suffix}"
    pin_target = await _pinned_override_from_twd_target()
    start_kw: dict[str, Any] = {
        "id": wid,
        "task_queue": task_queue,
        "execution_timeout": timedelta(seconds=60),
        "run_timeout": timedelta(seconds=60),
    }
    if pin_target is not None:
        start_kw["versioning_override"] = pin_target
    await tc.start_workflow(RollbackWorkflow.run, **start_kw)
    return {"workflow_id": wid, "workflow_type": "RollbackWorkflow"}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    run()
