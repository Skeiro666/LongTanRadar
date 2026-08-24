import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type TokenDash = {
  local?: Record<string, number>;
  cloud?: Record<string, number>;
  token_saved_pct?: number;
  cloud_token_saved_pct?: number;
  baseline_estimated_tokens?: number;
  actual_cloud_tokens?: number;
  saved_tokens?: number;
  cloud_escalation?: {
    rate?: number;
    count?: number;
    total_snapshots?: number;
    reasons?: Record<string, number>;
    funnel?: Record<string, unknown>;
  };
};

function fmt(n: number | undefined) {
  if (n == null) return "—";
  return n.toLocaleString();
}

export default function TokenDashboard() {
  const [data, setData] = useState<TokenDash | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.tokenDashboard().then(setData).catch((e) => setErr(String(e)));
  }, []);

  const saved = data?.cloud_token_saved_pct ?? data?.token_saved_pct;
  const esc = data?.cloud_escalation;

  return (
    <PageShell title="AI Cost / Token" subtitle="Local vs Cloud · Escalation Funnel · Savings">
      <ScrollPane>
        {err && <p className="error">{err}</p>}

        <div className="token-hero">
          <div className="token-hero-value">{saved != null ? `${saved}%` : "—"}</div>
          <div className="token-hero-label">Cloud Token Saved</div>
          <p className="muted">
            Baseline est {fmt(data?.baseline_estimated_tokens)} · Actual cloud {fmt(data?.actual_cloud_tokens)} · Saved{" "}
            {fmt(data?.saved_tokens)}
          </p>
        </div>

        <div className="dash-grid-2">
          <div className="persona-panel compact">
            <h3>Local LLM (News)</h3>
            <dl className="metrics">
              <div className="metric"><dt>Calls</dt><dd>{data?.local?.calls ?? 0}</dd></div>
              <div className="metric"><dt>Cache Hit</dt><dd>{data?.local?.cache_hits ?? 0}</dd></div>
              <div className="metric"><dt>Input</dt><dd>{fmt(data?.local?.input_tokens)}</dd></div>
              <div className="metric"><dt>Output</dt><dd>{fmt(data?.local?.output_tokens)}</dd></div>
              <div className="metric"><dt>Total</dt><dd>{fmt(data?.local?.total_tokens)}</dd></div>
            </dl>
          </div>
          <div className="persona-panel compact">
            <h3>Cloud LLM (Council)</h3>
            <dl className="metrics">
              <div className="metric"><dt>Calls</dt><dd>{data?.cloud?.calls ?? 0}</dd></div>
              <div className="metric"><dt>Input</dt><dd>{fmt(data?.cloud?.input_tokens)}</dd></div>
              <div className="metric"><dt>Output</dt><dd>{fmt(data?.cloud?.output_tokens)}</dd></div>
              <div className="metric"><dt>Total</dt><dd>{fmt(data?.cloud?.total_tokens)}</dd></div>
              <div className="metric"><dt>Cost USD</dt><dd>${Number(data?.cloud?.cost_usd ?? 0).toFixed(2)}</dd></div>
            </dl>
          </div>
        </div>

        {esc && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>Cloud Escalation</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              Rate {(Number(esc.rate || 0) * 100).toFixed(1)}% · {esc.count}/{esc.total_snapshots} snapshots
            </p>
            <dl className="metrics">
              {Object.entries(esc.reasons || {}).map(([k, v]) => (
                <div key={k} className="metric"><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
            <p className="muted">{String((esc.funnel || {}).note || "")}</p>
            <p className="muted">
              Funnel: escalated {String((esc.funnel || {}).escalated ?? 0)} → council{" "}
              {String((esc.funnel || {}).entered_council ?? 0)} → BUY {String((esc.funnel || {}).final_buy ?? 0)}
            </p>
          </div>
        )}

        <Link className="btn btn-ghost" to="/alpha-lab">← Alpha Lab</Link>
      </ScrollPane>
    </PageShell>
  );
}
