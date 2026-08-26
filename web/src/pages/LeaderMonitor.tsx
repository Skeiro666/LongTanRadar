import { useEffect, useMemo, useState } from "react";
import { api, num } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type TimelineStep = { event?: string; detail?: string };

type LeaderRow = {
  symbol: string;
  name?: string;
  lifecycle?: string;
  board_count?: number;
  leader_score?: number;
  stage?: string;
  chase_score?: number;
  chase_level?: string;
  trade_timing_score?: number;
  trade_timing_action?: string;
  reentry_score?: number;
  reentry_phase?: string;
  focus_tier?: string;
  entry_timeline?: TimelineStep[];
  news_score?: number;
  risk_status?: string;
  risk_flags?: string[];
  status_reason?: string;
  in_focus_watchlist?: boolean;
  merged_from_focus?: boolean;
  council_rating?: string;
  research_date?: string;
  research_limit_up?: boolean;
  live_price?: number | null;
  live_change_pct?: number | null;
  live_limit_up_price?: number | null;
  live_limit_down_price?: number | null;
  live_is_limit_up?: boolean;
  live_is_limit_down?: boolean;
  live_status?: string;
  live_updated_at?: string | null;
  live_session_open?: boolean;
};

type LeaderMonitorPayload = {
  enabled?: boolean;
  research_only?: boolean;
  positioning?: string;
  message?: string;
  has_buy_ready?: boolean;
  buy_ready_count?: number;
  focus_count?: number;
  as_of?: string;
  research_date?: string;
  buckets?: Record<string, LeaderRow[]>;
  stage_performance?: Record<string, { n?: number; mean_timing?: number | null }>;
  board_performance?: Record<string, { n?: number; mean_leader?: number | null }>;
  focus_stats?: Record<string, number>;
};

const BUCKET_ORDER = ["BUY_READY", "BUY_CANDIDATE", "FOCUS", "WAIT", "DROPPED", "OTHER"] as const;

const BUCKET_ZH: Record<string, string> = {
  BUY_READY: "可买入",
  BUY_CANDIDATE: "买点候选",
  FOCUS: "重点跟踪",
  WAIT: "等待观察",
  DROPPED: "已踢出",
  OTHER: "其他",
};

const STAGE_ZH: Record<string, string> = {
  EARLY: "早期",
  TREND: "趋势",
  ACCELERATION: "加速",
  EXTREME: "极端",
  DISTRIBUTION: "派发",
  BREAKDOWN: "破位",
  UNKNOWN: "未知",
  NA: "无",
};

const CHASE_ZH: Record<string, string> = {
  LOW: "低",
  MEDIUM: "中",
  HIGH: "高",
  EXTREME: "极高",
};

const TIMING_ZH: Record<string, string> = {
  BUY_READY: "可买入",
  BUY_CANDIDATE: "买点候选",
  WAIT: "等待",
  PASS: "放弃",
  NA: "无",
};

const PHASE_ZH: Record<string, string> = {
  NONE: "无",
  WAIT: "等待",
  PULLBACK_WATCH: "回踩观察",
  DIVERGENCE: "分歧",
  STABILIZATION: "企稳",
  REACCELERATION: "再加速",
  BUY_CANDIDATE: "买点候选",
};

const LIFE_ZH: Record<string, string> = {
  NEW_LIMIT_UP: "新涨停",
  LEADER_CANDIDATE: "龙头候选",
  LEADER_CONFIRMED: "确认龙头",
  FOCUS: "重点跟踪",
  BUY_CANDIDATE: "买点候选",
  BUY_READY: "可买入",
  HOLDING: "持仓中",
  EXIT_WATCH: "退出观察",
  DROPPED: "已踢出",
  WAIT: "等待",
  OTHER: "其他",
};

const FOCUS_TIER_ZH: Record<string, string> = {
  WATCH: "观察",
  BUY_CANDIDATE: "买点候选",
  BUY_READY: "可买入",
  FOCUS: "重点",
  PASS: "放弃",
  A: "A",
  B: "B",
  C: "C",
};

