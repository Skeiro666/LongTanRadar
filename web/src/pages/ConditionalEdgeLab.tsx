import { useEffect, useState } from "react";
import { api, pct } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type Cell = {
  n?: number;
  sample_quality?: string;
  t1_net?: number;
  t3_net?: number;
  t5_net?: number;
  win?: number;
  ld?: number;
  mae?: number;
  mdd?: number;
  rar?: number;
};

const TIER_ZH: Record<string, string> = {
  INSUFFICIENT_SAMPLE: "样本不足",
  LOW_SAMPLE: "样本偏少",
  OK: "样本尚可",
  STRONG: "样本充足",
  STRONG_SAMPLE: "样本充足",
};

const STAGE_ZH: Record<string, string> = {
  EARLY: "早期",
  TREND: "趋势",
  ACCELERATION: "加速",
  EXTREME: "极端",
  DISTRIBUTION: "派发",
  BREAKDOWN: "破位",
};

const MODE_ZH: Record<string, string> = {
  DIRECT_CHASE: "直接追涨",
  FIRST_DIVERGENCE: "首次分歧",
  PULLBACK: "回踩",
  REBREAKOUT: "重新突破",
  REACCELERATION: "再加速",
};

function zhKey(k: string) {
  let s = k;
  for (const [en, zh] of Object.entries(STAGE_ZH)) s = s.replaceAll(en, zh);
  for (const [en, zh] of Object.entries(MODE_ZH)) s = s.replaceAll(en, zh);
  s = s.replaceAll("BOARD", "连板").replaceAll("DEPTH", "深度").replaceAll("VOLUME", "量能");
  s = s.replaceAll("STAGE", "阶段").replaceAll("STRUCTURE", "结构");
  return s;
}

function CellTable({ title, cells }: { title: string; cells: Record<string, Cell> }) {
  const entries = Object.entries(cells || {}).filter(([, c]) => c && typeof c.n === "number");
  if (!entries.length) return null;
  return (
    <section className="panel">
      <h3>{title}</h3>
      <table className="data">
        <thead>
          <tr>
            <th>分组</th>
            <th>样本数</th>
            <th>样本质量</th>
            <th>T+1净收益</th>
            <th>T+3净收益</th>
            <th>T+5净收益</th>
            <th>胜率</th>
            <th>跌停率</th>
            <th>MAE</th>
            <th>最大回撤</th>
            <th>风险调整</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, c]) => (
            <tr key={k}>
              <td>{zhKey(k)}</td>
              <td>{c.n}</td>
              <td>{TIER_ZH[String(c.sample_quality)] || c.sample_quality || "—"}</td>
              <td>{pct(c.t1_net)}</td>
              <td>{pct(c.t3_net)}</td>
              <td>{pct(c.t5_net)}</td>
              <td>{pct(c.win)}</td>
              <td>{pct(c.ld)}</td>
              <td>{pct(c.mae)}</td>
              <td>{pct(c.mdd)}</td>
              <td>{pct(c.rar)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">样本数 &lt; 100 即使收益为正，也只能叫研究信号，不能叫优势。</p>
    </section>
  );
}

function prettyCell(c: Record<string, unknown> | null | undefined) {
  if (!c) return "—";
  const name = zhKey(String(c.name || ""));
  const n = c.n;
  const t1 = pct(c.t1_net as number | undefined);
  return `${name} · n=${n} · T+1净 ${t1}`;
}

