import { useEffect, useState } from "react";
import { api, num } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type T5Stats = {
  mean?: number;
  median?: number;
  win_rate?: number;
  limit_down_rate?: number;
  mean_mdd?: number;
};

type Cell = {
  n?: number;
  status?: string;
  mfe_mean?: number;
  mae_mean?: number;
  max_drawdown_mean?: number;
  gap_down_rate?: number;
  n_high?: number;
} & {
  "t+5"?: T5Stats;
};

const MODE_ZH: Record<string, string> = {
  DIRECT_CHASE: "直接追涨",
  FIRST_DIVERGENCE: "首次分歧",
  PULLBACK: "回踩",
  REBREAKOUT: "重新突破",
  REACCELERATION: "再加速",
  RANDOM_LIMIT_UP: "随机涨停买入",
  board_3_direct: "3板直接买",
  board_4_direct: "4板直接买",
  board_5_direct: "5板直接买",
};

const STATUS_ZH: Record<string, string> = {
  OK: "样本充足",
  LOW_SAMPLE: "样本偏少",
  INSUFFICIENT_SAMPLE: "样本不足",
};

const STAGE_ZH: Record<string, string> = {
  EARLY: "早期",
  TREND: "趋势",
  ACCELERATION: "加速",
  EXTREME: "极端",
  DISTRIBUTION: "派发",
  BREAKDOWN: "破位",
  NA: "无",
  "?": "未知",
};

const FEATURE_ZH: Record<string, string> = {
  structure: "结构",
  pullback: "回踩",
  volume: "量能",
  reacceleration: "再加速",
  confirmation: "确认",
};

const ABLATION_ZH: Record<string, string> = {
  FULL: "完整模型",
  FULL_minus_structure: "去掉结构",
  FULL_minus_pullback: "去掉回踩",
  FULL_minus_volume: "去掉量能",
  FULL_minus_reacceleration: "去掉再加速",
  FULL_minus_confirmation: "去掉确认",
  structure_only: "仅结构",
  pullback_only: "仅回踩",
  volume_only: "仅量能",
  reacceleration_only: "仅再加速",
  confirmation_only: "仅确认",
};

const FUNNEL_ZH: Record<string, string> = {
  ENTRY_EVENTS: "入场事件总数",
  DIRECT_CHASE: "直接追涨",
  FIRST_DIVERGENCE: "首次分歧",
  PULLBACK: "回踩",
  REBREAKOUT: "重新突破",
  REACCELERATION: "再加速",
  stage_EXTREME: "极端阶段样本",
  timing_BUY_CANDIDATE: "买点候选",
  timing_BUY_READY: "可买入",
  timing_WAIT: "等待",
};

const EDGE_ZH: Record<string, string> = {
  NO_STATISTICAL_EDGE_PROVEN: "尚未证明存在统计意义上的优势",
  STATISTICAL_EDGE_SUGGESTED: "数据显示可能存在优势（仍需更多验证）",
};

const CAL_ZH: Record<string, string> = {
  "REENTRY SCORE NOT CALIBRATED": "再入场分数未校准（分数高低与收益不同步）",
  CALIBRATED: "再入场分数已校准",
};

function zhLabel(raw: string): string {
  if (MODE_ZH[raw]) return MODE_ZH[raw];
  if (ABLATION_ZH[raw]) return ABLATION_ZH[raw];
  if (FUNNEL_ZH[raw]) return FUNNEL_ZH[raw];
  if (raw.includes("|")) {
    const [a, b] = raw.split("|");
    const left = STAGE_ZH[a] || (a.match(/^\d/) ? `${a}板` : a);
    const right = MODE_ZH[b] || STAGE_ZH[b] || b;
    return `${left} × ${right}`;
  }
  if (FEATURE_ZH[raw]) return FEATURE_ZH[raw];
  return raw;
}

function zhBool(v: unknown): string {
  if (v === true || v === "True" || v === "true") return "是";
  if (v === false || v === "False" || v === "false") return "否";
  if (v == null || v === "None" || v === "null") return "无法判断";
  return String(v);
}

function pct(x?: number | null) {
  if (x == null || Number.isNaN(x)) return "-";
  return `${(x * 100).toFixed(2)}%`;
}

