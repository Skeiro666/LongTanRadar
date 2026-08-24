import { useEffect, useRef, useState } from "react";
import CandidateCardView from "../components/research/CandidateCardView";
import NewsQuantMatrix from "../components/research/NewsQuantMatrix";
import ProgressTheater from "../components/research/ProgressTheater";
import PageShell from "../components/layout/PageShell";
import PageTabs from "../components/layout/PageTabs";
import ScrollPane from "../components/layout/ScrollPane";
import { api } from "../api";
import type { ResearchPayload, ResearchProgress } from "../types/research";
import type { CandidateCard, ResearchTerminal } from "../types/terminal";

type TabId = "terminal" | "pipeline";

export default function Research() {
  const [data, setData] = useState<ResearchPayload | null>(null);
  const [terminal, setTerminal] = useState<ResearchTerminal | null>(null);
  const [progress, setProgress] = useState<ResearchProgress | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [newsBusy, setNewsBusy] = useState(false);
  const [tab, setTab] = useState<TabId>("terminal");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPoll() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function load() {
    try {
      const [latest, term] = await Promise.all([api.researchLatest(), api.researchTerminal()]);
      setData(latest as ResearchPayload);
      setTerminal(term as ResearchTerminal);
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
              setTab("terminal");
              await load();
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
      await load();
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

  const ratings = terminal?.counts?.ratings || {};
  const buyN = (ratings.BUY || 0) + (ratings.STRONG_BUY || 0);
  const watchN = ratings.WATCH || 0;
  const passN = ratings.PASS || 0;
  const candidates = terminal?.candidates || [];

  return (
    <PageShell
      title="Research Terminal"
      subtitle={
        terminal
          ? `${terminal.as_of || "—"} · 更新 ${String(terminal.generated_at || "").slice(0, 16)} · 新闻覆盖 ${terminal.data_completeness?.news_coverage || "—"} (${terminal.data_completeness?.pct ?? "—"}%)`
          : "Signal First · 结论 → 原因 → 证据"
      }
      actions={
        <>
          <button className="btn btn-primary" disabled={busy} onClick={run}>
            {busy ? "运行中…" : "跑一轮"}
          </button>
          <button className="btn btn-ghost" disabled={busy || newsBusy} onClick={load}>
            刷新
          </button>
          <button
            className="btn btn-ghost"
            disabled={busy || newsBusy}
            onClick={async () => {
              setNewsBusy(true);
              try {
                await api.researchRefreshNews();
                await load();
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              } finally {
                setNewsBusy(false);
              }
            }}
          >
            {newsBusy ? "新闻…" : "刷新闻"}
          </button>
        </>
      }
      status={err ? <span className="persona-error">{err}</span> : busy ? <span className="status ok">Research Cycle 运行中…</span> : undefined}
      kpis={[
        { label: "候选", value: terminal?.counts?.candidates ?? "—" },
        { label: "BUY", value: buyN, tone: buyN ? "ok" : undefined },
        { label: "WATCH", value: watchN },
        { label: "PASS", value: passN },
        { label: "News Discovery", value: terminal?.counts?.news_discovery ?? "—" },
        {
          label: "Cycle",
          value: busy ? "RUN" : progress?.status?.toUpperCase() || (data ? "READY" : "—"),
          tone: busy ? "warn" : undefined,
        },
      ]}
    >
      <PageTabs
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        tabs={[
          { id: "terminal", label: "Research", badge: candidates.length || undefined },
          { id: "pipeline", label: "Pipeline", badge: busy ? "…" : undefined },
        ]}
      />

      <ScrollPane>
        {tab === "pipeline" && (
          <ProgressTheater progress={progress} runLog={data?.run_log} compact={false} />
        )}

        {tab === "terminal" && (
          <>
            {terminal?.news_discovery_status?.degraded && (
              <div className="degraded-banner">
                News DEGRADED — {String(terminal.news_discovery_status.provider_status || "provider issue")}
              </div>
            )}

            <div className="persona-panel compact">
              <h3>News × Quant Matrix</h3>
              <NewsQuantMatrix matrix={terminal?.matrix} candidates={candidates} />
            </div>

            <div className="candidate-list">
              {candidates.length === 0 ? (
                <p className="muted">尚无候选。点「跑一轮」开始 Research Cycle。</p>
              ) : (
                candidates.map((c: CandidateCard) => (
                  <CandidateCardView
                    key={c.symbol}
                    card={c}
                    expanded={!!expanded[c.symbol || ""]}
                    onToggle={() =>
                      setExpanded((m) => ({ ...m, [c.symbol || ""]: !m[c.symbol || ""] }))
                    }
                  />
                ))
              )}
            </div>
          </>
        )}
      </ScrollPane>
    </PageShell>
  );
}
