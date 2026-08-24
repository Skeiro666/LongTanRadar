import { Link } from "react-router-dom";
import type { CandidateCard } from "../../types/terminal";
import {
  insufficientSample,
  labelDiscovery,
  labelNewsLabel,
  labelPriority,
  labelRating,
  labelRisk,
  labelTradingAction,
} from "../../i18n/zh";
import CouncilCollapse from "./CouncilCollapse";
import NewsCard from "./NewsCard";
import SignalBreakdown from "./SignalBreakdown";

type Props = {
  card: CandidateCard;
  expanded?: boolean;
  onToggle?: () => void;
};

function ratingBadge(r?: string) {
  const u = (r || "WATCH").toUpperCase();
  if (u.includes("STRONG_BUY") || u === "BUY") return "buy";
  if (u === "PASS") return "pass";
  return "watch";
}

export default function CandidateCardView({ card, expanded, onToggle }: Props) {
  const conflict = card.conflict || {};
  const cohort = card.historical_cohort as Record<string, unknown> | null | undefined;
  const hz = (cohort?.horizons || {}) as Record<string, Record<string, unknown>>;

  return (
    <article className="candidate-card">
      <header className="candidate-card-head">
        <div>
          <span className={`badge badge-${ratingBadge(card.research_rating)}`}>
            {labelRating(card.research_rating)}
          </span>
          <strong style={{ marginLeft: "0.4rem" }}>{card.name || card.symbol}</strong>
          <span className="muted"> {card.symbol}</span>
          {card.price != null && <span className="muted"> · ¥{Number(card.price).toFixed(2)}</span>}
        </div>
        <div className="candidate-card-meta">
          <span className="muted">交易动作：{labelTradingAction(card.trading_action)}</span>
          <span className={`badge badge-${card.risk_status === "BLOCKED" ? "pass" : "watch"}`}>
            风控 {labelRisk(card.risk_status)}
          </span>
          {card.research_priority?.level && (
            <span className="badge badge-persona">优先级 {labelPriority(card.research_priority.level)}</span>
          )}
        </div>
      </header>

      <div className="candidate-discovery">
        <span className="badge badge-watch">{labelDiscovery(card.discovery_source)}</span>
        {(card.news_labels || []).map((l) => (
          <span key={l} className="badge badge-buy">{labelNewsLabel(l)}</span>
        ))}
        {card.degraded?.news && (
          <span className="badge badge-pass">新闻降级 {String(card.degraded.reason || "")}</span>
        )}
      </div>

      {Boolean(conflict.news_conflict) && (
        <div className="conflict-banner">
          ⚠ {String(conflict.display || "新闻/量化冲突")} · 分数 {Number(conflict.conflict_score || 0).toFixed(2)}
          {(conflict.reason_labels as string[] | undefined)?.length ? (
            <span className="muted"> — {(conflict.reason_labels as string[]).join("、")}</span>
          ) : null}
        </div>
      )}

      <div className="top-reasons">
        <strong>为什么值得看？</strong>
        <ol>
          {(card.top_reasons || ["—"]).slice(0, expanded ? 10 : 3).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ol>
        {onToggle && (card.top_reasons?.length || 0) > 3 && (
          <button type="button" className="btn btn-ghost" onClick={onToggle}>
            {expanded ? "收起" : "展开全部"}
          </button>
        )}
      </div>

      <SignalBreakdown items={card.signal_contribution} />

      {expanded && (
        <>
          <NewsCard news={card.news} />
          <CouncilCollapse
            roles={card.council_summary}
            rating={card.research_rating}
            tradingAction={card.trading_action}
          />
          {cohort && (
            <div className="historical-cohort">
              <h4>{String(cohort.label || "历史同类信号")}</h4>
              <p className="muted">样本 {String(cohort.sample_count)} · {String(cohort.note || "")}</p>
              <dl className="metrics">
                {["1", "5", "10", "20"].map((h) => {
                  const row = hz[h];
                  if (!row) return null;
                  const insuf = row.status === "INSUFFICIENT_SAMPLE";
                  return (
                    <div key={h} className="metric">
                      <dt>T+{h}</dt>
                      <dd>
                        {insuf
                          ? insufficientSample(Number(row.sample_count))
                          : `超额 ${((Number(row.excess_return_mean) || 0) * 100).toFixed(2)}% · 胜率 ${((Number(row.hit_rate) || 0) * 100).toFixed(0)}%`}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </div>
          )}
          {card.research_id && (
            <Link className="btn btn-ghost" to={`/research/${card.research_id}/${card.symbol}`}>
              打开研究快照 →
            </Link>
          )}
        </>
      )}
    </article>
  );
}
