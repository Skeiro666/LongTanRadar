import { useEffect, useState } from "react";
import { api } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type SourceRow = {
  source: string;
  sample_count: number;
  t1_alpha?: number | null;
  t5_alpha?: number | null;
  t10_alpha?: number | null;
  t20_alpha?: number | null;
  win_rate?: number | null;
  median_return?: number | null;
  cost_usd?: number | null;
  incremental_alpha?: number | null;
  efficiency?: number | null;
  status: string;
};

type LabData = {
  window?: string;
  minimum_sample_size?: number;
  as_of?: string;
  source_alpha?: SourceRow[];
  ai_council_ablation?: Record<string, unknown>;
  ml_ablation?: Record<string, unknown>;
  calibration?: Record<string, unknown>;
  token_efficiency?: Record<string, unknown>;
  ai_routing?: Record<string, unknown>;
  lab_summary?: string[];
  news_alpha?: Record<string, unknown>;
  news_calibration?: Record<string, unknown>;
  news_ablation?: Record<string, unknown>;
  news_ab_buckets?: Record<string, unknown>;
  news_token_stats?: Record<string, unknown>;
  cloud_token_stats?: Record<string, unknown>;
  token_saved_pct?: number;
  news_discovery?: Record<string, unknown>;
  news_evidence?: Record<string, unknown>;
};

function horizonCell(hz: Record<string, unknown> | undefined, key: string) {
  const h = (hz || {})[key] as Record<string, unknown> | undefined;
  if (!h) return "—";
  if (h.status === "INSUFFICIENT_SAMPLE") return `n=${h.sample_count}`;
  const ex = h.excess_return as Record<string, number> | undefined;
  if (ex?.mean != null) return fmtPct(ex.mean);
  const sel = h.selection_alpha as Record<string, number> | undefined;
  if (sel?.mean != null) return fmtPct(sel.mean);
  return String(h.status || "—");
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export default function AlphaLab() {
  const [window, setWindow] = useState("all");
  const [data, setData] = useState<LabData | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .alphaLab(window)
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [window]);

  const rows = data?.source_alpha || [];

  return (
    <PageShell title="Alpha Lab" subtitle="V5.4 · Source Alpha · Ablation · Routing · Evidence > Opinion">
      <ScrollPane>
        <div style={{ marginBottom: "0.75rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <span className="muted">窗口</span>
          {(["7d", "30d", "90d", "all"] as const).map((w) => (
            <button
              key={w}
              type="button"
              className={window === w ? "badge badge-buy" : "badge badge-watch"}
              onClick={() => setWindow(w)}
            >
              {w === "all" ? "全部" : w.toUpperCase()}
            </button>
          ))}
          {data?.minimum_sample_size != null && (
            <span className="muted" style={{ marginLeft: "auto" }}>
              min n = {data.minimum_sample_size}
            </span>
          )}
        </div>

        {err && <p className="error">{err}</p>}
        {data?.as_of && <p className="muted">As of {data.as_of}</p>}

        <div className="persona-panel compact">
          <h3>Source Alpha</h3>
          {rows.length === 0 ? (
            <p className="muted">跑完一轮研究后显示模块 Alpha 表。</p>
          ) : (
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>n</th>
                  <th>T+1</th>
                  <th>T+5</th>
                  <th>T+10</th>
                  <th>T+20</th>
                  <th>Win%</th>
                  <th>Median</th>
                  <th>Δα</th>
                  <th>Cost</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.source}>
                    <td>{r.source}</td>
                    <td>{r.sample_count}</td>
                    <td>{fmtPct(r.t1_alpha)}</td>
                    <td>{fmtPct(r.t5_alpha)}</td>
                    <td>{fmtPct(r.t10_alpha)}</td>
                    <td>{fmtPct(r.t20_alpha)}</td>
                    <td>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : "—"}</td>
                    <td>{fmtPct(r.median_return)}</td>
                    <td>{fmtPct(r.incremental_alpha)}</td>
                    <td>{r.cost_usd != null ? `$${Number(r.cost_usd).toFixed(2)}` : "$0"}</td>
                    <td>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {data?.news_token_stats && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>News Token (Local Ollama)</h3>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              calls={String(data.news_token_stats.calls ?? 0)} · cache_hits=
              {String(data.news_token_stats.cache_hits ?? 0)} · tokens=
              {String(data.news_token_stats.total_tokens ?? 0)} · saved{" "}
              {data.token_saved_pct != null ? `${data.token_saved_pct}%` : "—"}
            </p>
            {data.cloud_token_stats && (
              <p className="muted" style={{ fontSize: "0.85rem" }}>
                Cloud: calls={String(data.cloud_token_stats.calls ?? 0)} · tokens=
                {String(data.cloud_token_stats.total_tokens ?? 0)} · cost $
                {Number(data.cloud_token_stats.cost_usd ?? 0).toFixed(2)}
              </p>
            )}
          </div>
        )}

        {data?.news_alpha && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>News Alpha (Discovery / Evidence / Factor / Council)</h3>
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Lane</th>
                  <th>T+5</th>
                  <th>T+10</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["Discovery", data.news_alpha.news_discovery_alpha],
                    ["Evidence", data.news_alpha.news_evidence_alpha],
                    ["News+Factor", data.news_alpha.news_factor_alpha],
                    ["News+Council", data.news_alpha.news_council_alpha],
                  ] as const
                ).map(([label, hz]) => {
                  const h5 = (hz as Record<string, unknown>)?.["5"] as Record<string, unknown> | undefined;
                  const h10 = (hz as Record<string, unknown>)?.["10"] as Record<string, unknown> | undefined;
                  return (
                    <tr key={label}>
                      <td>{label}</td>
                      <td>{horizonCell(hz as Record<string, unknown>, "5")}</td>
                      <td>{horizonCell(hz as Record<string, unknown>, "10")}</td>
                      <td>{String(h5?.status || h10?.status || "—")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {data?.news_ab_buckets && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>News A/B/C/D (News Only = B)</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.news_ab_buckets, null, 2)}
            </pre>
          </div>
        )}

        {data?.news_calibration && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>News Score / Importance / Novelty Calibration</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.news_calibration, null, 2)}
            </pre>
          </div>
        )}

        {data?.ai_council_ablation && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>AI Ablation</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.ai_council_ablation, null, 2)}
            </pre>
          </div>
        )}

        {data?.calibration && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>Prediction Calibration</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.calibration, null, 2)}
            </pre>
          </div>
        )}

        {data?.token_efficiency && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>Token Efficiency</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.token_efficiency, null, 2)}
            </pre>
          </div>
        )}

        {data?.ai_routing && Object.keys(data.ai_routing).length > 0 && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>AI Routing</h3>
            <pre style={{ fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(data.ai_routing, null, 2)}
            </pre>
          </div>
        )}

        {data?.lab_summary && data.lab_summary.length > 0 && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>研究结论（程序生成）</h3>
            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
              {data.lab_summary.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </ScrollPane>
    </PageShell>
  );
}
