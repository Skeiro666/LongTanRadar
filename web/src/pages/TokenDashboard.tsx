import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { labelEscalationReason } from "../i18n/zh";
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
    <PageShell title="AI 成本 / Token" subtitle="本地 vs 云端 · 升级漏斗 · 节省统计">
      <ScrollPane>
        {err && <p className="error">{err}</p>}

        <div className="token-hero">
          <div className="token-hero-value">{saved != null ? `${saved}%` : "—"}</div>
          <div className="token-hero-label">云端 Token 节省率</div>
          <p className="muted">
            基线估算 {fmt(data?.baseline_estimated_tokens)} · 实际云端 {fmt(data?.actual_cloud_tokens)} · 节省{" "}
            {fmt(data?.saved_tokens)}
          </p>
        </div>

        <div className="dash-grid-2">
          <div className="persona-panel compact">
            <h3>本地 LLM（新闻）</h3>
            <dl className="metrics">
              <div className="metric"><dt>调用次数</dt><dd>{data?.local?.calls ?? 0}</dd></div>
              <div className="metric"><dt>缓存命中</dt><dd>{data?.local?.cache_hits ?? 0}</dd></div>
              <div className="metric"><dt>输入 Token</dt><dd>{fmt(data?.local?.input_tokens)}</dd></div>
              <div className="metric"><dt>输出 Token</dt><dd>{fmt(data?.local?.output_tokens)}</dd></div>
              <div className="metric"><dt>合计 Token</dt><dd>{fmt(data?.local?.total_tokens)}</dd></div>
            </dl>
          </div>
          <div className="persona-panel compact">
            <h3>云端 LLM（投委会）</h3>
            <dl className="metrics">
              <div className="metric"><dt>调用次数</dt><dd>{data?.cloud?.calls ?? 0}</dd></div>
              <div className="metric"><dt>输入 Token</dt><dd>{fmt(data?.cloud?.input_tokens)}</dd></div>
              <div className="metric"><dt>输出 Token</dt><dd>{fmt(data?.cloud?.output_tokens)}</dd></div>
              <div className="metric"><dt>合计 Token</dt><dd>{fmt(data?.cloud?.total_tokens)}</dd></div>
              <div className="metric"><dt>费用 USD</dt><dd>${Number(data?.cloud?.cost_usd ?? 0).toFixed(2)}</dd></div>
            </dl>
          </div>
        </div>

        {esc && (
          <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
            <h3>云端升级（Escalation）</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              升级率 {(Number(esc.rate || 0) * 100).toFixed(1)}% · {esc.count}/{esc.total_snapshots} 快照
            </p>
            <dl className="metrics">
              {Object.entries(esc.reasons || {}).map(([k, v]) => (
                <div key={k} className="metric"><dt>{labelEscalationReason(k)}</dt><dd>{v}</dd></div>
              ))}
            </dl>
            <p className="muted">{String((esc.funnel || {}).note || "")}</p>
            <p className="muted">
              漏斗：升级 {String((esc.funnel || {}).escalated ?? 0)} → 进投委会{" "}
              {String((esc.funnel || {}).entered_council ?? 0)} → 买入 {String((esc.funnel || {}).final_buy ?? 0)}
            </p>
          </div>
        )}

        <Link className="btn btn-ghost" to="/alpha-lab">← Alpha 实验室</Link>
      </ScrollPane>
    </PageShell>
  );
}
