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

type DistCell = {
  n?: number;
  status?: string;
  mean_return?: number;
  median_return?: number;
  win_rate?: number;
  limit_down_rate?: number;
  MDD?: number;
  MAE_mean?: number;
  risk_adjusted_return?: number;
  distribution?: Record<string, { p10?: number; p90?: number; histogram?: Record<string, number> }>;
};

type Headline = {
  mean?: number;
  median?: number;
  win_rate?: number;
  limit_down_rate?: number;
  worst?: number;
  best?: number;
  top10pct_share_of_positive_pnl?: number;
  risk_adjusted_return?: number;
  ev_net_t5?: number;
  histogram?: Record<string, number>;
};

const HEALTH_ZH: Record<string, string> = {
  HEALTHY_PULLBACK: "健康回踩",
  DANGEROUS_PULLBACK: "危险回踩",
  NEUTRAL_PULLBACK: "中性回踩",
  HEALTHY_PULLBACK_NOW: "健康回踩当日买",
  HP_THEN_REACCEL: "健康回踩后等再加速",
  AFTER_PULLBACK: "回踩后再加速",
  AFTER_DIVERGENCE: "分歧后再加速",
  AFTER_EXTREME: "极端后再加速",
  DIRECT_REACCEL: "直接再加速",
  STRUCTURE_REPAIRED: "结构修复后再加速",
};

function HistBars({ hist }: { hist?: Record<string, number> }) {
  if (!hist) return null;
  const max = Math.max(1, ...Object.values(hist));
  return (
    <div className="hist-bars" style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 72, marginTop: 8 }}>
      {Object.entries(hist).map(([k, v]) => (
        <div key={k} title={`${k}: ${v}`} style={{ flex: 1, textAlign: "center" }}>
          <div
            style={{
              height: `${Math.round((v / max) * 56)}px`,
              background: k.includes("-") && !k.startsWith("0") && !k.startsWith("5") ? "#b45309" : "#0f766e",
              borderRadius: 2,
            }}
          />
          <div className="muted" style={{ fontSize: 10 }}>
            {v}
          </div>
        </div>
      ))}
    </div>
  );
}

