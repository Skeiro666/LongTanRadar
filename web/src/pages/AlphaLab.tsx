import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CalibrationBarChart from "../components/research/CalibrationBarChart";
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
  status: string;
};

type PerfRow = {
  lane: string;
  sample_count: number;
  t5_excess_return?: number | null;
  t10_excess_return?: number | null;
  t5_status?: string;
  t10_status?: string;
  minimum_sample?: number;
};

type ExpRow = {
  id: string;
  label: string;
  sample_count: number;
  status: string;
  horizons: Record<
    string,
    {
      excess_return_mean?: number | null;
      delta_vs_baseline?: number | null;
      baseline_excess_return_mean?: number | null;
      status?: string;
      sample_count?: number;
    }
  >;
};

function fmtPct(v: number | null | undefined, status?: string, n?: number, minN?: number) {
  if (status === "INSUFFICIENT_SAMPLE" || (minN != null && n != null && n < minN)) return `INSUFFICIENT SAMPLE (n=${n ?? 0})`;
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export default function AlphaLab() {
  const [window, setWindow] = useState("all");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.alphaLab(window).then(setData).catch((e) => setErr(String(e)));
  }, [window]);

  const rows = (data?.source_alpha || []) as SourceRow[];
  const perf = (data?.performance_dashboard || []) as PerfRow[];
  const minN = Number(data?.minimum_sample_size ?? 30);
  const expLab = data?.experiment_lab as { baseline_row?: ExpRow; experiments?: ExpRow[] } | undefined;
  const charts = data?.calibration_charts as Record<string, Array<Record<string, unknown>>> | undefined;

  return (
    <PageShell title="Alpha Lab" subtitle="系统现在真的有效吗？— 10 秒内看 T+5 / T+10">
      <ScrollPane>
        <div style={{ marginBottom: "0.75rem", display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
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
          <Link className="btn btn-ghost" to="/token" style={{ marginLeft: "auto" }}>
            Token Dashboard →
          </Link>
        </div>

        {err && <p className="error">{err}</p>}
        {Boolean(data?.as_of) && <p className="muted">As of {String(data?.as_of)} · min n = {minN}</p>}

        <div className="persona-panel compact">
          <h3>Research Performance Dashboard</h3>
          <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th>Lane</th>
                <th>Sample</th>
                <th>T+5 Excess</th>
                <th>T+10 Excess</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {perf.map((r) => (
                <tr key={r.lane} className={r.t5_status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                  <td>{r.lane}</td>
                  <td>{r.sample_count}</td>
                  <td>{fmtPct(r.t5_excess_return, r.t5_status, r.sample_count, minN)}</td>
                  <td>{fmtPct(r.t10_excess_return, r.t10_status, r.sample_count, minN)}</td>
                  <td>{r.t10_status || r.t5_status || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
          <h3>Source Alpha</h3>
          {rows.length === 0 ? (
            <p className="muted">跑完一轮研究后显示。</p>
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
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.source} className={r.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                    <td>{r.source}</td>
                    <td>{r.sample_count}</td>
                    <td>{fmtPct(r.t1_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t5_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t10_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t20_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{r.win_rate != null && r.status !== "INSUFFICIENT_SAMPLE" ? `${(r.win_rate * 100).toFixed(0)}%` : "—"}</td>
                    <td>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {expLab && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>Experiment Lab (vs {expLab.baseline_row?.label || "No News"})</h3>
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Arm</th>
                  <th>n</th>
                  <th>T+5</th>
                  <th>Δ vs baseline</th>
                  <th>T+10</th>
                  <th>Δ vs baseline</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {[expLab.baseline_row, ...(expLab.experiments || [])].filter(Boolean).map((r) => {
                  const row = r as ExpRow;
                  const h5 = row.horizons?.["5"] || {};
                  const h10 = row.horizons?.["10"] || {};
                  return (
                    <tr key={row.id} className={row.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                      <td>{row.label}</td>
                      <td>{row.sample_count}</td>
                      <td>{fmtPct(h5.excess_return_mean, h5.status, h5.sample_count, minN)}</td>
                      <td>{fmtPct(h5.delta_vs_baseline, h5.status, h5.sample_count, minN)}</td>
                      <td>{fmtPct(h10.excess_return_mean, h10.status, h10.sample_count, minN)}</td>
                      <td>{fmtPct(h10.delta_vs_baseline, h10.status, h10.sample_count, minN)}</td>
                      <td>{row.status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="dash-grid-2" style={{ marginTop: "0.75rem" }}>
          <CalibrationBarChart title="News Score" series={charts?.news_score as never} />
          <CalibrationBarChart title="Importance" series={charts?.importance as never} />
          <CalibrationBarChart title="Novelty" series={charts?.novelty as never} />
        </div>

        {Array.isArray(data?.lab_summary) && (data?.lab_summary as string[]).length > 0 && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>程序结论</h3>
            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
              {(data?.lab_summary as string[]).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </ScrollPane>
    </PageShell>
  );
}