const RISK_ZH: Record<string, string> = {
  PASS: "通过",
  FAIL: "未通过",
  WARN: "警告",
  OK: "正常",
  BLOCK: "拦截",
  BLOCKED: "拦截",
  UNKNOWN: "未知",
};

const FOCUS_STAT_ZH: Record<string, string> = {
  promoted: "晋级",
  dropped: "踢出",
  retained: "保留",
  merged_from_focus: "自跟踪列表合并",
  added: "新增",
  kept: "维持",
};

const LIVE_STATUS_ZH: Record<string, string> = {
  LIMIT_UP: "涨停",
  BREAK_LIMIT: "炸板",
  WEAK: "偏弱",
  NORMAL: "正常",
  STALE: "行情数据延迟",
  UNKNOWN: "暂无实时行情",
};

const REASON_TOKEN_ZH: Record<string, string> = {
  WAIT: "等待",
  PASS: "放弃",
  BUY_READY: "可买入",
  BUY_CANDIDATE: "买点候选",
  limit_up_block: "研究日涨停封板，暂不追",
  extreme_wait_need_reentry: "极端阶段，需等再加速",
  extreme_not_chase: "极端阶段，不追高",
  board_lt_2_no_buy: "连板不足2，不可买入",
  stage_breakdown: "结构破位",
  breakout_after_pullback: "回踩后再突破",
  structure_break: "结构破坏",
  risk_fail: "风控未过",
  stale: "跟踪过久无进展",
};

function zhMap(dict: Record<string, string>, raw?: string | null, fallback = "—") {
  if (raw == null || raw === "") return fallback;
  const key = String(raw).toUpperCase();
  return dict[key] || dict[String(raw)] || String(raw);
}

function zhReason(raw?: string | null): string {
  if (!raw) return "";
  return String(raw)
    .split(/[;|]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const eq = part.indexOf("=");
      if (eq > 0) {
        const k = part.slice(0, eq).trim();
        const v = part.slice(eq + 1).trim();
        const kZh =
          {
            stage: "阶段",
            board: "连板",
            chase: "追涨风险",
            reentry: "再入场分",
            phase: "再入场阶段",
            leader: "龙头分",
            timing: "时机分",
          }[k] || k;
        const vZh =
          STAGE_ZH[v.toUpperCase()] ||
          PHASE_ZH[v.toUpperCase()] ||
          TIMING_ZH[v.toUpperCase()] ||
          CHASE_ZH[v.toUpperCase()] ||
          v;
        return `${kZh}=${vZh}`;
      }
      return REASON_TOKEN_ZH[part] || REASON_TOKEN_ZH[part.toUpperCase()] || part;
    })
    .join("；");
}

function zhTimelineEvent(ev?: string): string {
  if (!ev) return "—";
  if (/^\d+板$/.test(ev)) return ev;
  return (
    STAGE_ZH[ev.toUpperCase()] ||
    PHASE_ZH[ev.toUpperCase()] ||
    TIMING_ZH[ev.toUpperCase()] ||
    LIFE_ZH[ev.toUpperCase()] ||
    REASON_TOKEN_ZH[ev] ||
    ev
  );
}

function zhTimelineDetail(detail?: string): string {
  if (!detail) return "";
  if (detail.includes("=") || detail.includes(";")) return zhReason(detail);
  return REASON_TOKEN_ZH[detail] || REASON_TOKEN_ZH[detail.toUpperCase()] || detail;
}

function Tone({ text, tone }: { text: string; tone?: "ok" | "warn" | "down" | "muted" }) {
  const cls =
    tone === "ok"
      ? "badge badge-buy"
      : tone === "warn"
        ? "badge badge-watch"
        : tone === "down"
          ? "badge badge-pass"
          : "badge";
  return <span className={cls}>{text}</span>;
}

