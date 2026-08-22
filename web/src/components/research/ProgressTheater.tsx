import type { ResearchProgress } from "../../types/research";

function fmtSec(s?: number | null) {
  if (s == null || Number.isNaN(s)) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function fmtTs(iso?: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

type Props = {
  progress: ResearchProgress | null;
  runLog?: ResearchProgress["run_log"];
  compact?: boolean;
};

export default function ProgressTheater({ progress, runLog, compact = false }: Props) {
  const timing = progress?.pipeline_timing || runLog?.pipeline_timing || [];
  const steps = progress?.steps || runLog?.steps || [];
  const status = progress?.status || (runLog ? "done" : "idle");
  const elapsed = progress?.elapsed_sec ?? runLog?.elapsed_sec;

  if (status === "idle" && !runLog) {
    return (
      <div className="persona-panel compact">
        <h3>流水线</h3>
        <p className="persona-muted">尚未运行。点「跑一轮研究」后此处显示各阶段耗时与详细日志。</p>
      </div>
    );
  }

  return (
    <div className={`persona-panel${compact ? " compact flush" : ""}`}>
      <div className="persona-panel-body">
        {!compact ? <h3>研究流水线 · RUN LOG</h3> : <h3>流水线</h3>}
        <div className="kpi-strip" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
          <div className="kpi-card">
            <div className="kpi-label">状态</div>
            <div className="kpi-value">{status === "running" ? "RUNNING" : status.toUpperCase()}</div>
          </div>
          {elapsed != null && (
            <div className="kpi-card">
              <div className="kpi-label">已用</div>
              <div className="kpi-value">{fmtSec(elapsed)}</div>
            </div>
          )}
          {progress?.current_phase && status === "running" && (
            <div className="kpi-card kpi-warn">
              <div className="kpi-label">阶段</div>
              <div className="kpi-value" style={{ fontSize: "1rem" }}>
                {progress.current_phase.toUpperCase()}
              </div>
            </div>
          )}
        </div>

        <div className="phase-rail">
          {timing.map((row) => (
            <span
              key={row.phase}
              className={`phase-chip${row.status === "running" ? " running" : row.status === "done" ? " done" : row.status === "error" ? " error" : ""}`}
              title={`${row.label} · ${row.typical}`}
            >
              {row.label}
              {row.duration_sec != null ? ` ${fmtSec(row.duration_sec)}` : row.status === "running" ? " …" : ""}
            </span>
          ))}
        </div>

        <div className={compact ? "dash-split" : ""} style={{ flex: compact ? 1 : undefined, minHeight: compact ? 0 : undefined }}>
          <div className={compact ? "dash-split-col" : undefined}>
            <table className="persona-timing-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>典型</th>
                <th>实际</th>
                {!compact && <th>说明</th>}
              </tr>
            </thead>
            <tbody>
              {timing.map((row) => (
                <tr
                  key={row.phase}
                  className={
                    row.status === "running"
                      ? "is-running"
                      : row.status === "done"
                        ? "is-done"
                        : row.status === "error"
                          ? "is-error"
                          : ""
                  }
                >
                  <td>{row.label}</td>
                  <td className="persona-muted">{row.typical}</td>
                  <td>{row.duration_sec != null ? fmtSec(row.duration_sec) : row.status === "running" ? "…" : "—"}</td>
                  {!compact && (
                    <td className="persona-muted">
                      {row.note}
                      {row.error ? ` · ${row.error}` : ""}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className={compact ? "dash-split-col" : undefined} style={compact ? undefined : { marginTop: "0.75rem" }}>
          <div className="persona-muted" style={{ marginBottom: "0.35rem" }}>
            详细日志（{steps.length}）
          </div>
          <div className="persona-log">
            {steps.length === 0 ? (
              <div className="persona-muted">等待日志…</div>
            ) : (
              steps.map((s, i) => (
                <div
                  key={`${s.ts}-${i}`}
                  className={`persona-log-line ${s.level === "warn" ? "warn" : s.level === "error" ? "error" : ""}`}
                >
                  <span className="ts">{fmtTs(s.ts)}</span>
                  <span className="phase">[{s.phase}]</span>
                  <span className="msg">{s.message || s.label || ""}</span>
                  {s.duration_sec != null && <span className="persona-muted">{fmtSec(s.duration_sec)}</span>}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
