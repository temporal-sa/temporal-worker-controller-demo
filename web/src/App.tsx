import { useCallback, useEffect, useState } from "react";
import "./App.css";

type DeployStatus = {
  phase: string;
  summary: string;
  rolloutComplete: boolean;
  status?: Record<string, unknown>;
};

function TemporalLogo() {
  return (
    <img
      src="/temporal-symbol-light.png"
      alt=""
      className="temporal-logo"
      width={40}
      height={40}
      decoding="async"
    />
  );
}

async function fetchStatus(): Promise<DeployStatus> {
  const r = await fetch("/api/deployment/status");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<DeployStatus>;
}

/** URL segment must stay a/b/c so older demo-api builds still work; current API maps to pinned/auto/rollback. */
type ScenarioKey = "a" | "b" | "c";

async function runScenario(key: ScenarioKey) {
  const r = await fetch(`/api/scenarios/${key}`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ workflow_id: string; workflow_type: string }>;
}

/** Visual rollout fill (0–100). Not identical to Temporal ramp % early in the pipeline. */
function rolloutBarFromStatus(
  status: DeployStatus,
  rampDisplay: number | null,
  progressingReason: string,
): { pct: number; caption: string } {
  if (status.rolloutComplete && status.phase === "steady") {
    return { pct: 100, caption: "Rollout complete" };
  }
  if (status.phase === "error") {
    return { pct: 0, caption: "Rollout blocked" };
  }
  if (status.phase === "ramping") {
    if (rampDisplay !== null && !Number.isNaN(rampDisplay)) {
      const pct = Math.min(99, Math.max(5, rampDisplay));
      return { pct, caption: `Traffic ramp ${rampDisplay}% → target` };
    }
    return { pct: 50, caption: "Ramping" };
  }
  if (status.phase === "waiting_promotion") {
    return { pct: 24, caption: "Rollback workflow / registering version" };
  }
  if (status.phase === "waiting_pollers") {
    return { pct: 10, caption: "Waiting for workers to poll" };
  }
  if (progressingReason === "Ramping" && rampDisplay !== null) {
    const pct = Math.min(99, Math.max(5, rampDisplay));
    return { pct, caption: `Traffic ramp ${rampDisplay}% → target` };
  }
  if (progressingReason === "WaitingForPromotion") {
    return { pct: 24, caption: "Rollback workflow / registering version" };
  }
  if (progressingReason === "WaitingForPollers") {
    return { pct: 10, caption: "Waiting for workers to poll" };
  }
  return { pct: 12, caption: "Rollout in progress" };
}

