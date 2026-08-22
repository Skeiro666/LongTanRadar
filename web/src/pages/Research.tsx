import { useEffect, useState } from "react";
import { api } from "../api";

type ResearchPayload = {
  as_of?: string;
  strategy?: string;
  universe_size?: number;
  scored?: number;
  screen?: { sources?: Record<string, number> };
  pool?: {
    symbol?: string;
    name?: string;
    board_count?: number;
    profit_gap_score?: number;
    event_tags?: string[];
    thesis?: string;
    sources?: string[];
  }[];
  factor_ranks?: {
    symbol?: string;
    name?: string;
    score?: number;
    factors_z?: Record<string, number>;
    why?: string;
  }[];
  picks?: {
    symbol?: string;
    name?: string;
    score?: number;
    committee_verdict?: string;
    committee_thesis?: string;
    committee_risks?: string;
    committee_horizon?: string;
    ai_rationale?: string;
    why?: string;
    research_rating?: string;
    trading_action?: string;
    research_id?: string;
  }[];
  platform_reports?: {
    research_id?: string;
    symbol?: string;
    name?: string;
    rating?: string;
    action?: string;
    candidate_sources?: string[];
    research_hypotheses?: { type?: string; layers?: Record<string, string>; statement?: string }[];
    chairman?: { confidence?: number; base_case?: string; risks?: string[] };
    news?: {
      counts?: { last_24h?: number; last_7d?: number; last_30d?: number };
      net_event_score?: number;
      incomplete?: boolean;
      last_7d?: {
        id?: string;
        title?: string;
        media?: string;
        published_at?: string;
        classification?: string;
        url?: string;
      }[];
      timeline?: {
        event_id?: string;
        event_type?: string;
        direction?: string;
        impact_score?: number;
        title?: string;
        event_time?: string;
        evidence_id?: string;
        source_url?: string;
      }[];
      conflicts?: string[];
      expectation?: { available?: boolean; note?: string };
    };
  }[];
  news_discovery?: {
    available?: boolean;
    news_data_incomplete?: boolean;
    n_news?: number;
    n_events?: number;
    n_candidates?: number;
    n_rejected?: number;
    note?: string;
    news_candidates?: {
      symbol?: string;
      name?: string;
      event_type?: string;
      event_direction?: string;
      event_impact?: number;
      novelty_score?: number | null;
      novelty_available?: boolean;
      confidence?: number;
      source_quality?: string;
      mapping_method?: string;
      status?: string;
      reject_reason?: string;
      reason?: string;
      price_in_risk?: string;
      price_reaction?: { available?: boolean; price_signal?: string; news_signal?: string; note?: string };
      research_hypotheses?: { type?: string; layers?: Record<string, string>; hypothesis?: string }[];
      candidate_source?: string;
    }[];
    rejected?: { symbol?: string; reject_reason?: string; event_type?: string; title?: string }[];
  };
  candidate_union?: {
    n_union?: number;
    n_research?: number;
    universe?: {
      symbol?: string;
      name?: string;
      candidate_sources?: string[];
      candidate_score?: number;
      in_council?: boolean;
      trigger?: { type?: string; reason?: string };
      research_hypotheses?: { type?: string; layers?: Record<string, string> }[];
    }[];
    rejected?: { symbol?: string; reject_reason?: string; candidate_sources?: string[] }[];
  };
  research_outcomes?: {
    available?: boolean;
    horizon?: string;
    n?: number;
    attribution?: {
      by_source_bucket?: Record<string, { n?: number; mean_return?: number; win_rate?: number }>;
      rules?: string[];
    };
    note?: string;
  };
  roundtable?: {
    summary?: string;
    source?: string;
    replay_notes?: string;
    models_used?: { role?: string; model?: string }[];
    chair_model?: string;
    roles?: {
      id?: string;
      name?: string;
      stance?: string;
      confidence?: number;
      model?: string;
      points?: string[];
      challenges?: string[];
      falsify?: string;
    }[];
    debate?: { from?: string; to?: string; point?: string }[];
  };
};

