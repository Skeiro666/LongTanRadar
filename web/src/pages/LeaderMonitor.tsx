import { useEffect, useState } from "react";
import { api, num } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type LeaderRow = {
  symbol: string;
  name?: string;
  lifecycle?: string;
  board_count?: number;
  leader_score?: number;
  stage?: string;
  chase_score?: number;
  chase_level?: string;
  trade_timing_score?: number;
  trade_timing_action?: string;
  news_score?: number;
  risk_status?: string;
  risk_flags?: string[];
  status_reason?: string;
  in_focus_watchlist?: boolean;
  merged_from_focus?: boolean;
};

type LeaderMonitorPayload = {
  enabled?: boolean;
  research_only?: boolean;
  positioning?: string;
  message?: string;
  has_buy_ready?: boolean;
  buy_ready_count?: number;
  focus_count?: number;
  as_of?: string;
  buckets?: Record<string, LeaderRow[]>;
  stage_performance?: Record<string, { n?: number; mean_timing?: number | null }>;
  board_performance?: Record<string, { n?: number; mean_leader?: number | null }>;
  focus_stats?: Record<string, number>;
};

const BUCKET_ORDER = ["BUY_READY", "BUY_CANDIDATE", "FOCUS", "WAIT", "DROPPED", "OTHER"] as const;
const BUCKET_LABEL: Record<string, string> = {
  BUY_READY: "可买入",
  BUY_CANDIDATE: "买点候选",
  FOCUS: "重点跟踪",
  WAIT: "等待",
  DROPPED: "已踢出",
  OTHER: "其他",
};

function RowTable({ rows, highlight }: { rows: LeaderRow[]; highlight?: boolean }) {
  if (!rows.length) return <p className="muted">暂无</p>;
  return (
    <table className="data-table compact">
      <thead>
        <tr>
          <th>代码</th>
          <th>名称</th>
          <th>连板</th>
          <th>Leader</th>
          <th>Stage</th>
          <th>Chase</th>
          <th>Timing</th>
          <th>News</th>
          <th>风控</th>
          <th>状态说明</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.symbol} className={highlight ? "row-buy-ready" : undefined}>
            <td>{r.symbol}</td>
            <td>{r.name || "—"}</td>
            <td>{r.board_count ?? "—"}</td>
            <td>{num(r.leader_score, 3)}</td>
            <td>{r.stage || "—"}</td>
            <td>
              {num(r.chase_score, 2)} {r.chase_level ? `(${r.chase_level})` : ""}
            </td>
            <td>
              {r.trade_timing_action || "—"} / {num(r.trade_timing_score, 2)}
            </td>
            <td>{num(r.news_score, 2)}</td>
            <td>{r.risk_status || "—"}</td>
            <td className="muted small">{r.status_reason || (r.merged_from_focus ? "Focus 持续跟踪" : "—")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function LeaderMonitor() {
  const [data, setData] = useState<LeaderMonitorPayload | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const pack = await api.leaderMonitor();
      setData(pack);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const buckets = data?.buckets || {};

  return (
    <PageShell title="龙头监控" subtitle={data?.positioning || "涨停龙头研究与交易时机"}>
      {err && <div className="banner error">{err}</div>}
      <div className="card-grid">
        <div className={`card ${data?.has_buy_ready ? "card-ok" : "card-warn"}`}>
          <h3>买点状态</h3>
          <p className="lead">{data?.message || "加载中…"}</p>
          <p className="muted small">
            BUY_READY {data?.buy_ready_count ?? 0} · Focus {data?.focus_count ?? 0}
            {data?.research_only ? " · 研究模式" : ""}
          </p>
        </div>
        <div className="card">
          <h3>Focus 统计</h3>
          <ul className="kv-list">
            {Object.entries(data?.focus_stats || {}).map(([k, v]) => (
              <li key={k}>
                <span>{k}</span>
                <span>{v}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <ScrollPane>
        {BUCKET_ORDER.map((key) => {
          const rows = buckets[key] || [];
          if (key === "OTHER" && !rows.length) return null;
          return (
            <section key={key} className="section-block">
              <h2>
                {BUCKET_LABEL[key] || key}
                <span className="badge">{rows.length}</span>
              </h2>
              <RowTable rows={rows} highlight={key === "BUY_READY"} />
            </section>
          );
        })}

        <section className="section-block">
          <h2>Stage 表现（研究样本）</h2>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Stage</th>
                <th>样本</th>
                <th>平均 Timing</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data?.stage_performance || {}).map(([st, v]) => (
                <tr key={st}>
                  <td>{st}</td>
                  <td>{v.n ?? 0}</td>
                  <td>{num(v.mean_timing ?? undefined, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="section-block">
          <h2>板数分布</h2>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>板数</th>
                <th>样本</th>
                <th>平均 Leader</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data?.board_performance || {}).map(([b, v]) => (
                <tr key={b}>
                  <td>{b}</td>
                  <td>{v.n ?? 0}</td>
                  <td>{num(v.mean_leader ?? undefined, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </ScrollPane>
    </PageShell>
  );
}