export default function ConditionalEdgeLab() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .leaderConditionalEdge()
      .then((d) => setData(d))
      .catch((e) => setErr(String(e)));
  }, []);

  const meta = (data?.meta || {}) as Record<string, unknown>;
  const integ = (data?.integrity || {}) as Record<string, unknown>;
  const mine = (data?.mining || {}) as Record<string, unknown>;
  const mt = (mine.multiple_testing || {}) as Record<string, unknown>;
  const pollution = (integ.by_mode_pollution || {}) as Record<string, { n?: number; non_leader?: number; pollution_rate?: number }>;
  const examples = (integ.examples_board0_healthy || []) as Record<string, unknown>[];
  const wf = (mine.walk_forward || []) as Record<string, unknown>[];
  const hopeful = (mine.hopeful_cells_n100 || []) as Record<string, unknown>[];
  const verdict = String(mine.verdict || "");
  const defs = (integ.definitions || {}) as Record<string, string>;

  return (
    <PageShell
      title="条件边挖掘"
      subtitle="先确认龙头样本干净，再问什么条件下回踩才可能有优势。不改买入门槛，不调用大模型。"
      kpis={[
        { label: "原始事件", value: String(integ.total_entry_events ?? meta.raw_events ?? "—") },
        { label: "清洗后龙头事件", value: String(integ.leader_valid_events ?? meta.canonical_events ?? "—") },
        { label: "污染率", value: pct(integ.pollution_rate as number | undefined), tone: "warn" },
        {
          label: "研究判定",
          value: verdict === "CANDIDATE_EDGE" ? "候选优势" : "尚未证明优势",
          tone: verdict === "CANDIDATE_EDGE" ? "ok" : "down",
        },
      ]}
    >
      <ScrollPane>
        {err ? <p className="error">{err}</p> : null}
        {!data ? <p className="muted">加载中…</p> : null}
        {data && data.available === false ? <p className="muted">{String(data.message)}</p> : null}
        {data && data.available !== false ? (
          <>
            <section className="panel">
              <h3>龙头宇宙完整性</h3>
              <ul>
                <li>
                  原始 board=0：{String(integ.board_count_eq_0_raw)} · board≥1：{String(integ.board_count_ge_1_raw)}
                </li>
                <li>
                  破位阶段却标成健康回踩：{String(integ.breakdown_and_healthy_raw)}
                </li>
                <li>
                  从 board=0 修复出真实连板：{String(integ.repaired_peak_board_from_zero)} · 修复后仍为 0：
                  {String(integ.still_board_0_after_repair)}
                </li>
                <li>非龙头已剔除：{String(integ.non_leader_events)}</li>
                <li>买入管线是否修改：否</li>
              </ul>
              <p className="muted">
                当日连板：{defs.board_count_today || "非涨停日为 0"}。龙头波段板数：
                {defs.leader_board_count || "最近一次涨停当天的连续板数"}。
              </p>
              <p>
                board=0 主要出现在<strong>买点验证</strong>样本：非涨停日误用「前一日连板」，前一日不是涨停就是 0。
                统一事件集会回看最近涨停，所以 jsonl 里几乎没有 board=0；但 2 板结束后第 11–12 日仍被旧候选窗收进来，标准集已剔除。
              </p>
            </section>

            <section className="panel">
              <h3>各模式污染率</h3>
              <table className="data">
                <thead>
                  <tr>
                    <th>模式</th>
                    <th>事件数</th>
                    <th>非龙头</th>
                    <th>污染率</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(pollution).map(([m, c]) => (
                    <tr key={m}>
                      <td>{MODE_ZH[m] || m}</td>
                      <td>{c.n}</td>
                      <td>{c.non_leader}</td>
                      <td>{pct(c.pollution_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="panel">
              <h3>旧数据例子：board=0 且健康回踩</h3>
              <table className="data">
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>日期</th>
                    <th>旧板数</th>
                    <th>修复后连板</th>
                    <th>阶段</th>
                    <th>是否进入标准集</th>
                  </tr>
                </thead>
                <tbody>
                  {examples.map((e, i) => (
                    <tr key={i}>
                      <td>{String(e.symbol)}</td>
                      <td>{String(e.date)}</td>
                      <td>{String(e.board_raw)}</td>
                      <td>{String(e.leader_board)}</td>
                      <td>{STAGE_ZH[String(e.stage)] || String(e.stage)}</td>
                      <td>{e.canonical ? "是" : "否"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <CellTable title="健康回踩 × 连板" cells={(mine.by_board || {}) as Record<string, Cell>} />
            <CellTable title="健康回踩 × 回撤深度" cells={(mine.by_depth || {}) as Record<string, Cell>} />
            <CellTable title="健康回踩 × 量能" cells={(mine.by_volume || {}) as Record<string, Cell>} />
            <CellTable title="健康回踩 × 阶段" cells={(mine.by_stage || {}) as Record<string, Cell>} />
            <CellTable title="健康回踩 × 价格结构（仅用当日可知信息）" cells={(mine.by_structure || {}) as Record<string, Cell>} />

            {Object.entries((mine.cross || {}) as Record<string, Record<string, Cell>>).map(([name, grid]) => (
              <CellTable key={name} title={zhKey(name)} cells={grid} />
            ))}

            <section className="panel">
              <h3>多重检验摘要</h3>
              <ul>
                <li>总检验数：{String(mt.total_tests)}</li>
                <li>正收益格子：{String(mt.positive_cells)} · 负收益格子：{String(mt.negative_cells)}</li>
                <li>最好：{prettyCell(mt.best_cell as Record<string, unknown>)}</li>
                <li>次好：{prettyCell(mt.second_best as Record<string, unknown>)}</li>
                <li>中位：{prettyCell(mt.median_cell as Record<string, unknown>)}</li>
              </ul>
              <p className="muted">{String(mt.multiple_testing_warning || "格子很多时，不能只挑最好看的结果。")}</p>
            </section>

            <section className="panel">
              <h3>样本数≥100 且 T+1 净收益&gt;0 且风险调整&gt;0</h3>
              {hopeful.length === 0 ? (
                <p>没有格子同时满足这三项。这是允许的结果，不会因此放宽买入门槛。</p>
              ) : (
                <ul>
                  {hopeful.map((h) => (
                    <li key={String(h.name)}>{prettyCell(h)}</li>
                  ))}
                </ul>
              )}
            </section>

            <section className="panel">
              <h3>滚动验证（训练 / 验证 / 测试）</h3>
              {wf.length === 0 ? (
                <p className="muted">没有足够资格的格子做滚动验证。</p>
              ) : (
                wf.map((w) => {
                  const splits = (w.splits || {}) as Record<string, { n?: number; primary_net_mean?: number; date_start?: string; date_end?: string }>;
                  return (
                    <div key={String(w.cell)}>
                      <h4>{zhKey(String(w.cell))}</h4>
                      <table className="data">
                        <thead>
                          <tr>
                            <th>分段</th>
                            <th>样本数</th>
                            <th>区间</th>
                            <th>T+1净收益</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(["train", "validation", "test"] as const).map((k) => {
                            const label = k === "train" ? "训练" : k === "validation" ? "验证" : "测试";
                            const s = splits[k] || {};
                            return (
                              <tr key={k}>
                                <td>{label}</td>
                                <td>{s.n ?? "—"}</td>
                                <td>
                                  {s.date_start || "—"} → {s.date_end || "—"}
                                </td>
                                <td>{pct(s.primary_net_mean)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  );
                })
              )}
            </section>

            <section className="panel">
              <h3>最终结论</h3>
              <ol>
                <li>清洗后真正龙头事件：{String(integ.leader_valid_events)}</li>
                <li>board=0 是回踩日字段错误，不是买入信号。</li>
                <li>无法证明 2 连板来源的事件已从标准集剔除。</li>
                <li>新闻只作研究备注，不进入买入。</li>
                <li>当前买入管线应保持不变。</li>
              </ol>
            </section>
          </>
        ) : null}
      </ScrollPane>
    </PageShell>
  );
}