export default function Research() {
  const [data, setData] = useState<ResearchPayload | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await api.researchLatest());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function run() {
    setBusy(true);
    try {
      setData(await api.researchRun({}));
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const rt = data?.roundtable;

  return (
    <section className="section">
      <h2>AI 圆桌研报</h2>
      <p className="lead">
        候选漏斗 → 因子/Leader → 利润断层/事件 → ML 排序辅助 → 六角色圆桌（含空头）→ 主席交叉验证。
        研究评级与交易动作分离；机器发现机会，AI 研究，人做决策。
      </p>
      <div className="cta-row">
        <button className="btn btn-primary" disabled={busy} onClick={run}>
          {busy ? "研究中…" : "跑一轮研究"}
        </button>
        <button className="btn btn-ink" disabled={busy} onClick={load}>
          刷新最新
        </button>
      </div>
      {err && <p className="status error">{err}</p>}

      {data && (
        <>
          <p className="muted" style={{ marginTop: "1rem" }}>
            日期 {data.as_of || "—"} · 策略 {data.strategy || "—"} · 池 {data.universe_size ?? "—"} ·
            打分 {data.scored ?? "—"}
            {data.screen?.sources
              ? ` · 来源 ${Object.entries(data.screen.sources)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(" / ")}`
              : ""}
          </p>

          <div className="panel">
            <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>投委会纪要</h3>
            <p>{rt?.summary || "尚无纪要"}</p>
            <p className="muted">
              来源：{rt?.source || "—"}
              {rt?.chair_model ? ` · 主席模型 ${rt.chair_model}` : ""}
            </p>
            {(rt?.models_used || []).length > 0 && (
              <p className="muted" style={{ fontSize: "0.9rem" }}>
                多模型：
                {(rt?.models_used || []).map((m) => `${m.role}=${m.model}`).join(" · ")}
              </p>
            )}
            {rt?.replay_notes && <p>复盘要点：{rt.replay_notes}</p>}
          </div>

          <div className="role-grid">
            {(rt?.roles || []).map((r) => (
              <div className="panel role-card" key={r.id || r.name}>
                <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>
                  {r.name || r.id}
                  <span className="muted" style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
                    {r.stance || ""}
                    {r.confidence != null ? ` · ${(r.confidence * 100).toFixed(0)}%` : ""}
                  </span>
                </h3>
                <p className="muted" style={{ marginTop: 0, fontSize: "0.85rem" }}>
                  模型 {r.model || "—"}
                </p>
                <ul>
                  {(r.points || []).map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
                {(r.challenges || []).length > 0 && (
                  <p className="muted" style={{ fontSize: "0.9rem" }}>
                    质疑：{(r.challenges || []).join("；")}
                  </p>
                )}
                {r.falsify && (
                  <p style={{ fontSize: "0.9rem" }}>
                    <strong>证伪：</strong>
                    {r.falsify}
                  </p>
                )}
              </div>
            ))}
          </div>

          {(rt?.debate || []).length > 0 && (
            <div className="panel" style={{ marginTop: "1rem" }}>
              <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>交叉盘问</h3>
              <ul>
                {(rt?.debate || []).map((d, i) => (
                  <li key={i}>
                    {d.from} → {d.to}：{d.point}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="panel" style={{ marginTop: "1rem" }}>
            <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>News Discovery</h3>
            <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
              新闻发现并行候选 · 新闻 ≠ BUY · Price-In 仅警告
              {data.news_discovery?.available === false ? " · 本轮发现不可用" : ""}
              {data.news_discovery?.news_data_incomplete ? " · 新闻不完整" : ""}
            </p>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              新闻 {data.news_discovery?.n_news ?? "—"} · 事件 {data.news_discovery?.n_events ?? "—"} · 候选{" "}
              {data.news_discovery?.n_candidates ?? "—"} · 拒绝 {data.news_discovery?.n_rejected ?? "—"}
              {data.candidate_union?.n_union != null
                ? ` · Union ${data.candidate_union.n_union} → Council池 ${data.candidate_union.n_research ?? "—"}`
                : ""}
            </p>
            {(data.news_discovery?.news_candidates || []).length === 0 ? (
              <p className="muted">暂无新闻候选（需跑一轮研究）。</p>
            ) : (
              (data.news_discovery?.news_candidates || []).map((c, i) => {
                const inCouncil = (data.candidate_union?.universe || []).some(
                  (u) => u.symbol === c.symbol && u.in_council
                );
                const hyp =
                  (c.research_hypotheses || [])[0]?.layers?.HYPOTHESIS ||
                  (c.research_hypotheses || [])[0]?.hypothesis ||
                  "";
                const risk = (c.price_in_risk || "UNKNOWN").toUpperCase();
                return (
                  <div key={`${c.symbol}-${c.event_type}-${i}`} className="verdict-row">
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
                      <span
                        className={`badge badge-${
                          risk === "HIGH" ? "pass" : risk === "MEDIUM" ? "watch" : "buy"
                        }`}
                      >
                        Price-In {risk}
                      </span>{" "}
                      {c.name || c.symbol}{" "}
                      <span className="muted" style={{ fontWeight: 400 }}>
                        {c.symbol}
                        {c.event_type ? ` · ${c.event_type}` : ""}
                        {c.event_direction ? ` · ${c.event_direction}` : ""}
                        {inCouncil ? " · 已进 Council" : " · 未进 Council"}
                      </span>
                    </div>
                    <p style={{ margin: "0.35rem 0 0", fontSize: "0.95rem" }}>{c.reason || "—"}</p>
                    <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.85rem" }}>
                      impact {c.event_impact != null ? Number(c.event_impact).toFixed(2) : "—"} · conf{" "}
                      {c.confidence != null ? Number(c.confidence).toFixed(2) : "—"} · 源质{" "}
                      {c.source_quality || "—"} · 映射 {c.mapping_method || "—"} · novelty{" "}
                      {c.novelty_available === false
                        ? "unavailable"
                        : c.novelty_score != null
                          ? Number(c.novelty_score).toFixed(2)
                          : "—"}
                      {c.price_reaction?.available
                        ? ` · 价讯 ${c.price_reaction.news_signal || "—"} / 价动 ${c.price_reaction.price_signal || "—"}`
                        : " · 价反应用不可用"}
                    </p>
                    {hyp && (
                      <p style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
                        <strong>假设：</strong>
                        {hyp}
                      </p>
                    )}
                    {c.reject_reason && (
                      <p className="muted" style={{ fontSize: "0.85rem" }}>
                        reject：{c.reject_reason}
                      </p>
                    )}
                  </div>
                );
              })
            )}
            {(data.candidate_union?.universe || []).some((u) => (u.candidate_sources || []).includes("news")) && (
              <div style={{ marginTop: "0.75rem" }}>
                <strong>Union 含新闻来源</strong>
                {(data.candidate_union?.universe || [])
                  .filter((u) => (u.candidate_sources || []).includes("news"))
                  .map((u) => (
                    <div key={u.symbol} className="muted" style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}>
                      {(u.candidate_sources || []).join("+")} · {u.name || u.symbol} · score{" "}
                      {u.candidate_score != null ? Number(u.candidate_score).toFixed(3) : "—"}
                      {u.in_council ? " · Council" : ""}
                      {u.trigger?.type ? ` · ${u.trigger.type}` : ""}
                    </div>
                  ))}
              </div>
            )}
            {(data.news_discovery?.rejected || []).slice(0, 8).length > 0 && (
              <div style={{ marginTop: "0.75rem" }}>
                <strong>拒绝样例</strong>
                <p className="muted" style={{ fontSize: "0.8rem", margin: "0.25rem 0 0.5rem" }}>
                  {data.news_discovery?.n_candidates === 0
                    ? "本轮快讯多为宏观/海外标题，未命中 6 位代码、公司全称或别名 — 属预期行为，不会交给模型猜股。"
                    : "未映射到具体 A 股的事件（证据不足时不强行入库）。"}
                </p>
                {(data.news_discovery?.rejected || []).slice(0, 8).map((r, i) => {
                  const reason =
                    r.reject_reason === "NOT_ENOUGH_EVIDENCE"
                      ? "无代码/公司名"
                      : r.reject_reason === "INDUSTRY_MAP_UNAVAILABLE"
                        ? "无行业受益映射"
                        : r.reject_reason === "LOW_CONFIDENCE"
                          ? "LLM 低置信"
                          : r.reject_reason || "—";
                  return (
                    <div key={i} className="muted" style={{ fontSize: "0.8rem", marginTop: "0.2rem" }}>
                      <span style={{ color: "var(--ink-soft)" }}>{reason}</span>
                      {r.event_type && r.event_type !== "OTHER" ? ` · ${r.event_type}` : ""}
                      {" · "}
                      {(r.title || r.reason || "—").slice(0, 120)}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {data.research_outcomes?.available && data.research_outcomes.attribution && (
            <div className="panel" style={{ marginTop: "1rem" }}>
              <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>来源归因（描述性）</h3>
              <p className="muted" style={{ marginTop: 0, fontSize: "0.85rem" }}>
                horizon {data.research_outcomes.horizon || "5"} · 样本 {data.research_outcomes.n ?? "—"} ·
                不改交易权重
              </p>
              {Object.entries(data.research_outcomes.attribution.by_source_bucket || {}).map(([k, v]) => (
                <div key={k} className="muted" style={{ fontSize: "0.9rem" }}>
                  {k}：n={v.n ?? 0}
                  {v.mean_return != null ? ` · mean ${(v.mean_return * 100).toFixed(2)}%` : ""}
                  {v.win_rate != null ? ` · win ${(v.win_rate * 100).toFixed(0)}%` : ""}
                </div>
              ))}
            </div>
          )}

          {(data.platform_reports || []).length > 0 && (
            <div className="panel" style={{ marginTop: "1rem" }}>
              <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>平台研报卡片</h3>
              {(data.platform_reports || []).map((r) => (
                <div key={r.research_id || r.symbol} className="verdict-row">
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
                    <span className={`badge badge-${(r.rating || "WATCH").toLowerCase().includes("buy") ? "buy" : "watch"}`}>
                      {(r.rating || "WATCH").toUpperCase()}
                    </span>{" "}
                    {r.name || r.symbol}{" "}
                    <span className="muted" style={{ fontWeight: 400 }}>
                      {r.symbol}
                      {r.action ? ` · 交易动作 ${r.action}` : ""}
                      {(r.candidate_sources || []).length
                        ? ` · 来源 ${(r.candidate_sources || []).join("+")}`
                        : ""}
                      {r.chairman?.confidence != null
                        ? ` · 置信 ${(r.chairman.confidence * 100).toFixed(0)}%`
                        : ""}
                    </span>
                  </div>
                  <p style={{ margin: "0.35rem 0 0" }}>{r.chairman?.base_case || "—"}</p>
                  <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
                    风险：{(r.chairman?.risks || []).join("；") || "—"} · ID {r.research_id || "—"}
                  </p>
                  {r.news && (
                    <div style={{ marginTop: "0.6rem" }}>
                      <strong>新闻与事件</strong>
                      <p className="muted" style={{ margin: "0.2rem 0", fontSize: "0.85rem" }}>
                        24h {r.news.counts?.last_24h ?? "—"} · 7d {r.news.counts?.last_7d ?? "—"} · 30d{" "}
                        {r.news.counts?.last_30d ?? "—"}
                        {r.news.net_event_score != null ? ` · 事件净分 ${r.news.net_event_score.toFixed(2)}` : ""}
                        {r.news.incomplete ? " · 新闻不完整" : ""}
                      </p>
                      {(r.news.conflicts || []).map((c, i) => (
                        <p key={i} className="muted" style={{ fontSize: "0.85rem" }}>
                          冲突：{c}
                        </p>
                      ))}
                      <p className="muted" style={{ fontSize: "0.85rem" }}>
                        预期差：{r.news.expectation?.available ? "有数据" : r.news.expectation?.note || "无一致预期"}
                      </p>
                      {(r.news.last_7d || []).slice(0, 8).map((n) => (
                        <div key={n.id || n.title} style={{ borderBottom: "1px solid var(--line)", padding: "0.35rem 0" }}>
                          <div>
                            {n.published_at || "—"} · {n.title}
                          </div>
                          <div className="muted" style={{ fontSize: "0.8rem" }}>
                            {n.media || "—"} · {n.classification || "OTHER"}
                            {n.url ? (
                              <>
                                {" "}
                                ·{" "}
                                <a href={n.url} target="_blank" rel="noreferrer">
                                  原文
                                </a>
                              </>
                            ) : null}
                          </div>
                        </div>
                      ))}
                      {(r.news.timeline || []).slice(0, 6).map((e) => (
                        <div key={e.event_id} className="muted" style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}>
                          {e.event_time} · {e.event_type} · {e.direction} · impact {e.impact_score} · evidence{" "}
                          {e.evidence_id}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="panel" style={{ marginTop: "1rem" }}>
            <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>标的结论</h3>
            {(data.picks || []).map((p) => (
              <div key={p.symbol} className="verdict-row">
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
                  <span className={`badge badge-${p.committee_verdict || "watch"}`}>
                    {(p.committee_verdict || "watch").toUpperCase()}
                  </span>{" "}
                  {p.name || p.symbol}{" "}
                  <span className="muted" style={{ fontWeight: 400 }}>
                    {p.symbol}
                    {p.score != null ? ` · 因子分 ${p.score.toFixed(3)}` : ""}
                    {p.research_rating ? ` · 研究评级 ${p.research_rating}` : ""}
                    {p.trading_action ? ` · ${p.trading_action}` : ""}
                  </span>
                </div>
                <p style={{ margin: "0.35rem 0 0" }}>{p.committee_thesis || p.ai_rationale || p.why}</p>
                <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
                  风险：{p.committee_risks || "—"} · 窗口：{p.committee_horizon || "T+1"}
                </p>
              </div>
            ))}
          </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
            <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>事件/龙头池（节选）</h3>
            {(data.pool || []).slice(0, 15).map((c) => (
              <div key={c.symbol} style={{ borderBottom: "1px solid var(--line)", padding: "0.45rem 0" }}>
                <strong>{c.name || c.symbol}</strong>{" "}
                <span className="muted">
                  {c.symbol}
                  {c.board_count ? ` · ${c.board_count}板` : ""}
                  {c.profit_gap_score ? ` · 断层${Number(c.profit_gap_score).toFixed(1)}` : ""}
                </span>
                <div className="muted" style={{ fontSize: "0.85rem" }}>
                  {(c.event_tags || []).join(" · ") || c.thesis}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
