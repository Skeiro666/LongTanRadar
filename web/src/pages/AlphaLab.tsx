import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CalibrationBarChart from "../components/research/CalibrationBarChart";
import { api } from "../api";
import { insufficientSample, labelPerfLane, labelSourceAlpha, labelStatus } from "../i18n/zh";
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
  if (status === "INSUFFICIENT_SAMPLE" || (minN != null && n != null && n < minN)) return insufficientSample(n);
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
    <PageShell title="Alpha 实验室" subtitle="系统现在真的有效吗？— 10 秒内看 T+5 / T+10">
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
              {w === "all" ? "全部" : w.replace("d", " 天")}
            </button>
          ))}
          <Link className="btn btn-ghost" to="/token" style={{ marginLeft: "auto" }}>
            Token 成本 →
          </Link>
        </div>

        {err && <p className="error">{err}</p>}
        {Boolean(data?.as_of) && <p className="muted">截至 {String(data?.as_of)} · 最小样本 {minN}</p>}

        <div className="persona-panel compact">
          <h3>研究表现总览</h3>
          <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th>通道</th>
                <th>样本</th>
                <th>T+5 超额</th>
                <th>T+10 超额</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {perf.map((r) => (
                <tr key={r.lane} className={r.t5_status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                  <td>{labelPerfLane(r.lane)}</td>
                  <td>{r.sample_count}</td>
                  <td>{fmtPct(r.t5_excess_return, r.t5_status, r.sample_count, minN)}</td>
                  <td>{fmtPct(r.t10_excess_return, r.t10_status, r.sample_count, minN)}</td>
                  <td>{labelStatus(r.t10_status || r.t5_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
          <h3>信号来源 Alpha</h3>
          {rows.length === 0 ? (
            <p className="muted">跑完一轮研究后显示。</p>
          ) : (
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>来源</th>
                  <th>样本</th>
                  <th>T+1</th>
                  <th>T+5</th>
                  <th>T+10</th>
                  <th>T+20</th>
                  <th>胜率</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.source} className={r.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                    <td>{labelSourceAlpha(r.source)}</td>
                    <td>{r.sample_count}</td>
                    <td>{fmtPct(r.t1_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t5_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t10_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{fmtPct(r.t20_alpha, r.status, r.sample_count, minN)}</td>
                    <td>{r.win_rate != null && r.status !== "INSUFFICIENT_SAMPLE" ? `${(r.win_rate * 100).toFixed(0)}%` : "—"}</td>
                    <td>{labelStatus(r.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {expLab && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>实验对照（基线：{expLab.baseline_row?.label || "无新闻"}）</h3>
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>实验组</th>
                  <th>样本</th>
                  <th>T+5</th>
                  <th>相对基线</th>
                  <th>T+10</th>
                  <th>相对基线</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {[expLab.baseline_row, ...(expLab.experiments || [])].filter(Boolean).map((r) => {
                  const row = r as ExpRow;
                  const h5 = row.horizons?.["5"] || {};
                  const h10 = row.horizons?.["10"] || {};
                  return (
                    <tr key={row.id} className={row.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                      <td>{labelPerfLane(row.label)}</td>
                      <td>{row.sample_count}</td>
                      <td>{fmtPct(h5.excess_return_mean, h5.status, h5.sample_count, minN)}</td>
                      <td>{fmtPct(h5.delta_vs_baseline, h5.status, h5.sample_count, minN)}</td>
                      <td>{fmtPct(h10.excess_return_mean, h10.status, h10.sample_count, minN)}</td>
                      <td>{fmtPct(h10.delta_vs_baseline, h10.status, h10.sample_count, minN)}</td>
                      <td>{labelStatus(row.status)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="dash-grid-2" style={{ marginTop: "0.75rem" }}>
          <CalibrationBarChart title="新闻分" series={charts?.news_score as never} />
          <CalibrationBarChart title="重要性" series={charts?.importance as never} />
          <CalibrationBarChart title="新颖度" series={charts?.novelty as never} />
        </div>

        {Boolean(data?.exit_lab) && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>Exit 表现（卖出引擎）</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              样本入口 {(data?.exit_lab as { n_entries?: number })?.n_entries ?? 0} · 最小样本{" "}
              {(data?.exit_lab as { minimum_sample?: number })?.minimum_sample ?? minN}
            </p>
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>样本</th>
                  <th>总收益</th>
                  <th>Sharpe</th>
                  <th>最大回撤</th>
                  <th>平均回吐</th>
                  <th>相对无退出</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {(((data?.exit_lab as { exit_alpha?: { strategies?: Array<Record<string, unknown>> } })?.exit_alpha
                  ?.strategies) || []).map((r) => (
                  <tr key={String(r.id)} className={r.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                    <td>{String(r.label)}</td>
                    <td>{String(r.sample_count ?? 0)}</td>
                    <td>{fmtPct(r.total_return as number | null, String(r.status), Number(r.sample_count), minN)}</td>
                    <td>
                      {r.status === "INSUFFICIENT_SAMPLE" || r.sharpe == null
                        ? "—"
                        : Number(r.sharpe).toFixed(2)}
                    </td>
                    <td>{fmtPct(r.max_drawdown as number | null, String(r.status), Number(r.sample_count), minN)}</td>
                    <td>{fmtPct(r.mean_giveback as number | null, String(r.status), Number(r.sample_count), minN)}</td>
                    <td>
                      {fmtPct(
                        r.delta_return_vs_no_exit as number | null,
                        String(r.status),
                        Number(r.sample_count),
                        minN
                      )}
                    </td>
                    <td>{labelStatus(String(r.status))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(() => {
              const ml = (data?.exit_lab as { ml?: Record<string, unknown> })?.ml;
              if (!ml) return null;
              return (
                <p className="muted" style={{ fontSize: "0.85rem" }}>
                  Exit ML：{String(ml.status || (ml.available ? "OK" : "未训练"))}
                  {ml.sample_count != null ? ` · 样本 ${String(ml.sample_count)}` : ""}
                  {ml.mse != null ? ` · MSE ${Number(ml.mse).toFixed(4)}` : ""}
                </p>
              );
            })()}
            <Link className="btn btn-ghost" to="/positions">
              打开持仓/退出 →
            </Link>
          </div>
        )}

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
