import { Link } from "react-router-dom";

type ExitSignal = {
  exit_score?: number;
  action?: string;
  confidence?: number;
  expected_return_5d?: number;
  expected_return_10d?: number;
  reason_texts?: string[];
  reasons?: string[];
  exit_types?: string[];
  hold_days?: number;
  unrealized_return?: number;
  max_favorable_return?: number;
  giveback?: number;
  thesis_decay?: { level?: string; thesis_decay?: number; available?: boolean };
};

type Props = {
  symbol: string;
  name?: string;
  price?: number;
  cost?: number;
  shares?: number;
  exit?: ExitSignal | null;
  compact?: boolean;
};

function pct(v?: number | null) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function actionLabel(a?: string) {
  if (a === "EXIT") return "退出";
  if (a === "REDUCE") return "减仓";
  if (a === "HOLD") return "持有";
  return a || "—";
}

export default function ExitScoreCard({ symbol, name, price, cost, shares, exit, compact }: Props) {
  const score = exit?.exit_score;
  const action = exit?.action || "HOLD";
  const reasons = exit?.reason_texts || exit?.reasons || [];

  return (
    <div className="exit-score-card">
      <div className="exit-score-head">
        <div>
          <strong>{name || symbol}</strong>
          <span className="muted"> {symbol}</span>
          {shares != null && <span className="muted"> · {shares} 股</span>}
        </div>
        <span className={`badge badge-${action === "EXIT" ? "pass" : action === "REDUCE" ? "watch" : "buy"}`}>
          {actionLabel(action)}
        </span>
      </div>

      <div className="exit-score-meter">
        <div className="exit-score-value">{score != null ? Math.round(score * 100) : "—"}</div>
        <div className="muted">退出分 / 100</div>
        <div className="exit-bar">
          <div className="exit-bar-fill" style={{ width: `${Math.min(100, (score || 0) * 100)}%` }} />
        </div>
      </div>

      {!compact && (
        <dl className="metrics">
          <div className="metric"><dt>现价</dt><dd>{price != null ? price.toFixed(2) : "—"}</dd></div>
          <div className="metric"><dt>成本</dt><dd>{cost != null ? cost.toFixed(2) : "—"}</dd></div>
          <div className="metric"><dt>浮盈</dt><dd>{pct(exit?.unrealized_return)}</dd></div>
          <div className="metric"><dt>最高浮盈</dt><dd>{pct(exit?.max_favorable_return)}</dd></div>
          <div className="metric"><dt>回吐</dt><dd>{pct(exit?.giveback)}</dd></div>
          <div className="metric"><dt>持有天数</dt><dd>{exit?.hold_days ?? "—"}</dd></div>
          <div className="metric"><dt>预期 T+5</dt><dd>{pct(exit?.expected_return_5d)}</dd></div>
          <div className="metric"><dt>预期 T+10</dt><dd>{pct(exit?.expected_return_10d)}</dd></div>
        </dl>
      )}

      <div className="exit-reasons">
        <strong>Top 退出原因</strong>
        <ol>
          {(reasons.length ? reasons : ["暂无"]).slice(0, 3).map((r) => (
            <li key={String(r)}>{String(r)}</li>
          ))}
        </ol>
      </div>

      {exit?.thesis_decay?.available && (
        <p className="muted" style={{ fontSize: "0.82rem" }}>
          Thesis 衰减：{exit.thesis_decay.level}（{pct(exit.thesis_decay.thesis_decay)}）
        </p>
      )}

      <Link className="btn btn-ghost" to={`/positions/${encodeURIComponent(symbol)}`}>
        持仓 / 退出详情 →
      </Link>
    </div>
  );
}
