import { useEffect, useState } from "react";
import { api } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type NotificationRow = {
  notification_id?: string;
  symbol?: string;
  name?: string;
  level?: string;
  channel?: string;
  status?: string;
  created_at?: string;
  sent_at?: string;
  error?: string;
  metadata?: {
    expected_excess_return?: { value?: number };
    confidence?: number;
  };
};

type Stats = {
  today_count?: number;
  days_7_count?: number;
  days_30_count?: number;
  success_rate?: number;
  BUY_count?: number;
  STRONG_BUY_count?: number;
  RISK_EXIT_count?: number;
  RATING_EXIT_count?: number;
  cooldown_count?: number;
  duplicate_count?: number;
  notification_llm_cost?: number;
  notification_attribution?: Record<string, Record<string, { insufficient_sample?: boolean; mean_market_alpha?: number; sample_count?: number }>>;
};

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export default function Notifications() {
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const [list, st] = await Promise.all([api.notifications(100), api.notificationStats()]);
      setRows((list.notifications || []) as NotificationRow[]);
      setStats(st as Stats);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  const attr = stats?.notification_attribution;

  return (
    <PageShell title="通知中心" subtitle="买入提醒 + 卖出/退出提醒 · 0 LLM · 不自动交易">
      <ScrollPane>
      {err && <p className="error">{err}</p>}
      {stats && (
        <div className="persona-panel compact">
          <h3>概览</h3>
          <dl className="metrics">
            <div className="metric">
              <dt>今日</dt>
              <dd>{stats.today_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>7日</dt>
              <dd>{stats.days_7_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>30日</dt>
              <dd>{stats.days_30_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>成功率</dt>
              <dd>{((stats.success_rate ?? 0) * 100).toFixed(0)}%</dd>
            </div>
            <div className="metric">
              <dt>BUY</dt>
              <dd>{stats.BUY_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>STRONG_BUY</dt>
              <dd>{stats.STRONG_BUY_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>RISK_EXIT</dt>
              <dd>{stats.RISK_EXIT_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>RATING_EXIT</dt>
              <dd>{stats.RATING_EXIT_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>Cooldown</dt>
              <dd>{stats.cooldown_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>Duplicate</dt>
              <dd>{stats.duplicate_count ?? 0}</dd>
            </div>
            <div className="metric">
              <dt>Notify LLM $</dt>
              <dd>${stats.notification_llm_cost ?? 0}</dd>
            </div>
          </dl>
        </div>
      )}

      {attr && (
        <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
          <h3>Notification Alpha</h3>
          {(["BUY", "STRONG_BUY", "RATING_EXIT", "RISK_EXIT"] as const).map((level) => (
            <div key={level} style={{ marginBottom: "0.5rem" }}>
              <strong>{level}</strong>
              {["5", "10", "20"].map((h) => {
                const cell = attr[level]?.[h];
                if (!cell) return null;
                return (
                  <div key={h} className="muted" style={{ fontSize: "0.85rem" }}>
                    T+{h}:{" "}
                    {cell.insufficient_sample
                      ? `INSUFFICIENT_SAMPLE (n=${cell.sample_count ?? 0})`
                      : `Market α ${fmtPct(cell.mean_market_alpha)} · n=${cell.sample_count}`}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}

      <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
        <h3>通知历史</h3>
        {rows.length === 0 ? (
          <p className="muted">暂无通知记录。Precision &gt; Recall — 无信号时不打扰。</p>
        ) : (
          rows.map((r) => (
            <div key={r.notification_id || `${r.symbol}-${r.created_at}`} className="verdict-row">
              <span className={`badge badge-${r.status === "SENT" ? "buy" : "watch"}`}>{r.status}</span>{" "}
              <span className={`badge badge-${(r.level || "").toLowerCase().includes("strong") ? "pass" : "watch"}`}>
                {r.level}
              </span>{" "}
              <strong>{r.name || r.symbol}</strong>{" "}
              <span className="muted">
                {r.symbol} · {r.channel} · {r.sent_at || r.created_at}
              </span>
              {r.error && <p className="muted" style={{ margin: "0.2rem 0 0" }}>{r.error}</p>}
            </div>
          ))
        )}
      </div>
      </ScrollPane>
    </PageShell>
  );
}