export default function App() {
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<ScenarioKey | null>(null);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const s = await fetchStatus();
      setStatus(s);
      setStatusErr(null);
    } catch (e) {
      setStatusErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const rolloutIdle =
    status != null &&
    status.rolloutComplete === true &&
    status.phase === "steady";
  const pollMs = rolloutIdle ? 5000 : 900;

  useEffect(() => {
    void poll();
    const t = setInterval(() => void poll(), pollMs);
    return () => clearInterval(t);
  }, [poll, pollMs]);

  const onScenario = async (key: ScenarioKey) => {
    setBusy(key);
    setRunErr(null);
    setLastRun(null);
    try {
      const out = await runScenario(key);
      setLastRun(`${out.workflow_type} → ${out.workflow_id}`);
    } catch (e) {
      setRunErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const target = status?.status?.targetVersion as
    | Record<string, unknown>
    | undefined;
  const current = status?.status?.currentVersion as
    | Record<string, unknown>
    | undefined;
  const tq =
    target && typeof target === "object" && Array.isArray(target.taskQueues)
      ? (target.taskQueues as { name?: string }[])[0]?.name
      : undefined;

  const conditions = (status?.status?.conditions ?? []) as {
    type?: string;
    status?: string;
    reason?: string;
  }[];
  const formatCond = (t: string) => {
    const c = conditions.find((x) => x.type === t);
    if (!c) return null;
    const st = c.status ?? "?";
    const r = c.reason ? ` (${c.reason})` : "";
    return `${t}=${st}${r}`;
  };
  const progressingCond = formatCond("Progressing");
  const readyCond = formatCond("Ready");

  const rampRaw = target?.rampPercentage;
  const rampPct =
    typeof rampRaw === "number"
      ? rampRaw
      : typeof rampRaw === "string" && rampRaw !== ""
        ? Number(rampRaw)
        : undefined;
  const rampDisplay =
    rampPct !== undefined && !Number.isNaN(rampPct) ? rampPct : null;

  const progressingReason =
    conditions.find((x) => x.type === "Progressing")?.reason ?? "";

  const bar =
    status != null
      ? rolloutBarFromStatus(status, rampDisplay, progressingReason)
      : { pct: 0, caption: "" };

  return (
    <div className="app">
      <header className="header">
        <TemporalLogo />
        <div>
          <h1>Temporal Worker Controller demo</h1>
          <p className="sub">
            Try three rollout stories below and watch live status from your
            cluster.{" "}
            <a href="https://docs.temporal.io/worker-versioning">
              How worker versioning works
            </a>
            .
          </p>
        </div>
      </header>

      <section className="status-panel">
        <h2>Rollout status</h2>
        {statusErr ? (
          <p className="summary error">
            Couldn’t load status (check the API is running and can reach your
            cluster): {statusErr}
          </p>
        ) : status ? (
          <>
            <div className="phase">{status.phase.replace(/_/g, " ")}</div>
            <p className="summary">{status.summary}</p>
            <span
              className={`badge ${status.rolloutComplete ? "complete" : status.phase === "error" ? "err" : "progress"}`}
            >
              {status.rolloutComplete
                ? "Steady state"
                : status.phase === "error"
                  ? "Check cluster"
                  : "Rollout in progress"}
            </span>
            {!status.rolloutComplete && (
              <div
                className={`rollout-bar-wrap ${status.phase === "error" ? "rollout-bar-wrap--err" : ""}`}
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(bar.pct)}
                aria-label="Rollout progress"
              >
                <div className="rollout-bar-label">
                  <span>Rollout progress</span>
                  <span>{Math.round(bar.pct)}%</span>
                </div>
                <div className="rollout-bar-track">
                  <div
                    className="rollout-bar-fill"
                    style={{ width: `${bar.pct}%` }}
                  />
                </div>
                <p className="rollout-bar-caption">{bar.caption}</p>
              </div>
            )}
            <div className="meta">
              {current && typeof current.buildID === "string" && (
                <div>Current build: {current.buildID}</div>
              )}
              {target && typeof target.buildID === "string" && (
                <div>Target build: {target.buildID}</div>
              )}
              {progressingCond && (
                <div className="cond">{progressingCond}</div>
              )}
              {readyCond && <div className="cond">{readyCond}</div>}
              {typeof target?.status === "string" && (
                <div>Target version status: {target.status}</div>
              )}
              {rampDisplay !== null && <div>Ramp %: {rampDisplay}</div>}
              {tq && <div>Task queue (target): {tq}</div>}
              {!status.rolloutComplete && (
                <p className="hint">
                  Updates about once a second while a rollout is active. When
                  things finish, the “current” and “target” lines may both show
                  the new version. That is normal.
                </p>
              )}
            </div>
          </>
        ) : (
          <p className="summary">Loading status…</p>
        )}
      </section>

      <div className="grid">
        <article className="card">
          <span className="tag">Scenario A</span>
          <h3>Pinned Workflow</h3>
          <p>
            Starts a long-running job (~90 seconds) that keeps using the same app
            version until it finishes, even if you deploy a newer one mid-flight.
            Use this when an upgrade is not backward compatible and the run must
            stay on the code that started it.
          </p>
          <p className="rw">
            <strong>Use Case:</strong> regulated flows, long jobs, or any case
            where the same code version must see the run through.
          </p>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => onScenario("a")}
          >
            {busy === "a" ? "Starting…" : "Run scenario A"}
          </button>
        </article>

        <article className="card">
          <span className="tag">Scenario B</span>
          <h3>Auto Upgrade Workflow</h3>
          <p>
            Probes the worker version, waits 2 minutes 30 seconds, then probes again.
            Finish promoting the new build to Current during the wait to often
            see <code>ok-a -&gt; ok-b</code> in the result, Web UI, or pod logs.
            Rebuild both v-a and v-b images from the same code when you change
            workflows.
          </p>
          <p className="rw">
            <strong>Use Case:</strong> short, compatible workflows and feature
            flags where it’s
            safe for work to land on the newest deployment.
          </p>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => onScenario("b")}
          >
            {busy === "b" ? "Starting…" : "Run scenario B"}
          </button>
        </article>

        <article className="card">
          <span className="tag">Scenario C</span>
          <h3>Rollback workflow</h3>
          <p>
            Starts <code>RollbackWorkflow</code> with auto-upgrade versioning
            (type in <code>spec.rollout.gate</code>). It fails on version B when
            that type is not registered on B workers. The demo shows rolling back
            to version A. Workflow ids use the prefix <code>rollback-demo-</code>.
          </p>
          <p className="rw">
            <strong>Use Case:</strong> a small test workflow on the candidate
            version before you send real traffic.
          </p>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => onScenario("c")}
          >
            {busy === "c" ? "Starting…" : "Run scenario C"}
          </button>
        </article>
      </div>

      {lastRun && <p className="result">Started: {lastRun}</p>}
      {runErr && <p className="result error">{runErr}</p>}
    </div>
  );
}
