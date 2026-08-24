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

        {Boolean(data?.exit_lab) && (() => {
          const lab = data?.exit_lab as Record<string, unknown>;
          const ev = (lab?.exit_validation || {}) as Record<string, unknown>;
          const cal = (ev.calibration || lab.calibration || {}) as Record<string, unknown>;
          const chartsEv = (ev.charts || {}) as Record<string, unknown>;
          const report = (ev.report || lab.validation_report || {}) as Record<string, unknown>;
          const answers = (report.answers || {}) as Record<string, unknown>;
          const featIc = ((ev.feature_ic || lab.feature_ic || {}) as { features?: Array<Record<string, unknown>> }).features || [];
          const redPairs = ((ev.redundancy || lab.redundancy || {}) as { pairs?: Array<Record<string, unknown>>; high_redundancy_count?: number }).pairs || [];
          const timing = (ev.timing || {}) as Record<string, unknown>;
          const giveback = (ev.giveback || {}) as Record<string, Record<string, unknown>>;
          const chartOk = Boolean(chartsEv.available);
          const strategies =
            ((lab.exit_alpha as { strategies?: Array<Record<string, unknown>> })?.strategies) ||
            (ev.ablation as Array<Record<string, unknown>>) ||
            [];

          return (
            <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
              <h3>Exit Validation（卖出系统有没有 Alpha？）</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                样本入口 {String(lab?.n_entries ?? 0)} · 校准行 {String(lab?.n_calibration_rows ?? 0)} · 最小样本{" "}
                {String(lab?.minimum_sample ?? minN)} · 执行 {String(lab?.execution_model || "t1_open")}
              </p>
              {Boolean(report.verdict) && (
                <p style={{ fontSize: "0.92rem" }}>
                  <strong>结论：</strong>
                  {String(report.verdict)}
                </p>
              )}

              <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th>策略</th>
                    <th>样本</th>
                    <th>净收益</th>
                    <th>毛收益</th>
                    <th>Sharpe</th>
                    <th>最大回撤</th>
                    <th>平均回吐</th>
                    <th>相对无退出</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((r) => (
                    <tr key={String(r.id)} className={r.status === "INSUFFICIENT_SAMPLE" ? "insufficient-row" : ""}>
                      <td>{String(r.label)}</td>
                      <td>{String(r.sample_count ?? 0)}</td>
                      <td>{fmtPct(r.total_return as number | null, String(r.status), Number(r.sample_count), minN)}</td>
                      <td>
                        {fmtPct(r.total_return_gross as number | null, String(r.status), Number(r.sample_count), minN)}
                      </td>
                      <td>
                        {r.status === "INSUFFICIENT_SAMPLE" || r.sharpe == null ? "—" : Number(r.sharpe).toFixed(2)}
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

              <div className="dash-grid-2" style={{ marginTop: "0.75rem" }}>
                <div>
                  <h4 style={{ marginBottom: "0.35rem" }}>Exit Score → T+10 收益</h4>
                  {!chartOk ? (
                    <p className="muted">样本不足，不画误导散点图</p>
                  ) : (
                    <CalibrationBarChart
                      title="分桶平均 T+10"
                      series={((chartsEv.bucket_t10 as Array<Record<string, unknown>>) || []).map((b) => ({
                        bucket: String(b.range),
                        mean: b.t10_mean as number | null,
                        status: String(b.status || ""),
                      }))}
                    />
                  )}
                </div>
                <div>
                  <h4 style={{ marginBottom: "0.35rem" }}>分桶亏损率</h4>
                  {!chartOk ? (
                    <p className="muted">样本不足，不画误导图</p>
                  ) : (
                    <CalibrationBarChart
                      title="Loss Rate"
                      series={((chartsEv.bucket_loss_rate as Array<Record<string, unknown>>) || []).map((b) => ({
                        bucket: String(b.range),
                        mean: b.loss_rate as number | null,
                        status: String(b.status || ""),
                      }))}
                    />
                  )}
                </div>
              </div>

              <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
                单调性：{String(cal.monotonicity ?? answers["1_monotonicity"] ?? "—")} · IC T+10：
                {(() => {
                  const ic = answers["2_exit_score_ic"] as Record<string, unknown> | undefined;
                  const t10 = ic?.["T+10"];
                  if (t10 === "INSUFFICIENT_SAMPLE" || t10 == null) return "INSUFFICIENT_SAMPLE";
                  if (typeof t10 === "object" && t10 && "spearman" in t10) {
                    return `Spearman ${Number((t10 as { spearman?: number }).spearman).toFixed(3)}`;
                  }
                  return String(t10);
                })()}
              </p>

              {(() => {
                const icDebug = (ev.ic_debug || lab.ic_debug || {}) as Record<string, unknown>;
                const root = (icDebug.root_cause || {}) as Record<string, unknown>;
                const ic5 = (icDebug.ic_t5_close_to_close || {}) as Record<string, unknown>;
                if (!icDebug || (!root.primary && !ic5.spearman)) return null;
                return (
                  <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
                    <strong>Exit IC Debug</strong>
                    <p className="muted" style={{ margin: "0.25rem 0" }}>
                      根因：{String(root.primary || "—")} · {String(root.label || "")}
                      {ic5.spearman != null ? ` · T+5 Spearman ${Number(ic5.spearman).toFixed(3)}` : ""}
                      {icDebug.corr_exit_score_vs_past_5d_return != null
                        ? ` · corr(score, past5d) ${Number(icDebug.corr_exit_score_vs_past_5d_return).toFixed(3)}`
                        : ""}
                    </p>
                    <p className="muted" style={{ margin: 0, fontSize: "0.8rem" }}>
                      {String(root.detail || "")}
                    </p>
                    <details style={{ marginTop: "0.35rem" }}>
                      <summary>IC 样本（T close → T+5 close）</summary>
                      <table className="data-table" style={{ width: "100%", fontSize: "0.75rem" }}>
                        <thead>
                          <tr>
                            <th>symbol</th>
                            <th>score_time</th>
                            <th>label_time</th>
                            <th>score</th>
                            <th>ret_5d</th>
                            <th>price_t</th>
                            <th>price_t5</th>
                            <th>adj</th>
                          </tr>
                        </thead>
                        <tbody>
                          {((icDebug.samples as Array<Record<string, unknown>>) || []).slice(0, 20).map((s, i) => (
                            <tr key={`${s.symbol}-${i}`}>
                              <td>{String(s.symbol)}</td>
                              <td>{String(s.score_time)}</td>
                              <td>{String(s.label_time)}</td>
                              <td>{s.score != null ? Number(s.score).toFixed(3) : "—"}</td>
                              <td>
                                {s.future_return_5d != null
                                  ? `${(Number(s.future_return_5d) * 100).toFixed(2)}%`
                                  : "—"}
                              </td>
                              <td>{s.price_t != null ? Number(s.price_t).toFixed(2) : "—"}</td>
                              <td>{s.price_t5 != null ? Number(s.price_t5).toFixed(2) : "—"}</td>
                              <td>{String(s.adj_type || "qfq")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  </div>
                );
              })()}

              {(() => {
                const rg = (ev.risk_group || lab.risk_group || {}) as Record<string, unknown>;
                const uiRows = (rg.ui_rows || ev.feature_groups || []) as Array<Record<string, unknown>>;
                const matrix = (rg.correlation_matrix_spearman || {}) as Record<string, Record<string, number | null>>;
                const feats = Object.keys(matrix);
                if (!rg.available && !uiRows.length) return null;
                return (
                  <div style={{ marginTop: "0.75rem" }}>
                    <h4 style={{ marginBottom: "0.35rem" }}>Exit Feature Groups（RISK）</h4>
                    <p className="muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>
                      生产权重未改写 · Candidate only · 冗余阈值 HIGH≥
                      {String((rg.thresholds as { high?: number })?.high ?? 0.8)}
                    </p>
                    {uiRows.length > 0 && (
                      <table className="data-table" style={{ width: "100%", fontSize: "0.8rem" }}>
                        <thead>
                          <tr>
                            <th>GROUP</th>
                            <th>FEATURE</th>
                            <th>WEIGHT</th>
                            <th>IC_5d</th>
                            <th>IC_10d</th>
                            <th>REDUNDANCY</th>
                            <th>CONTRIBUTION</th>
                          </tr>
                        </thead>
                        <tbody>
                          {uiRows.map((r) => (
                            <tr key={String(r.feature)}>
                              <td>{String(r.group)}</td>
                              <td>{String(r.feature)}</td>
                              <td>{r.weight != null ? Number(r.weight).toFixed(2) : "—"}</td>
                              <td>{r.IC_5d == null ? "—" : Number(r.IC_5d).toFixed(3)}</td>
                              <td>{r.IC_10d == null ? "—" : Number(r.IC_10d).toFixed(3)}</td>
                              <td>{String(r.redundancy || "—")}</td>
                              <td>{String(r.contribution || "—")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {feats.length > 0 && (
                      <details style={{ marginTop: "0.35rem" }}>
                        <summary>RISK Spearman Correlation Matrix</summary>
                        <table className="data-table" style={{ width: "100%", fontSize: "0.7rem" }}>
                          <thead>
                            <tr>
                              <th></th>
                              {feats.map((f) => (
                                <th key={f}>{f.slice(0, 8)}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {feats.map((a) => (
                              <tr key={a}>
                                <td>{a.slice(0, 10)}</td>
                                {feats.map((b) => {
                                  const v = matrix[a]?.[b];
                                  return (
                                    <td
                                      key={b}
                                      style={{
                                        background:
                                          v != null && Math.abs(v) >= 0.8
                                            ? "rgba(200,80,80,0.25)"
                                            : v != null && Math.abs(v) >= 0.6
                                              ? "rgba(200,160,60,0.2)"
                                              : undefined,
                                      }}
                                    >
                                      {v == null ? "—" : v.toFixed(2)}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    )}
                    {Boolean(rg.answers) && (
                      <details style={{ marginTop: "0.35rem" }}>
                        <summary>RISK GROUP 结论</summary>
                        <pre className="council-expand" style={{ maxHeight: 220, fontSize: "0.75rem" }}>
                          {JSON.stringify(rg.answers, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                );
              })()}

              <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
                <strong>Profit Giveback</strong>
                <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem" }}>
                  {(["no_exit", "fixed_stop", "exit_engine"] as const).map((k) => {
                    const g = giveback[k] || {};
                    return (
                      <li key={k}>
                        {k}: mean {fmtPct(g.mean as number | null, String(g.status))} · median{" "}
                        {fmtPct(g.median as number | null, String(g.status))} · P90{" "}
                        {fmtPct(g.p90 as number | null, String(g.status))}
                      </li>
                    );
                  })}
                </ul>
              </div>

              <p className="muted" style={{ fontSize: "0.85rem" }}>
                Exit Timing：Early{" "}
                {timing.available ? `${(Number(timing.early_pct) * 100).toFixed(1)}%` : "INSUFFICIENT_SAMPLE"} · Good{" "}
                {timing.available ? `${(Number(timing.good_pct) * 100).toFixed(1)}%` : "—"} · Late{" "}
                {timing.available ? `${(Number(timing.late_pct) * 100).toFixed(1)}%` : "—"}
              </p>

              {featIc.length > 0 && (
                <details style={{ marginTop: "0.5rem" }}>
                  <summary>Feature IC</summary>
                  <table className="data-table" style={{ width: "100%", fontSize: "0.8rem" }}>
                    <thead>
                      <tr>
                        <th>feature</th>
                        <th>IC_5d</th>
                        <th>IC_10d</th>
                        <th>IC_20d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {featIc.slice(0, 20).map((f) => (
                        <tr key={String(f.feature)}>
                          <td>{String(f.feature)}</td>
                          <td>{f.IC_5d == null ? "—" : Number(f.IC_5d).toFixed(3)}</td>
                          <td>{f.IC_10d == null ? "—" : Number(f.IC_10d).toFixed(3)}</td>
                          <td>{f.IC_20d == null ? "—" : Number(f.IC_20d).toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}

              {redPairs.length > 0 && (
                <details style={{ marginTop: "0.35rem" }}>
                  <summary>
                    Feature Redundancy（|corr|&gt;0.8 → HIGH_REDUNDANCY，不自动删除）
                  </summary>
                  <ul style={{ fontSize: "0.8rem", margin: "0.25rem 0 0", paddingLeft: "1.1rem" }}>
                    {redPairs
                      .filter((p) => p.high_redundancy)
                      .slice(0, 12)
                      .map((p) => (
                        <li key={`${p.a}-${p.b}`}>
                          {String(p.a)} ↔ {String(p.b)} · Spearman {Number(p.spearman).toFixed(2)} · HIGH_REDUNDANCY
                        </li>
                      ))}
                    {redPairs.filter((p) => p.high_redundancy).length === 0 && (
                      <li className="muted">当前无 |corr|&gt;0.8 对</li>
                    )}
                  </ul>
                </details>
              )}

              {(() => {
                const ml = lab?.ml as Record<string, unknown> | undefined;
                const cmp = lab?.ml_vs_heuristic as Record<string, unknown> | undefined;
                if (!ml && !cmp) return null;
                return (
                  <p className="muted" style={{ fontSize: "0.85rem" }}>
                    Exit ML：{String(ml?.keep || cmp?.keep || "HEURISTIC")} ·{" "}
                    {String(ml?.status || cmp?.status || (ml?.available ? "OK" : "未训练"))}
                    {ml?.sample_count != null ? ` · 样本 ${String(ml.sample_count)}` : ""}
                    {cmp?.ml_improves === false ? " · 未显著优于 Heuristic" : ""}
                  </p>
                );
              })()}

              <details style={{ marginTop: "0.35rem" }}>
                <summary>十三问摘要</summary>
                <pre className="council-expand" style={{ maxHeight: 280, fontSize: "0.75rem" }}>
                  {JSON.stringify(answers, null, 2)}
                </pre>
              </details>

              <Link className="btn btn-ghost" to="/positions">
                打开持仓/退出 →
              </Link>
            </div>
          );
        })()}

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
