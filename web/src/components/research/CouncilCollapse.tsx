import { useState } from "react";

type Role = {
  role: string;
  stance?: string;
  confidence?: number;
  summary?: string;
  expandable?: boolean;
  full?: Record<string, unknown>;
};

type Props = {
  roles?: Role[];
  chairman?: Record<string, unknown> | null;
  rating?: string;
  tradingAction?: string;
};

export default function CouncilCollapse({ roles, chairman, rating, tradingAction }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const ch = chairman || {};
  const chairRating = rating || String(ch.rating || "—");
  const action = tradingAction || String(ch.trading_action || "NONE");

  return (
    <div className="council-collapse">
      <div className="chairman-banner">
        <span className={`badge badge-${chairRating.toLowerCase().includes("buy") ? "buy" : "watch"}`}>
          {chairRating}
        </span>
        <span className="muted">Trading Action: <strong>{action}</strong></span>
        {ch.confidence != null && <span className="muted">Conf {Number(ch.confidence).toFixed(2)}</span>}
      </div>
      {(roles || []).map((r) => (
        <div key={r.role} className="council-row">
          <button type="button" className="council-row-btn" onClick={() => setOpen(open === r.role ? null : r.role)}>
            <strong>{r.role}</strong>
            <span>{String(r.stance || "NEUTRAL").toUpperCase()}</span>
            {r.confidence != null && <span className="muted">· {Number(r.confidence).toFixed(2)}</span>}
            <span className="muted council-one-liner">{r.summary || "—"}</span>
          </button>
          {open === r.role && r.full && (
            <pre className="council-expand">{JSON.stringify(r.full, null, 2)}</pre>
          )}
        </div>
      ))}
    </div>
  );
}
