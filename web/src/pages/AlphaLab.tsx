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
};

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
