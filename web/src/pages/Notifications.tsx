import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type HistoryRow = {
  notification_id?: string;
  symbol?: string;
  name?: string;
  level?: string;
  channel?: string;
  status?: string;
  sent_at?: string;
  created_at?: string;
  research_snapshot_id?: string;
  outcome_status?: string;
  horizons?: Record<string, { available?: boolean; excess_return?: number; return?: number }>;
  metadata?: Record<string, unknown>;
};

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export default function Notifications() {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const [hist, st] = await Promise.all([api.notificationHistory(100), api.notificationStats()]);
      setRows((hist.notifications || []) as HistoryRow[]);
      setStats(st);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <PageShell title="通知中心" subtitle="历史通知 + Outcome 复盘 — 以前的通知准不准？">
      <ScrollPane>
        {err && <p className="error">{err}</p>}

        {stats && (
          <div className="persona-panel compact">
            <h3>概览</h3>
            <dl className="metrics">
              <div className="metric"><dt>今日</dt><dd>{String(stats.today_count ?? 0)}</dd></div>
              <div className="metric"><dt>7日</dt><dd>{String(stats.days_7_count ?? 0)}</dd></div>
              <div className="metric"><dt>BUY</dt><dd>{String(stats.BUY_count ?? 0)}</dd></div>
              <div className="metric"><dt>STRONG_BUY</dt><dd>{String(stats.STRONG_BUY_count ?? 0)}</dd></div>
            </dl>
          </div>
        )}

        <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
          <h3>Notification History</h3>
          {rows.length === 0 ? (
            <p className="muted">暂无通知。Precision &gt; Recall。</p>
          ) : (
            rows.map((r) => {
              const rid = r.research_snapshot_id;
              const hz = r.horizons || {};
              return (
                <div key={r.notification_id || `${r.symbol}-${r.created_at}`} className="verdict-row">
                  <span className={`badge badge-${r.status === "SENT" ? "buy" : "watch"}`}>{r.status}</span>{" "}
                  <span className="badge badge-watch">{r.level}</span>{" "}
                  <strong>{r.name || r.symbol}</strong>{" "}
                  <span className="muted">{r.symbol} · {r.sent_at || r.created_at}</span>
                  <div className="muted" style={{ fontSize: "0.82rem", marginTop: "0.25rem" }}>
                    Outcome {r.outcome_status || "PENDING"} ·{" "}
                    {["1", "5", "10", "20"].map((h) => {
                      const cell = hz[h];
                      if (!cell?.available) return `T+${h}: pending`;
                      return `T+${h}: ${fmtPct(cell.excess_return ?? cell.return)}`;
                    }).join(" · ")}
                  </div>
                  {rid && r.symbol && (
                    <Link className="btn btn-ghost" to={`/research/${rid}/${r.symbol}`} style={{ marginTop: "0.25rem" }}>
                      Research Snapshot →
                    </Link>
                  )}
                </div>
              );
            })
          )}
        </div>
      </ScrollPane>
    </PageShell>
  );
}
