# Temporal Worker Controller demo

## Purpose

This repo shows how **[Worker Versioning](https://docs.temporal.io/worker-versioning)** and the **[Temporal Worker Controller](https://github.com/temporalio/temporal-worker-controller)** work together: a **TemporalWorkerDeployment** drives progressive rollout, optional **gate** workflows, drainage, and sunset. A small **FastAPI** service starts test workflows and reads TWD status from Kubernetes; a **Vite + React** UI runs the scenarios and mirrors rollout state.

## Repository layout

- `activity/`: `probe_version`, `slow_step`
- `workflows/`: `PinnedDemo`, `AutoUpgradeDemo`, `RollbackWorkflow` / `RolloutGate` (same logic; gate type matches `spec.rollout.gate.workflowType` or older `RolloutGate` samples)
- `worker/`: versioned worker (`WorkerDeploymentConfig`, readiness `:8080`)
- `api/`: `demo-api` (start workflows, `GET /api/deployment/status`)
- `web/`: UI (proxies `/api` to the API)
- `k8s/`: `TemporalConnection`, `TemporalWorkerDeployment` examples

Empty `__init__.py` files exist for packaging; import concrete modules directly (e.g. `from activity.demo_activity import …`).

Treat **this folder** as the **git repository root** (so `.gitignore` applies to `web/node_modules/`). If you already ran `git add web/node_modules` once, Git keeps tracking those paths until you run `git rm -r --cached web/node_modules`.

## Prerequisites

### Local machine

| Item | Notes |
|------|--------|
| **Rancher Desktop** | Enable **Kubernetes**; use embedded **Docker** so `docker build` images are visible to the cluster (`docker` and `kubectl` share the same engine). |
| **kubectl** | `kubectl config current-context` should point at Rancher’s cluster. |
| **Helm 3** | For cert-manager and the worker-controller charts. |
| **Docker** | Build worker images `worker-controller-demo:v-a` / `:v-b`. |
| **uv** | `uv sync`, `uv run demo-api`. |
| **Node.js + npm** | `cd web && npm install && npm run dev`. |

### Temporal

- **Temporal Cloud** with Worker Versioning / Worker Deployments, **or** self-hosted Temporal **≥ 1.29.1** with the same features.

### Cluster: cert-manager + worker controller

Install **cert-manager** (TLS for validating webhooks; recommended if you use `WorkerResourceTemplate`):

```bash
helm repo add jetstack https://charts.jetstack.io --force-update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace --set crds.enabled=true
```

Install **CRDs** then the **controller** (replace `<VERSION>` with a [release](https://github.com/temporalio/temporal-worker-controller/releases) tag):

```bash
helm install temporal-worker-controller-crds \
  oci://docker.io/temporalio/temporal-worker-controller-crds \
  --version <VERSION> --namespace temporal-system --create-namespace

helm install temporal-worker-controller \
  oci://docker.io/temporalio/temporal-worker-controller \
  --version <VERSION> --namespace temporal-system
```

Sanity checks:

```bash
kubectl get pods -n temporal-system
kubectl get crd | grep temporal.io
```

Apply the steps below **after** the controller is running. The **Temporal Worker Controller** watches `TemporalConnection` and `TemporalWorkerDeployment` in your cluster; workers in pods use the same Temporal endpoint and API key you configure in Kubernetes (not the React UI).

## One-time cluster + image setup

### Namespace and API key secret (cluster)

Workers and `TemporalConnection` need a **Kubernetes Secret** with your Temporal Cloud API key (create a key in the Temporal Cloud UI). Use the placeholder below; **do not commit real keys** into YAML or this repo.

```bash
kubectl create namespace worker-controller-demo
kubectl create secret generic temporal-api-key -n worker-controller-demo \
  --from-literal=api-key='YOUR_API_KEY'
```

- Secret name **`temporal-api-key`**, data key **`api-key`**, must match what the manifests reference (`spec.apiKeySecretRef` on `TemporalConnection` and `secretKeyRef` on worker pods in the TWD template).
- To rotate: `kubectl delete secret temporal-api-key -n worker-controller-demo` and recreate, then restart affected pods if needed.

### TemporalConnection (cluster)

The connection CR tells the controller how workers reach Temporal. Copy the example, set **`spec.hostPort`** to your **regional** gRPC host (Temporal Cloud: same region as in the Cloud UI; API keys do not use the old `*.tmprl.cloud` host for gRPC in many setups).

```bash
cp k8s/temporal-connection.example.yaml k8s/temporal-connection.yaml
# Edit spec.hostPort in k8s/temporal-connection.yaml if it differs from your region.
kubectl apply -f k8s/temporal-connection.yaml
```

`k8s/temporal-connection.example.yaml` documents the secret shape. In this repo, generated copies **`k8s/temporal-connection.yaml`** and **`k8s/temporal-worker-deployment.yaml`** (with your namespace and edits) are listed in **`.gitignore`** so they are not committed by mistake.

### Worker images

```bash
docker build -t worker-controller-demo:v-a --build-arg DEMO_WORKER_VERSION=a .
docker build -t worker-controller-demo:v-b --build-arg DEMO_WORKER_VERSION=b \
  --build-arg DEMO_OMIT_ROLLOUT_GATE=1 .
```

`v-b` **does not** register the gate workflow types (`DEMO_OMIT_ROLLOUT_GATE=1`) so Scenario **C** and the controller gate can fail on **B** while **A/B** demos still run.

### TemporalWorkerDeployment (cluster)

```bash
cp k8s/temporal-worker-deployment.example.yaml k8s/temporal-worker-deployment.yaml
# Set spec.workerOptions.temporalNamespace in temporal-worker-deployment.yaml and temporal-worker-deployment.v-b.yaml
# Worker pods read TEMPORAL_API_KEY from the temporal-api-key secret (same as TemporalConnection).

kubectl apply -f k8s/temporal-worker-deployment.yaml
kubectl get twd -n worker-controller-demo
```

## Local `.env` (laptop API and optional local worker)

The **web UI never stores the Temporal API key**; only the FastAPI process on your machine uses it. Copy the example file and fill in values that **match** your cluster manifests and Temporal namespace.

```bash
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `TEMPORAL_ADDRESS` | Same gRPC **host:port** as `TemporalConnection.spec.hostPort` (regional Cloud endpoint when using API keys). |
| `TEMPORAL_NAMESPACE` | Same as `spec.workerOptions.temporalNamespace` on your TWD. |
| `TEMPORAL_API_KEY` | Same secret **value** you put in the `temporal-api-key` Kubernetes secret (local use only). |
| `TEMPORAL_TASK_QUEUE` | Same as `TEMPORAL_TASK_QUEUE` in the TWD pod template. |
| `K8S_NAMESPACE` | Namespace where `TemporalConnection` and TWD live (e.g. `worker-controller-demo`). |
| `K8S_TWD_NAME` | `metadata.name` of your `TemporalWorkerDeployment` resource. |
| `TEMPORAL_DEPLOYMENT_NAME` | Optional; must match the worker deployment name the controller sets on pods if it differs from `K8S_TWD_NAME` (needed for Scenario A pin). |

**Rules:** Keep **`.env` out of git** (it is listed in `.gitignore`). Do not paste real API keys into `README.md`, committed YAML, or the UI repo. Use **`.env.example`** only as a template (no secrets in that file).

**Kubernetes access:** `demo-api` uses your **kubeconfig** (same context as `kubectl`) to read TWD status. If status stays empty, run `kubectl config current-context` and `kubectl get twd -n worker-controller-demo` from the same machine.

## Run API + UI (laptop)

```bash
uv sync
# Ensure .env exists and is filled out (see table above).

uv run demo-api
# other terminal:
cd web && npm install && npm run dev
```

Open `http://localhost:5173`. The UI polls TWD status and starts scenarios **A / B / C**.

## Scenarios

| Scenario | Workflow | Behavior |
|----------|----------|----------|
| **A** | `PinnedDemo` | **Pinned** versioning. API adds **`PinnedVersioningOverride`** to **current** TWD build so the first task stays on stable **A** during ramp. Long **~90s** sleep then `probe_version`. |
| **B** | `AutoUpgradeDemo` | **Auto-upgrade**. `probe_version` → **150s** sleep → `probe_version`; result like `ok-a -> ok-b` if **B** becomes **Current** mid-run. **Rebuild v-a and v-b from the same workflow code**; only env/build-args differ. |
| **C** | `RollbackWorkflow` | **Auto-upgrade**; id prefix **`rollback-demo-`**. API pins start to TWD **target** (candidate) when Kubernetes + env allow. **v-a** registers gate types; **v-b** omits them → **C** / controller gate stall or time out on **B**. |

**Rollback v-a:** `kubectl apply -f k8s/temporal-worker-deployment.yaml`  
**Roll forward v-b:** `kubectl apply -f k8s/temporal-worker-deployment.v-b.yaml`

**Drain / sunset:** Pinned work stays on its build; auto-upgrade can follow **Current** on later tasks. Controller policy drives scale-down of old versions after drain + `sunset` delays (see controller docs).

## Demo script (commands only)

```bash
# 0) Prep (once): namespace, secret, TemporalConnection, images, TWD (see sections above).

# 1) Steady state on v-a
kubectl apply -f k8s/temporal-worker-deployment.yaml
kubectl get twd,pods -n worker-controller-demo

# 2) Terminal watches (optional)
kubectl get twd -n worker-controller-demo -w
kubectl get deploy,pods -n worker-controller-demo -w   # or two terminals for -w

# 3) API + UI
uv run demo-api
cd web && npm run dev
# Browser: http://localhost:5173. Run **A**, then **B** a few times on v-a.

# 4) Progressive rollout to v-b (gate + Scenario C fail on b; A/B still work)
kubectl apply -f k8s/temporal-worker-deployment.v-b.yaml
# UI: watch ramp; run **C** and expect failure/timeout on target b without gate workers.

# 5) Roll back to v-a
kubectl apply -f k8s/temporal-worker-deployment.yaml

# 6) Snapshots (any time)
kubectl get twd -n worker-controller-demo -o wide
kubectl describe twd worker-controller-demo -n worker-controller-demo
```

**Pre-demo checklist:** controller pods **Running**; CRDs present; secret `temporal-api-key`; `temporalNamespace` in TWD matches Cloud; `.env` matches task queue, `K8S_TWD_NAME`, namespace; cluster can pull or use `IfNotPresent` for `worker-controller-demo:v-a` and `:v-b`.

## Self-hosted Temporal

Point `TemporalConnection.spec.hostPort` at your frontend (e.g. `temporal-frontend.temporal:7233`). Configure TLS/mTLS per [controller configuration](https://github.com/temporalio/temporal-worker-controller/blob/main/docs/configuration.md). Drop `TEMPORAL_API_KEY` from workers if unused.

## References

- [Worker Versioning](https://docs.temporal.io/worker-versioning)
- [Temporal Worker Controller](https://github.com/temporalio/temporal-worker-controller)
