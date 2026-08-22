import { useEffect, useRef, useState } from "react";
import ProgressTheater from "../components/research/ProgressTheater";
import RoundtableTheater from "../components/research/RoundtableTheater";
import PageShell from "../components/layout/PageShell";
import PageTabs from "../components/layout/PageTabs";
import ScrollPane from "../components/layout/ScrollPane";
import { api } from "../api";
import type { ResearchPayload, ResearchProgress } from "../types/research";

type TabId = "overview" | "pipeline" | "roundtable" | "news" | "decisions" | "alpha";

export default function Research() {
  const [data, setData] = useState<ResearchPayload | null>(null);
  const [progress, setProgress] = useState<ResearchProgress | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [newsBusy, setNewsBusy] = useState(false);
  const [tab, setTab] = useState<TabId>("overview");
  const [notifyMap, setNotifyMap] = useState<Record<string, { notified?: boolean; notification_time?: string; channel?: string }>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPoll() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function load() {
    try {
      setData((await api.researchLatest()) as ResearchPayload);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function run() {
    setBusy(true);
    setErr("");
    setProgress({ status: "running", steps: [], pipeline_timing: [] });
    setTab("pipeline");
    stopPoll();
    try {
      const kick = await api.researchRun({});
      if (kick.status === "running") {
        pollRef.current = setInterval(async () => {
          try {
            const p = (await api.researchProgress()) as ResearchProgress;
            setProgress(p);
            if (p.status === "done" && p.result) {
              setData(p.result ?? null);
              stopPoll();
              setBusy(false);
              setTab("overview");
            } else if (p.status === "error") {
              setErr(p.error || "研究失败");
              stopPoll();
              setBusy(false);
            }
          } catch {
            /* keep polling */
          }
        }, 1200);
        return;
      }
      setData(kick as ResearchPayload);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (!pollRef.current) setBusy(false);
    }
  }

  useEffect(() => () => stopPoll(), []);
  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!data?.platform_reports?.length) return;
    api.notifications(80).then((res) => {
      const map: Record<string, { notified?: boolean; notification_time?: string; channel?: string }> = {};
      for (const n of res.notifications || []) {
        if (n.status !== "SENT") continue;
        const key = `${n.symbol}:${n.research_session_id || ""}`;
        map[key] = {
          notified: true,
          notification_time: n.sent_at || n.created_at,
          channel: n.channel,
        };
      }
      setNotifyMap(map);
    }).catch(() => {});
  }, [data?.platform_reports]);

  const rt = data?.roundtable;
  const picks = data?.picks || [];
  const newsN = data?.news_discovery?.n_candidates ?? 0;

  return (
    <PageShell
      title="圆桌研报 · THEATER"
      subtitle={
        data
          ? `${data.as_of || "—"} · ${String(data.strategy || "—")} · 池 ${data.universe_size ?? "—"} · 打分 ${data.scored ?? "—"}`
          : "机器发现 → 验证 → AI 辩论 → Canonical 决策"
      }
      actions={
        <>
          <button className="btn btn-primary" disabled={busy} onClick={run}>
            {busy ? "STRIKE BACK…" : "跑一轮"}
          </button>
          <button className="btn btn-ghost" disabled={busy || newsBusy} onClick={load}>
            刷新
          </button>
          <button className="btn btn-ghost" disabled={busy || newsBusy} onClick={async () => {
            setNewsBusy(true);
            try {
              await api.researchRefreshNews();
              await load();
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e));
            } finally {
              setNewsBusy(false);
            }
          }}>
            {newsBusy ? "新闻…" : "刷新闻"}
          </button>
        </>
      }
      status={err ? <span className="persona-error">{err}</span> : busy ? <span className="status ok">研究运行中…</span> : undefined}
      kpis={[
        {
          label: "状态",
          value: busy ? "RUN" : progress?.status?.toUpperCase() || (data ? "READY" : "—"),
          tone: busy ? "warn" : data ? "ok" : undefined,
        },
        { label: "候选", value: data?.candidate_union?.n_union ?? "—" },
        { label: "Council", value: data?.candidate_union?.n_research ?? "—" },
        { label: "新闻候选", value: newsN },
        { label: "结论", value: picks.length },
        {
          label: "耗时",
          value:
            progress?.elapsed_sec != null
              ? `${Math.floor(progress.elapsed_sec / 60)}m ${Math.round(progress.elapsed_sec % 60)}s`
              : data?.run_log?.elapsed_sec != null
                ? `${Math.floor((data.run_log.elapsed_sec || 0) / 60)}m ${Math.round((data.run_log.elapsed_sec || 0) % 60)}s`
                : "—",
        },
      ]}
    >
      <PageTabs
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        tabs={[
          { id: "overview", label: "速览" },
          { id: "pipeline", label: "流水线", badge: busy ? "…" : undefined },
          { id: "roundtable", label: "圆桌", badge: rt?.roles?.length || undefined },
          { id: "news", label: "新闻", badge: newsN || undefined },
          { id: "decisions", label: "结论", badge: picks.length || undefined },
          { id: "alpha", label: "Alpha" },
        ]}
      />

      <ScrollPane>
        {tab === "overview" && (
          <>
            <div className="dash-grid-2" style={{ minHeight: "340px" }}>
              <ProgressTheater progress={progress} runLog={data?.run_log} compact />
              <RoundtableTheater roundtable={rt} compact />
            </div>
            {picks.length > 0 && (
              <div style={{ marginTop: "0.75rem" }}>
                <h3 className="dash-title" style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>
                  TOP 结论
                </h3>
                <div className="dash-card-grid">
                  {picks.slice(0, 6).map((p) => (
                    <div key={p.symbol} className="pick-card">
                      <div className="pick-card-title">
                        <span className={`badge badge-${p.committee_verdict || "watch"}`}>
                          {(p.committee_verdict || "watch").toUpperCase()}
                        </span>{" "}
                        {p.name || p.symbol}
                      </div>
                      <p className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.3rem" }}>
                        {p.symbol}
                        {p.score != null ? ` · ${p.score.toFixed(3)}` : ""}
                      </p>
                      <p>{p.committee_thesis || p.ai_rationale || p.why || "—"}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!data && !busy && (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                尚无研报。点「跑一轮」开始；运行中可切到「流水线」看实时日志。
              </p>
            )}
          </>
        )}

        {tab === "pipeline" && (
          <ProgressTheater progress={progress} runLog={data?.run_log} compact />
        )}

        {tab === "roundtable" && <RoundtableTheater roundtable={rt} />}

        {tab === "news" && data && (
          <div className="persona-panel compact">
            <h3>News Discovery</h3>
            <p className="persona-muted" style={{ marginTop: 0 }}>
              新闻 {data.news_discovery?.n_news ?? "—"} · 事件 {data.news_discovery?.n_events ?? "—"} · 候选{" "}
              {data.news_discovery?.n_candidates ?? "—"} · 拒绝 {data.news_discovery?.n_rejected ?? "—"}
            </p>
            {(data.news_discovery?.news_candidates || []).length === 0 ? (
              <p className="muted">暂无新闻候选。</p>
            ) : (
              (data.news_discovery?.news_candidates || []).map((c, i) => {
                const risk = (c.price_in_risk || "UNKNOWN").toUpperCase();
                const lc = (c.lifecycle_status || "NEW").toUpperCase();
                return (
                  <div key={`${c.symbol}-${i}`} className="verdict-row">
                    <span className={`badge badge-${risk === "HIGH" ? "pass" : risk === "MEDIUM" ? "watch" : "buy"}`}>
                      {risk}
                    </span>{" "}
                    <span className="badge badge-watch" style={{ marginLeft: "0.25rem" }}>
                      {lc}
                    </span>{" "}
                    <strong>{c.name || c.symbol}</strong>{" "}
                    <span className="muted">{c.symbol}</span>
                    {c.price_in_score != null && (
                      <span className="muted"> · Price-In {(c.price_in_score * 100).toFixed(0)}%</span>
                    )}
                    <p style={{ margin: "0.3rem 0 0", fontSize: "0.9rem" }}>{c.reason || "—"}</p>
                  </div>
                );
              })
            )}
          </div>
        )}

        {tab === "news" && !data && <p className="muted">先跑一轮研究。</p>}

        {tab === "decisions" && data && (
          <>
            <div className="persona-panel compact">
              <h3>标的结论</h3>
              {(data.picks || []).map((p) => (
                <div key={p.symbol} className="verdict-row">
                  <span className={`badge badge-${p.committee_verdict || "watch"}`}>
                    {(p.committee_verdict || "watch").toUpperCase()}
                  </span>{" "}
                  <strong>{p.name || p.symbol}</strong>{" "}
                  <span className="muted">{p.symbol}</span>
                  <p style={{ margin: "0.3rem 0 0" }}>{p.committee_thesis || p.ai_rationale || p.why}</p>
                </div>
              ))}
            </div>
            {(data.platform_reports || []).length > 0 && (
              <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
                <h3>平台研报</h3>
                {(data.platform_reports || []).map((r) => {
                  const nk = `${r.symbol}:${r.research_id || ""}`;
                  const ns = notifyMap[nk];
                  return (
                  <div key={r.research_id || r.symbol} className="verdict-row">
                    <span className={`badge badge-${(r.rating || "WATCH").toLowerCase().includes("buy") ? "buy" : "watch"}`}>
                      {(r.rating || "WATCH").toUpperCase()}
                    </span>{" "}
                    <strong>{r.name || r.symbol}</strong>
                    {ns?.notified ? (
                      <span className="muted"> · 🟢 已通知 {ns.channel} {ns.notification_time?.slice(0, 16)}</span>
                    ) : (
                      <span className="muted"> · ⚪ 未通知</span>
                    )}
                    <p style={{ margin: "0.3rem 0 0" }}>{r.chairman?.base_case || "—"}</p>
                  </div>
                  );
                })}
              </div>
            )}
            <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
              <h3>龙头池（节选）</h3>
              {(data.pool || []).slice(0, 12).map((c) => (
                <div key={c.symbol} className="verdict-row">
                  <strong>{c.name || c.symbol}</strong>{" "}
                  <span className="muted">
                    {c.symbol}
                    {c.board_count ? ` · ${c.board_count}板` : ""}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === "decisions" && !data && <p className="muted">先跑一轮研究。</p>}

        {tab === "alpha" && data?.research_outcomes?.available && (
          <div className="persona-panel compact">
            <h3>Alpha · Cost</h3>
            {(data.research_outcomes.benchmark_snapshot || data.research_outcomes.benchmark?.snapshot) && (
              <p className="persona-muted" style={{ marginTop: 0 }}>
                Benchmark:{" "}
                <strong>
                  {(data.research_outcomes.benchmark_snapshot || data.research_outcomes.benchmark?.snapshot)?.actual ===
                  "csi300"
                    ? "CSI300"
                    : "Equal-weight Universe"}
                </strong>
                {(data.research_outcomes.benchmark_snapshot || data.research_outcomes.benchmark?.snapshot)?.fallback && (
                  <>
                    {" "}
                    (Fallback: CSI300 unavailable)
                  </>
                )}
              </p>
            )}
            {data.ai_cost && (
              <dl className="metrics">
                <div className="metric">
                  <dt>LLM</dt>
                  <dd>{data.ai_cost.n_calls ?? 0}</dd>
                </div>
                <div className="metric">
                  <dt>Tokens</dt>
                  <dd>{data.ai_cost.total_tokens ?? 0}</dd>
                </div>
                <div className="metric">
                  <dt>USD</dt>
                  <dd>${Number(data.ai_cost.estimated_usd ?? 0).toFixed(4)}</dd>
                </div>
              </dl>
            )}
            {data.research_outcomes.portfolio_attribution?.available && (
              <p className="muted" style={{ marginTop: "0.35rem" }}>
                Portfolio α (primary) T+{data.research_outcomes.portfolio_attribution.horizon || data.research_outcomes.horizon}:{" "}
                {data.research_outcomes.portfolio_attribution.mean_selection_alpha != null
                  ? `${(data.research_outcomes.portfolio_attribution.mean_selection_alpha * 100).toFixed(2)}% selection`
                  : data.research_outcomes.portfolio_attribution.mean_market_alpha != null
                    ? `${(data.research_outcomes.portfolio_attribution.mean_market_alpha * 100).toFixed(2)}% market`
                    : "—"}
                {" · fill "}
                {data.research_outcomes.portfolio_attribution.n_paper_fill ?? 0}
                {" / signal "}
                {data.research_outcomes.portfolio_attribution.n_signal_close ?? 0}
              </p>
            )}
            {data.ai_cost?.budget && (
              <p className="muted" style={{ fontSize: "0.82rem" }}>
                Cache hit {(Number(data.ai_cost.budget.used?.cache_hit_rate ?? 0) * 100).toFixed(0)}%
                {data.ai_cost.budget.hard_stop ? " · budget stop" : ""}
              </p>
            )}
            {(data.research_outcomes.ai_incremental_alpha?.available ||
              data.research_outcomes.ai_topk_ablation?.available) && (
              <p className="muted">
                AI Δ (Top-K 同宇宙){" "}
                {(data.research_outcomes.ai_incremental_alpha || data.research_outcomes.ai_topk_ablation)
                  ?.ai_incremental_alpha != null
                  ? `${(
                      ((data.research_outcomes.ai_incremental_alpha || data.research_outcomes.ai_topk_ablation)
                        ?.ai_incremental_alpha ?? 0) * 100
                    ).toFixed(2)}%`
                  : "—"}
                {" · 样本 "}
                {(data.research_outcomes.ai_incremental_alpha || data.research_outcomes.ai_topk_ablation)
                  ?.sample_count ?? "—"}
              </p>
            )}
            {data.research_outcomes.role_ablation?.available && (
              <div style={{ marginTop: "0.5rem" }}>
                <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>Role Ablation (实验)</h4>
                {Object.entries(data.research_outcomes.role_ablation.by_role || {}).map(([role, row]) => (
                  <div key={role} className="muted" style={{ fontSize: "0.82rem" }}>
                    −{role}: Δ{" "}
                    {row.delta_vs_full_council != null
                      ? `${(row.delta_vs_full_council * 100).toFixed(2)}%`
                      : "—"}
                  </div>
                ))}
              </div>
            )}
            {data.research_outcomes.model_benchmark?.available && (
              <div style={{ marginTop: "0.5rem" }}>
                <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>Model × Token</h4>
                {(data.research_outcomes.model_benchmark.models || []).slice(0, 4).map((m) => (
                  <div key={m.model} className="muted" style={{ fontSize: "0.82rem" }}>
                    {m.model}: {m.tokens ?? 0} tok · ${Number(m.cost_usd ?? 0).toFixed(4)}
                  </div>
                ))}
              </div>
            )}
            {(data.research_outcomes.outcomes || []).slice(0, 5).map((o, i) => {
              const h = (o.horizons as Record<string, Record<string, number>> | undefined)?.[
                String(data.research_outcomes?.horizon || 5)
              ];
              if (!h?.actual_return) return null;
              return (
                <div key={i} className="muted" style={{ fontSize: "0.85rem" }}>
                  {o.symbol}: 总收益 {(h.actual_return * 100).toFixed(2)}%
                  {h.market_alpha != null ? ` · Market α ${(h.market_alpha * 100).toFixed(2)}%` : ""}
                  {h.selection_alpha != null ? ` · Selection α ${(h.selection_alpha * 100).toFixed(2)}%` : ""}
                </div>
              );
            })}
          </div>
        )}

        {tab === "alpha" && !data?.research_outcomes?.available && (
          <p className="muted">Alpha 归因需完整跑完一轮研究后才有。</p>
        )}
      </ScrollPane>
    </PageShell>
  );
}
