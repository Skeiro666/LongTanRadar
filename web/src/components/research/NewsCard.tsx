type Props = { news?: Record<string, unknown> | null };

function q(v: unknown) {
  if (v == null) return "—";
  if (typeof v === "number") return v.toFixed(2);
  return String(v);
}

export default function NewsCard({ news }: Props) {
  if (!news) return <p className="muted">无新闻包 — 不代表无利空，见 Data Coverage。</p>;
  const sq = String(news.source_quality || "C").toUpperCase();
  return (
    <div className="news-card compact">
      <div className="news-card-head">
        <span className="badge badge-watch">{String(news.event_type || "event")}</span>
        <span className={`badge badge-${String(news.direction || "").includes("pos") ? "buy" : "pass"}`}>
          {String(news.direction || "—")}
        </span>
        <span className="badge badge-persona">Source {sq}</span>
      </div>
      <dl className="metrics news-metrics">
        <div className="metric"><dt>Importance</dt><dd>{q(news.importance)}</dd></div>
        <div className="metric"><dt>Novelty</dt><dd>{q(news.novelty)}</dd></div>
        <div className="metric"><dt>Relevance</dt><dd>{q(news.market_relevance)}</dd></div>
        <div className="metric"><dt>Horizon</dt><dd>{q(news.impact_horizon)}</dd></div>
        <div className="metric"><dt>Confidence</dt><dd>{q(news.event_confidence)}</dd></div>
      </dl>
      <p className="news-summary">{String(news.summary || "—")}</p>
      <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
        {String(news.media || "—")} · {String(news.published_at || "—").slice(0, 16)}
      </p>
    </div>
  );
}