function ModeTable({ title, data }: { title: string; data?: Record<string, Cell> }) {
  if (!data) return null;
  const modes = Object.keys(data);
  return (
    <section className="panel">
      <h3>{title}</h3>
      <table className="data-table compact">
        <thead>
          <tr>
            <th>类别</th>
            <th>样本数</th>
            <th>样本状态</th>
            <th>五日收益均值</th>
            <th>五日胜率</th>
            <th>五日跌停率</th>
            <th>最大有利波动</th>
            <th>最大不利波动</th>
          </tr>
        </thead>
        <tbody>
          {modes.map((m) => {
            const c = data[m] || {};
            const t5 = c["t+5"] || {};
            return (
              <tr key={m}>
                <td>{zhLabel(m)}</td>
                <td>{c.n ?? "-"}</td>
                <td>{STATUS_ZH[c.status || ""] || c.status || "-"}</td>
                <td>{pct(t5.mean)}</td>
                <td>{pct(t5.win_rate)}</td>
                <td>{pct(t5.limit_down_rate)}</td>
                <td>{pct(c.mfe_mean)}</td>
                <td>{pct(c.mae_mean)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default function EntryValidation() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .leaderEntryValidation()
      .then((payload) => setData(payload))
      .catch((e) => setErr(String(e)));
  }, []);

  const v = (data?.verdicts || {}) as Record<string, unknown>;
  const meta = (data?.meta || {}) as Record<string, unknown>;
  const funnel = (data?.buy_pipeline_funnel || {}) as Record<string, unknown>;
  const cal = (data?.reentry_calibration || {}) as {
    verdict?: string;
    spearman_approx?: number;
    bins?: Record<string, Cell>;
  };
  const wf = (data?.walk_forward || {}) as Record<string, unknown>;
  const edgeKey = String(v.statistical_edge || "");
  const calKey = String(v.reentry_calibration_verdict || cal.verdict || "");

  return (
    <PageShell title="买点验证" subtitle="用历史数据检验各类买点是否真有优势（参数冻结，不调用大模型）">
      <ScrollPane>
        {err ? <p className="error">{err}</p> : null}
        {!data ? <p className="muted">加载中…</p> : null}
        {data && data.available === false ? <p className="muted">{String(data.message)}</p> : null}
        {data && data.available !== false ? (
          <>
            <section className="panel">
              <h3>研究结论</h3>
              <p>
                <strong>{EDGE_ZH[edgeKey] || edgeKey || "-"}</strong>
              </p>
              <ul className="muted">
                <li>
                  样本数 {String(meta.n_samples)} · 股票数 {String(meta.n_symbols_scanned)} · 耗时{" "}
                  {String(meta.elapsed_sec)} 秒 · 大模型调用 {String(meta.llm_calls)} · Token{" "}
                  {String(meta.tokens)}
                </li>
                <li>分数校准：{CAL_ZH[calKey] || calKey || "-"}</li>
                <li>极端阶段「等待后再买」是否优于直接追涨：{zhBool(v.extreme_wait_better_than_chase)}</li>
                <li>滚动验证优势是否稳定：{zhBool(v.walk_forward_edge_stable)}</li>
                <li>
                  最重要特征：{FEATURE_ZH[String(v.most_important_feature || "")] || String(v.most_important_feature || "-")}
                  {" · "}
                  买点候选 {String(v.buy_candidate_count)} · 可买入 {String(v.buy_ready_count)}
                </li>
              </ul>
            </section>

            <ModeTable title="各买点表现" data={data.entry_mode_performance as Record<string, Cell>} />
            <ModeTable title="极端阶段后的路径对比" data={data.extreme_path_performance as Record<string, Cell>} />
            <ModeTable title="简单基准对比" data={data.baselines as Record<string, Cell>} />
            <ModeTable title="连板数 × 买点" data={data.board_x_entry as Record<string, Cell>} />
            <ModeTable title="阶段 × 买点" data={data.stage_x_entry as Record<string, Cell>} />
            <ModeTable title="因子消融（高分样本）" data={data.ablation as Record<string, Cell>} />

            <section className="panel">
              <h3>再入场分数校准</h3>
              <p className="muted">
                {CAL_ZH[String(cal.verdict || "")] || cal.verdict} · 等级相关约 {num(cal.spearman_approx, 3)}
              </p>
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>分数区间</th>
                    <th>样本数</th>
                    <th>五日收益均值</th>
                    <th>五日胜率</th>
                    <th>五日跌停率</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cal.bins || {}).map(([bin, cell]) => (
                    <tr key={bin}>
                      <td>{bin}</td>
                      <td>{cell?.n}</td>
                      <td>{pct(cell?.["t+5"]?.mean)}</td>
                      <td>{pct(cell?.["t+5"]?.win_rate)}</td>
                      <td>{pct(cell?.["t+5"]?.limit_down_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="panel">
              <h3>买入漏斗</h3>
              <ul>
                {Object.entries(funnel)
                  .filter(([k]) => k !== "dry_run")
                  .map(([k, val]) => (
                    <li key={k}>
                      {FUNNEL_ZH[k] || zhLabel(k)}：{String(val)}
                    </li>
                  ))}
              </ul>
              {funnel.dry_run ? (
                <div className="muted small">
                  <p>最近一次试跑摘要：</p>
                  <ul>
                    {Object.entries(funnel.dry_run as Record<string, unknown>).map(([k, val]) => (
                      <li key={k}>
                        {k === "n_enriched"
                          ? "入池增强数"
                          : k === "n_research"
                            ? "研究数"
                            : k === "buy_candidate_n"
                              ? "买点候选"
                              : k === "buy_ready_n"
                                ? "可买入"
                                : k === "timing_counts"
                                  ? "时机统计"
                                  : k === "reentry_phase_counts"
                                    ? "再入场阶段统计"
                                    : k === "focus_stats"
                                      ? "重点池统计"
                                      : k}
                        ：{typeof val === "object" ? JSON.stringify(val) : String(val)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>

            <section className="panel">
              <h3>滚动验证（前训 / 中验 / 后测）</h3>
              <ul className="muted">
                <li>状态：{STATUS_ZH[String(wf.status || "")] || String(wf.status || "-")}</li>
                <li>优势是否跨期稳定：{zhBool(wf.edge_stable)}</li>
                <li>
                  测试期「再加速 − 直接追涨」五日收益差：
                  {wf.reaccel_minus_chase_test == null ? "无法计算" : pct(Number(wf.reaccel_minus_chase_test))}
                </li>
                {wf.pullback_minus_chase_test != null ? (
                  <li>测试期「回踩 − 直接追涨」五日收益差：{pct(Number(wf.pullback_minus_chase_test))}</li>
                ) : null}
                {wf.edge_stable_reason ? <li>说明：{String(wf.edge_stable_reason)}</li> : null}
              </ul>
            </section>
          </>
        ) : null}
      </ScrollPane>
    </PageShell>
  );
}
