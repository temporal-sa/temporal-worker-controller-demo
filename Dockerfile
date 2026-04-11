# Build per version, e.g.:
#   docker build -t worker-controller-demo:v-a --build-arg DEMO_WORKER_VERSION=a .
# v-b: omit RollbackWorkflow (Scenario C + controller rollback check fail on b; A/B work) — demo rollback story
#   docker build -t worker-controller-demo:v-b --build-arg DEMO_WORKER_VERSION=b \
#     --build-arg DEMO_OMIT_ROLLOUT_GATE=1 .
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml README.md uv.lock ./
COPY activity ./activity
COPY workflows ./workflows
COPY worker ./worker
COPY api ./api
RUN uv sync --frozen --no-dev
ARG DEMO_WORKER_VERSION=a
ENV DEMO_WORKER_VERSION=${DEMO_WORKER_VERSION}
ARG DEMO_OMIT_ROLLOUT_GATE=
ENV DEMO_OMIT_ROLLOUT_GATE=${DEMO_OMIT_ROLLOUT_GATE}
EXPOSE 8080
CMD ["uv", "run", "python", "worker/main.py"]