function stageTone(stage?: string): "ok" | "warn" | "down" | "muted" {
  const s = String(stage || "").toUpperCase();
  if (s === "TREND" || s === "EARLY") return "ok";
  if (s === "EXTREME" || s === "ACCELERATION") return "warn";
  if (s === "BREAKDOWN" || s === "DISTRIBUTION") return "down";
  return "muted";
}

function timingTone(action?: string): "ok" | "warn" | "down" | "muted" {
  const a = String(action || "").toUpperCase();
  if (a === "BUY_READY") return "ok";
  if (a === "BUY_CANDIDATE") return "warn";
  if (a === "PASS") return "down";
  return "muted";
}

function liveTone(status?: string): "ok" | "warn" | "down" | "muted" {
  const s = String(status || "").toUpperCase();
  if (s === "LIMIT_UP") return "ok";
  if (s === "BREAK_LIMIT" || s === "STALE" || s === "WEAK") return "warn";
  if (s === "UNKNOWN") return "muted";
  return "muted";
}

function formatLiveTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function pctText(v?: number | null): string {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function Timeline({ steps }: { steps?: TimelineStep[] }) {
  if (!steps?.length) return <span className="muted">暂无路径</span>;
  return (
    <ol className="entry-timeline">
      {steps.map((s, i) => (
        <li key={`${s.event}-${i}`}>
          <strong>{zhTimelineEvent(s.event)}</strong>
          {s.detail ? <span className="muted small"> · {zhTimelineDetail(s.detail)}</span> : null}
        </li>
      ))}
    </ol>
  );
}

function LiveStatusLabel({ status }: { status?: string }) {
  const s = String(status || "UNKNOWN").toUpperCase();
  const text = LIVE_STATUS_ZH[s] || s;
  if (s === "LIMIT_UP") return <Tone text={text} tone="ok" />;
  if (s === "BREAK_LIMIT") return <Tone text={text} tone="warn" />;
  if (s === "STALE") return <Tone text={text} tone="warn" />;
  if (s === "WEAK") return <Tone text={text} tone="warn" />;
  return <Tone text={text} tone={liveTone(s)} />;
}

function LeaderCard({ row, highlight }: { row: LeaderRow; highlight?: boolean }) {
  const researchDate = row.research_date || "—";
  const boardLabel = row.board_count != null ? `${row.board_count}板` : "—";
  const hasLivePx = row.live_price != null && Number(row.live_price) > 0;
  const statusUp = String(row.live_status || "").toUpperCase();
  const staleOrUnknown = statusUp === "STALE" || statusUp === "UNKNOWN";

  return (
    <article className={`leader-monitor-card${highlight ? " is-buy-ready" : ""}`}>
      <header className="leader-monitor-card__head">
        <div>
          <strong>{row.name || "—"}</strong>
          <span className="mono muted"> {row.symbol}</span>
        </div>
        <Tone text={zhMap(LIFE_ZH, row.lifecycle)} tone="muted" />
      </header>

      <div className="leader-monitor-card__grid">
        <section className="leader-panel leader-panel--research">
          <h4>研究</h4>
          <div className="kv-list compact-kv">
            <div>
              <span>研究日期</span>
              <span className="mono">{researchDate}</span>
            </div>
            <div>
              <span>研究连板</span>
              <span>{boardLabel}</span>
            </div>
            <div>
              <span>研究涨停</span>
              <span>{row.research_limit_up ? "是（研究日）" : "否 / 未标注"}</span>
            </div>
            <div>
              <span>Leader Score</span>
              <span>{num(row.leader_score, 2)}</span>
            </div>
            <div>
              <span>Focus</span>
              <span>{zhMap(FOCUS_TIER_ZH, row.focus_tier)}</span>
            </div>
            <div>
              <span>阶段</span>
              <span>
                <Tone text={zhMap(STAGE_ZH, row.stage)} tone={stageTone(row.stage)} />
              </span>
            </div>
            <div>
              <span>交易时机</span>
              <span>
                <Tone
                  text={zhMap(TIMING_ZH, row.trade_timing_action)}
                  tone={timingTone(row.trade_timing_action)}
                />
                <span className="muted small"> · {num(row.trade_timing_score, 2)}</span>
              </span>
            </div>
            <div>
              <span>追涨风险</span>
              <span>
                {num(row.chase_score, 2)}
                {row.chase_level ? `（${zhMap(CHASE_ZH, row.chase_level)}）` : ""}
              </span>
            </div>
            <div>
              <span>再入场</span>
              <span>
                {num(row.reentry_score, 2)}
                {row.reentry_phase ? ` / ${zhMap(PHASE_ZH, row.reentry_phase)}` : ""}
              </span>
            </div>
            <div>
              <span>风控</span>
              <span>{zhMap(RISK_ZH, row.risk_status)}</span>
            </div>
          </div>
          {row.status_reason ? (
            <p className="muted small">研究原因：{zhReason(row.status_reason)}</p>
          ) : null}
          <Timeline steps={row.entry_timeline} />
        </section>

        <section className="leader-panel leader-panel--live">
          <h4>今日实时</h4>
          {staleOrUnknown && !hasLivePx ? (
            <div className="live-quote-block">
              <LiveStatusLabel status={row.live_status || "UNKNOWN"} />
              <p className="muted small">最后更新：{formatLiveTime(row.live_updated_at)}</p>
            </div>
          ) : (
            <div className="live-quote-block">
              {hasLivePx && statusUp !== "STALE" ? (
                <>
                  <div className="live-quote-price">
                    <span className="live-px mono">¥{Number(row.live_price).toFixed(2)}</span>
                    <span
                      className={
                        Number(row.live_change_pct || 0) >= 0 ? "live-chg up" : "live-chg down"
                      }
                    >
                      {pctText(row.live_change_pct)}
                    </span>
                  </div>
                  <div className="muted small">
                    涨停价：
                    {row.live_limit_up_price != null
                      ? `¥${Number(row.live_limit_up_price).toFixed(2)}`
                      : "—"}
                  </div>
                </>
              ) : hasLivePx && statusUp === "STALE" ? (
                <p className="muted small">暂不展示可能过期的价格数字</p>
              ) : null}
              <div className="live-status-row">
                <LiveStatusLabel status={row.live_status} />
              </div>
              <p className="muted small">实时更新：{formatLiveTime(row.live_updated_at)}</p>
              {row.live_session_open === false ? (
                <p className="muted small">当前非连续竞价时段（展示缓存/收盘附近行情）</p>
              ) : null}
            </div>
          )}
        </section>
      </div>
    </article>
  );
}

function RowCards({ rows, highlight }: { rows: LeaderRow[]; highlight?: boolean }) {
  if (!rows.length) return <p className="muted">本分栏暂无标的</p>;
  return (
    <div className="leader-monitor-grid">
      {rows.map((r) => (
        <LeaderCard key={r.symbol} row={r} highlight={highlight} />
      ))}
    </div>
  );
}

export default function LeaderMonitor() {
  const [data, setData] = useState<LeaderMonitorPayload | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const pack = await api.leaderMonitor();
      setData(pack);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const buckets = data?.buckets || {};
  const sortedBuckets = useMemo(() => {
    const out: Record<string, LeaderRow[]> = {};
    for (const key of BUCKET_ORDER) {
      const rows = [...(buckets[key] || [])];
      rows.sort((a, b) => Number(b.leader_score || 0) - Number(a.leader_score || 0));
      out[key] = rows;
    }
    return out;
  }, [buckets]);

  const researchDate = data?.research_date || data?.as_of;
  const subtitle = researchDate
    ? `研究日期 ${researchDate} · 今日实时为盘中叠加（不改研究快照 · 不自动下单）`
    : "研究快照 + 今日实时叠加（不自动下单）";

  return (
    <PageShell
      title="龙头监控"
      subtitle={subtitle}
      actions={
        <button type="button" className="btn btn-ghost" onClick={load}>
          刷新
        </button>
      }
      kpis={[
        {
          label: "可买入",
          value: String(data?.buy_ready_count ?? 0),
          hint: data?.has_buy_ready ? "已有满足条件标的" : "当前无满足条件",
          tone: data?.has_buy_ready ? "ok" : "warn",
        },
        {
          label: "跟踪池",
          value: String(data?.focus_count ?? 0),
          hint: "重点跟踪 + 买点候选 + 可买入",
        },
        {
          label: "等待观察",
          value: String((sortedBuckets.WAIT || []).length),
          hint: "多为极端阶段暂不追",
        },
        {
          label: "模式",
          value: data?.research_only === false ? "交易模式" : "研究模式",
          hint: data?.enabled === false ? "龙头管线已关闭" : "参数冻结，不降买入门槛",
        },
      ]}
      status={
        <div className="dash-status-line">
          <strong>{data?.message || "加载中…"}</strong>
          <span className="muted">
            {data?.has_buy_ready
              ? ` · 可买入 ${data?.buy_ready_count ?? 0} 只`
              : " · 暂无「可买入」标的"}
            {` · 跟踪 ${data?.focus_count ?? 0} 只`}
            {researchDate ? ` · 研究 ${researchDate}` : ""}
          </span>
        </div>
      }
    >
      {err ? <div className="banner error">{err}</div> : null}

      <div className="card-grid">
        <div className="card">
          <h3>跟踪列表变动</h3>
          {Object.keys(data?.focus_stats || {}).length ? (
            <ul className="kv-list">
              {Object.entries(data?.focus_stats || {}).map(([k, v]) => (
                <li key={k}>
                  <span>{FOCUS_STAT_ZH[k] || k}</span>
                  <span>{v}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">暂无统计（跑完研究流水线后更新）</p>
          )}
        </div>
        <div className="card">
          <h3>阅读说明</h3>
          <ul className="muted small tight">
            <li>
              <strong>研究</strong>来自日频快照（含连板），不会被盘中行情改写。
            </li>
            <li>
              <strong>今日实时</strong>来自新浪行情批量叠加，约 15 秒刷新；炸板 ≠ 研究连板失效。
            </li>
            <li>阶段「极端」默认等待，不直接追涨停；「可买入」门槛未降低。</li>
          </ul>
        </div>
      </div>

      <ScrollPane>
        {BUCKET_ORDER.map((key) => {
          const rows = sortedBuckets[key] || [];
          if (key === "OTHER" && !rows.length) return null;
          return (
            <section key={key} className="section-block">
              <h2>
                {BUCKET_ZH[key] || key}
                <span className="badge">{rows.length}</span>
              </h2>
              <RowCards rows={rows} highlight={key === "BUY_READY"} />
            </section>
          );
        })}

        <section className="section-block">
          <h2>阶段分布（当前研究样本）</h2>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>阶段</th>
                <th>样本数</th>
                <th>平均时机分</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data?.stage_performance || {}).length ? (
                Object.entries(data?.stage_performance || {}).map(([st, v]) => (
                  <tr key={st}>
                    <td>{zhMap(STAGE_ZH, st)}</td>
                    <td>{v.n ?? 0}</td>
                    <td>{num(v.mean_timing ?? undefined, 3)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="muted">
                    暂无
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="section-block">
          <h2>连板分布（研究口径）</h2>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>连板</th>
                <th>样本数</th>
                <th>平均龙头分</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data?.board_performance || {}).length ? (
                Object.entries(data?.board_performance || {}).map(([b, v]) => (
                  <tr key={b}>
                    <td>{String(b).endsWith("+") ? `${b}板` : `${b}板`}</td>
                    <td>{v.n ?? 0}</td>
                    <td>{num(v.mean_leader ?? undefined, 3)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="muted">
                    暂无
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </ScrollPane>
    </PageShell>
  );
}
