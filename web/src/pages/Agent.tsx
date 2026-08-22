import { useEffect, useState } from "react";
import { api } from "../api";

type LogRow = { ts?: string; message?: string; phase?: string };
type AgentState = {
  running?: boolean;
  cycle?: number;
  phase?: string;
  last_error?: string;
  interval_sec?: number;
  started_at?: string;
  logs?: LogRow[];
  last_result?: {
    proposal?: { rationale?: string; source?: string };
    metrics?: { equity?: number; paper_return?: number };
    roundtable?: { summary?: string };
  };
  ai_model?: string;
};

export default function Agent() {
  const [st, setSt] = useState<AgentState | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setSt(await api.agent());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  async function start() {
    setBusy(true);
    try {
      setSt(await api.agentStart({ run_now: true }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      setSt(await api.agentStop());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resetAll() {
    if (!window.confirm("确认清空模拟账户与盈亏曲线？本金将恢复为 3000，并重新开一轮研究。")) return;
    setBusy(true);
    try {
      setSt(await api.agentReset());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const ret = st?.last_result?.metrics?.paper_return;
  return (
    <section className="section">
      <h2>研究循环</h2>
      <p className="lead">
        模拟盘循环：龙头/事件池 → 因子打分 → AI 圆桌研报 → 仅 buy 才下单 → 评估 → 调整因子权重。实盘不会自动开。
      </p>
      <p className="muted">
        模型 {st?.ai_model || "—"} · 阶段 {st?.phase || "idle"} · 轮次 {st?.cycle ?? 0}
        {st?.running ? " · 运行中" : " · 已停止"}
      </p>

      <div className="cta-row">
        <button className="btn btn-primary" disabled={busy || st?.running} onClick={start}>
          {busy ? "…" : "启动研究循环"}
        </button>
        <button className="btn btn-ink-outline" disabled={busy || !st?.running} onClick={stop}>
          急停
        </button>
        <button className="btn btn-ink" disabled={busy} onClick={resetAll}>
          清空重置
        </button>
        <button className="btn btn-ink" disabled={busy} onClick={refresh}>
          刷新状态
        </button>
      </div>

      {err && <p className="status error">{err}</p>}
      {st?.last_error && <p className="status error">上一轮：{st.last_error}</p>}

      <dl className="metrics" style={{ marginTop: "1.25rem" }}>
        <div className="metric">
          <dt>模拟权益</dt>
          <dd>{st?.last_result?.metrics?.equity != null ? st.last_result.metrics.equity.toFixed(0) : "—"}</dd>
        </div>
        <div className="metric">
          <dt>相对本金</dt>
          <dd>{ret != null ? `${(ret * 100).toFixed(2)}%` : "—"}</dd>
        </div>
        <div className="metric">
          <dt>方向</dt>
          <dd>龙头/事件</dd>
        </div>
      </dl>

      {(st?.last_result?.roundtable?.summary || st?.last_result?.proposal?.rationale) && (
        <div className="panel">
          <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>本轮说明</h3>
          {st?.last_result?.roundtable?.summary && <p>{st.last_result.roundtable.summary}</p>}
          {st?.last_result?.proposal?.rationale && <p>{st.last_result.proposal.rationale}</p>}
          <p className="muted">来源：{st.last_result.proposal?.source || "—"}</p>
        </div>
      )}

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>运行日志</h3>
        {(st?.logs || []).length === 0 ? (
          <p className="muted">还没有日志。点启动后，首轮拉涨停/业绩池可能要 1–3 分钟。</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "0.9rem" }}>
            {[...(st?.logs || [])].reverse().map((row, i) => (
              <li key={i} style={{ borderBottom: "1px solid var(--line)", padding: "0.45rem 0" }}>
                <span className="muted">{row.phase || ""}</span> {row.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
