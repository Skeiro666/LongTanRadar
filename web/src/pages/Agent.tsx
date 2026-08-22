import { useEffect, useState } from "react";
import { api, num, pct } from "../api";
import PageShell from "../components/layout/PageShell";
import PageTabs from "../components/layout/PageTabs";
import ScrollPane from "../components/layout/ScrollPane";

type CostSummary = {
  cycle?: {
    n_calls?: number;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    estimated_usd?: number;
    cache_saved_tokens?: number;
  };
  cycle_cost?: CostSummary["cycle"];
  efficiency?: {
    tokens_per_research?: number | null;
    cost_per_buy?: number | null;
  };
};

type AlphaDash = {
  ai_topk_ablation?: {
    available?: boolean;
    ai_incremental_alpha?: number | null;
    insufficient_sample?: boolean;
    baseline_topk?: { mean_return?: number | null };
    ai_topk?: { mean_return?: number | null };
  };
  discovery_attribution?: {
    sources?: Record<string, { n?: number; mean_return?: number | null; insufficient_sample?: boolean }>;
  };
  cost?: { alpha_per_100k_tokens?: number | null };
};

type LogRow = { ts?: string; message?: string; phase?: string };
type AgentState = {
  running?: boolean;
  cycle?: number;
  phase?: string;
  last_error?: string;
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
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [alpha, setAlpha] = useState<AlphaDash | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("control");

  async function refresh() {
    try {
      setSt(await api.agent());
      try {
        setCost(await api.aiCost());
      } catch {
        setCost(null);
      }
      try {
        setAlpha(await api.researchAlphaDashboard());
      } catch {
        setAlpha(null);
      }
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

  useEffect(() => {
    if (st?.running) setTab("logs");
  }, [st?.running]);

  async function start() {
    setBusy(true);
    try {
      setSt(await api.agentStart({ run_now: true }));
      setTab("logs");
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
  const cycle = cost?.cycle_cost || cost?.cycle;
  const eff = cost?.efficiency;
  const topk = alpha?.ai_topk_ablation;

  return (
    <PageShell
      title="研究循环 · AGENT"
      subtitle={`${st?.ai_model || "—"} · 阶段 ${st?.phase || "idle"} · 轮次 ${st?.cycle ?? 0}`}
      actions={
        <>
          <button className="btn btn-primary" disabled={busy || st?.running} onClick={start}>
            {busy ? "…" : "启动"}
          </button>
          <button className="btn btn-ink-outline" disabled={busy || !st?.running} onClick={stop}>
            急停
          </button>
          <button className="btn btn-ink" disabled={busy} onClick={resetAll}>
            重置
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={refresh}>
            刷新
          </button>
        </>
      }
      status={
        <>
          {err && <span className="status error">{err}</span>}
          {st?.last_error && <span className="status error"> · 上轮 {st.last_error}</span>}
          {st?.running && <span className="status ok"> · 运行中</span>}
        </>
      }
      kpis={[
        {
          label: "状态",
          value: st?.running ? "RUN" : "STOP",
          tone: st?.running ? ("warn" as const) : undefined,
        },
        {
          label: "权益",
          value: st?.last_result?.metrics?.equity != null ? st.last_result.metrics.equity.toFixed(0) : "—",
        },
        {
          label: "相对本金",
          value: ret != null ? `${(ret * 100).toFixed(2)}%` : "—",
          tone: ret != null && ret > 0 ? "up" : ret != null && ret < 0 ? "down" : undefined,
        },
        { label: "LLM 调用", value: cycle?.n_calls ?? 0 },
        { label: "Tokens", value: cycle?.total_tokens ?? 0 },
        { label: "USD", value: `$${num(cycle?.estimated_usd, 4)}` },
      ]}
    >
      <PageTabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "control", label: "控制台" },
          { id: "cost", label: "成本/Alpha" },
          { id: "logs", label: "日志", badge: st?.logs?.length || undefined },
        ]}
      />

      <ScrollPane>
        {tab === "control" && (
          <div className="dash-grid-2">
            <div className="panel compact">
              <h3>循环说明</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                龙头/事件池 → 因子 → AI 圆桌 → 仅 buy 下单 → 评估 → 调权重。实盘不会自动开。
              </p>
              {st?.last_result?.roundtable?.summary && (
                <>
                  <h3 style={{ marginTop: "1rem" }}>圆桌摘要</h3>
                  <p>{st.last_result.roundtable.summary}</p>
                </>
              )}
              {st?.last_result?.proposal?.rationale && (
                <>
                  <h3 style={{ marginTop: "1rem" }}>参数层</h3>
                  <p>{st.last_result.proposal.rationale}</p>
                  <p className="muted" style={{ fontSize: "0.85rem" }}>
                    {st.last_result.proposal.source || ""}
                  </p>
                </>
              )}
            </div>
            <div className="panel compact">
              <h3>Council</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                Canonical Decision 驱动纸面交易 · 圆桌仅 benchmark
              </p>
              {!st?.last_result?.roundtable?.summary && !st?.last_result?.proposal?.rationale && (
                <p className="muted">启动后首轮约 1–3 分钟，日志 Tab 可看进度。</p>
              )}
            </div>
          </div>
        )}

        {tab === "cost" && cost && (
          <>
            <dl className="metrics">
              <div className="metric">
                <dt>Input</dt>
                <dd>{cycle?.input_tokens ?? cycle?.total_tokens ?? 0}</dd>
              </div>
              <div className="metric">
                <dt>Output</dt>
                <dd>{cycle?.output_tokens ?? 0}</dd>
              </div>
              <div className="metric">
                <dt>Cache 节省</dt>
                <dd>{cycle?.cache_saved_tokens ?? 0}</dd>
              </div>
              <div className="metric">
                <dt>Tokens/Research</dt>
                <dd>{eff?.tokens_per_research != null ? num(eff.tokens_per_research, 0) : "—"}</dd>
              </div>
              <div className="metric">
                <dt>Cost/BUY</dt>
                <dd>{eff?.cost_per_buy != null ? `$${num(eff.cost_per_buy, 4)}` : "—"}</dd>
              </div>
            </dl>
            {topk?.available && (
              <div className="panel compact">
                <h3>AI Incremental Alpha</h3>
                <p style={{ margin: 0 }}>
                  {topk.insufficient_sample
                    ? "样本不足"
                    : topk.ai_incremental_alpha != null
                      ? pct(topk.ai_incremental_alpha)
                      : "—"}
                  {" · Baseline "}
                  {topk.baseline_topk?.mean_return != null ? pct(topk.baseline_topk.mean_return) : "—"}
                  {" · AI "}
                  {topk.ai_topk?.mean_return != null ? pct(topk.ai_topk.mean_return) : "—"}
                </p>
              </div>
            )}
            {alpha?.discovery_attribution?.sources && (
              <div className="panel compact" style={{ marginTop: "0.75rem" }}>
                <h3>Discovery Alpha</h3>
                {Object.entries(alpha.discovery_attribution.sources).map(([k, v]) => (
                  <div key={k} className="muted" style={{ fontSize: "0.85rem" }}>
                    {k}：n={v.n ?? 0}
                    {v.mean_return != null ? ` · ${pct(v.mean_return)}` : ""}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === "cost" && !cost && <p className="muted">暂无成本数据。</p>}

        {tab === "logs" && (
          <div className="persona-panel compact flush">
            <h3>运行日志</h3>
            {(st?.logs || []).length === 0 ? (
              <p className="persona-muted">还没有日志。点启动后开始写入。</p>
            ) : (
              <div className="persona-log" style={{ minHeight: "320px" }}>
                {[...(st?.logs || [])].reverse().map((row, i) => (
                  <div key={i} className="persona-log-line">
                    <span className="ts">{row.ts ? row.ts.slice(11, 19) : ""}</span>
                    <span className="phase">[{row.phase || "—"}]</span>
                    <span className="msg">{row.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </ScrollPane>
    </PageShell>
  );
}