function DistTable({
  title,
  data,
  labelPrefix,
}: {
  title: string;
  data?: Record<string, DistCell>;
  labelPrefix?: string;
}) {
  if (!data) return null;
  return (
    <section className="panel">
      <h3>{title}</h3>
      <table className="data-table compact">
        <thead>
          <tr>
            <th>类别</th>
            <th>样本数</th>
            <th>状态</th>
            <th>均值</th>
            <th>中位数</th>
            <th>胜率</th>
            <th>跌停率</th>
            <th>最大回撤</th>
            <th>不利波动</th>
            <th>风险调整</th>
            <th>P10</th>
            <th>P90</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([k, c]) => {
            const t5 = c.distribution?.["t+5"] || {};
            const label =
              HEALTH_ZH[k] ||
              MODE_ZH[k] ||
              (labelPrefix && /^\d/.test(k) ? `${k}${labelPrefix}` : zhLabel(k));
            return (
              <tr key={k}>
                <td>{label}</td>
                <td>{c.n ?? "-"}</td>
                <td>{STATUS_ZH[c.status || ""] || c.status || "-"}</td>
                <td>{pct(c.mean_return)}</td>
                <td>{pct(c.median_return)}</td>
                <td>{pct(c.win_rate)}</td>
                <td>{pct(c.limit_down_rate)}</td>
                <td>{pct(c.MDD)}</td>
                <td>{pct(c.MAE_mean)}</td>
                <td>{pct(c.risk_adjusted_return)}</td>
                <td>{pct(t5.p10)}</td>
                <td>{pct(t5.p90)}</td>
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
  const [dist, setDist] = useState<Record<string, unknown> | null>(null);
  const [hp, setHp] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.leaderEntryValidation(),
      api.leaderEntryDistribution(),
      api.leaderHealthyPullback(),
    ])
      .then(([validation, distribution, healthy]) => {
        setData(validation);
        setDist(distribution?.available === false ? null : distribution);
        setHp(healthy?.available === false ? null : healthy);
      })
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
  const lab = (dist || (data?.distribution_lab as Record<string, unknown>) || null) as Record<
    string,
    unknown
  > | null;
  const chasePull = (lab?.chase_vs_pullback || {}) as Record<string, Headline>;
  const modeDist = (lab?.mode_distribution || {}) as Record<string, DistCell>;
  const chaseBoard = (lab?.direct_chase_by_board || {}) as Record<string, DistCell>;
  const pbDepth = (lab?.pullback_by_depth || {}) as Record<string, DistCell>;
  const pbHealth = (lab?.pullback_by_health || {}) as Record<string, DistCell>;
  const rePaths = (lab?.reacceleration_paths || {}) as Record<string, DistCell>;
  const answers = (lab?.answers || {}) as Record<string, unknown>;
  const labMeta = (lab?.meta || {}) as Record<string, unknown>;

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
                  最重要特征：
                  {FEATURE_ZH[String(v.most_important_feature || "")] ||
                    String(v.most_important_feature || "-")}
                  {" · "}
                  买点候选 {String(v.buy_candidate_count)} · 可买入 {String(v.buy_ready_count)}
                </li>
              </ul>
            </section>

            {lab ? (
              <section className="panel">
                <h3>收益分布实验室（核心）</h3>
                <p className="muted">
                  往返成本约 {pct(Number(labMeta.cost_rate_round_trip))} · 再入场分数状态：未校准 · 大模型调用{" "}
                  {String(labMeta.llm_calls ?? 0)} · 总评：
                  {String(answers.overall || "-") === "NO_EDGE_PROVEN"
                    ? "尚未证明优势"
                    : String(answers.overall || "-")}
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <div>
                    <h4>直接追涨</h4>
                    <ul className="muted">
                      <li>均值 {pct(chasePull.DIRECT_CHASE?.mean)} / 中位数 {pct(chasePull.DIRECT_CHASE?.median)}</li>
                      <li>胜率 {pct(chasePull.DIRECT_CHASE?.win_rate)} · 跌停率 {pct(chasePull.DIRECT_CHASE?.limit_down_rate)}</li>
                      <li>
                        最差 {pct(chasePull.DIRECT_CHASE?.worst)} · 最好 {pct(chasePull.DIRECT_CHASE?.best)}
                      </li>
                      <li>
                        头部10%占正收益池 {pct(chasePull.DIRECT_CHASE?.top10pct_share_of_positive_pnl)}
                      </li>
                      <li>
                        扣费后期望 {pct(chasePull.DIRECT_CHASE?.ev_net_t5)} · 风险调整{" "}
                        {pct(chasePull.DIRECT_CHASE?.risk_adjusted_return)}
                      </li>
                    </ul>
                    <HistBars hist={chasePull.DIRECT_CHASE?.histogram} />
                    <p className="muted small">可能赚很多，但极容易吃大亏（跌停率高、左尾厚）。</p>
                  </div>
                  <div>
                    <h4>回踩</h4>
                    <ul className="muted">
                      <li>均值 {pct(chasePull.PULLBACK?.mean)} / 中位数 {pct(chasePull.PULLBACK?.median)}</li>
                      <li>胜率 {pct(chasePull.PULLBACK?.win_rate)} · 跌停率 {pct(chasePull.PULLBACK?.limit_down_rate)}</li>
                      <li>
                        最差 {pct(chasePull.PULLBACK?.worst)} · 最好 {pct(chasePull.PULLBACK?.best)}
                      </li>
                      <li>
                        头部10%占正收益池 {pct(chasePull.PULLBACK?.top10pct_share_of_positive_pnl)}
                      </li>
                      <li>
                        扣费后期望 {pct(chasePull.PULLBACK?.ev_net_t5)} · 风险调整{" "}
                        {pct(chasePull.PULLBACK?.risk_adjusted_return)}
                      </li>
                    </ul>
                    <HistBars hist={chasePull.PULLBACK?.histogram} />
                    <p className="muted small">收益未必最高，但风险明显下降，是当前最值得继续研究的买点。</p>
                  </div>
                </div>
              </section>
            ) : (
              <section className="panel">
                <h3>收益分布实验室</h3>
                <p className="muted">尚未生成。请运行：python scripts/leader_entry_distribution.py</p>
              </section>
            )}

            {lab ? (
              <>
                <DistTable title="各买点分位数与风险（五日）" data={modeDist} />
                <DistTable title="直接追涨按连板拆解" data={chaseBoard} labelPrefix="板" />
                <DistTable title="回踩深度拆解" data={pbDepth} />
                <DistTable title="健康回踩 vs 危险回踩" data={pbHealth} />
                <DistTable title="再加速路径拆解" data={rePaths} />
                <section className="panel">
                  <h3>十问十答（分布研究）</h3>
                  <ol className="muted">
                    <li>直接追涨均值是否由少数赢家贡献：{String(answers["1_chase_mean_from_few_winners"] || "-")}</li>
                    <li>为何跌停率近半：{String(answers["2_chase_high_ld_why"] || "-")}</li>
                    <li>回踩为何跌停更低：{String(answers["3_pullback_low_ld_why"] || "-")}</li>
                    <li>
                      什么样回踩更好：
                      {typeof answers["4_best_pullback_type"] === "object"
                        ? JSON.stringify(answers["4_best_pullback_type"])
                        : String(answers["4_best_pullback_type"] || "-")}
                    </li>
                    <li>再加速为何无优势：{String(answers["5_reaccel_no_edge_why"] || "-")}</li>
                    <li>
                      最佳连板×买点：
                      {typeof answers["6_best_board_entry"] === "object"
                        ? JSON.stringify(answers["6_best_board_entry"])
                        : String(answers["6_best_board_entry"] || "-")}
                    </li>
                    <li>是否继续用再入场分数：{String(answers["7_continue_reentry_score"] || "-")}</li>
                    <li>
                      是否有风险调整优势：
                      {String(answers["8_risk_adjusted_entry_edge"] || "-") === "NO_EDGE_PROVEN"
                        ? "尚未证明"
                        : String(answers["8_risk_adjusted_entry_edge"] || "-")}
                    </li>
                    <li>能否进入参数优化：{zhBool(answers["9_ready_for_param_opt"])}</li>
                    <li>
                      为何可买入为0：
                      {typeof answers["10_why_buy_ready_zero"] === "object"
                        ? ((answers["10_why_buy_ready_zero"] as { reasons?: string[] }).reasons || []).join("；")
                        : String(answers["10_why_buy_ready_zero"] || "-")}
                    </li>
                  </ol>
                </section>
              </>
            ) : null}

            {hp ? (
              <section className="panel">
                <h3>健康回踩实验室</h3>
                <p className="muted">
                  回踩扫描 {String((hp.meta as Record<string, unknown>)?.n_pullback_scans)} · 健康回踩{" "}
                  {String((hp.meta as Record<string, unknown>)?.n_healthy)} · 耗时{" "}
                  {String((hp.meta as Record<string, unknown>)?.elapsed_sec)} 秒 · 大模型 0 · 结论：
                  {String((hp.answers as Record<string, unknown>)?.["10_statistical_edge"]) === "NO_EDGE_PROVEN"
                    ? "尚未证明优势"
                    : String((hp.answers as Record<string, unknown>)?.["10_statistical_edge"] || "-")}
                </p>
                <DistTable title="按健康度" data={hp.by_health as Record<string, DistCell>} />
                <DistTable title="健康回踩按深度" data={hp.by_depth as Record<string, DistCell>} />
                <DistTable title="健康回踩按连板" data={hp.healthy_by_board as Record<string, DistCell>} />
                <DistTable title="立刻买 vs 等再加速" data={hp.path_performance as Record<string, DistCell>} />
                <ul className="muted">
                  <li>
                    扣费后期望：
                    {pct(Number((hp.answers as Record<string, unknown>)?.["1_healthy_pullback_net_ev"]))}
                  </li>
                  <li>
                    路径偏好：
                    {String(
                      ((hp.answers as Record<string, unknown>)?.["5_buy_now_vs_wait_reaccel"] as Record<string, unknown>)
                        ?.prefer || "-"
                    )}
                  </li>
                  <li>
                    最重要健康条件：
                    {String((hp.answers as Record<string, unknown>)?.["6_most_important_health_condition"] || "-")}
                  </li>
                  <li>
                    是否可进入买点候选研究：
                    {zhBool((hp.answers as Record<string, unknown>)?.["9_ready_for_buy_candidate_research"])}
                  </li>
                  <li>滚动验证：{JSON.stringify((hp.answers as Record<string, unknown>)?.["8_walk_forward"])}</li>
                </ul>
              </section>
            ) : (
              <section className="panel">
                <h3>健康回踩实验室</h3>
                <p className="muted">尚未生成。请运行：python scripts/leader_healthy_pullback_lab.py</p>
              </section>
            )}

            <ModeTable title="各买点表现（旧版摘要）" data={data.entry_mode_performance as Record<string, Cell>} />
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
              </ul>
            </section>
          </>
        ) : null}
      </ScrollPane>
    </PageShell>
  );
}
