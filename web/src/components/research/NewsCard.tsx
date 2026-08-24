import { labelDirection } from "../../i18n/zh";

type Props = { news?: Record<string, unknown> | null };

function q(v: unknown) {
  if (v == null) return "—";
  if (typeof v === "number") return v.toFixed(2);
  return String(v);
}

export default function NewsCard({ news }: Props) {
  if (!news) return <p className="muted">无新闻包 — 不代表无利空，见上方新闻覆盖率。</p>;
  const sq = String(news.source_quality || "C").toUpperCase();
  return (
    <div className="news-card compact">
      <div className="news-card-head">
        <span className="badge badge-watch">{String(news.event_type || "事件")}</span>
        <span className={`badge badge-${String(news.direction || "").includes("pos") ? "buy" : "pass"}`}>
          {labelDirection(String(news.direction || ""))}
        </span>
        <span className="badge badge-persona">来源质量 {sq}</span>
      </div>
      <dl className="metrics news-metrics">
        <div className="metric"><dt>重要性</dt><dd>{q(news.importance)}</dd></div>
        <div className="metric"><dt>新颖度</dt><dd>{q(news.novelty)}</dd></div>
        <div className="metric"><dt>市场相关</dt><dd>{q(news.market_relevance)}</dd></div>
        <div className="metric"><dt>影响周期</dt><dd>{q(news.impact_horizon)}</dd></div>
        <div className="metric"><dt>置信度</dt><dd>{q(news.event_confidence)}</dd></div>
      </dl>
      <p className="news-summary">{String(news.summary || "—")}</p>
      <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
        {String(news.media || "—")} · {String(news.published_at || "—").slice(0, 16)}
      </p>
    </div>
  );
}
