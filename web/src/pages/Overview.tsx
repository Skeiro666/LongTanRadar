import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, num, pct } from "../api";
import { EquityLineChart, type PnlPoint } from "../components/Charts";

type AgentState = {
  running?: boolean;
  phase?: string;
  cycle?: number;
  last_error?: string;
  last_result?: {
    proposal?: { rationale?: string; source?: string };
    picks?: {
      strategy?: string;
      picks?: {
        symbol: string;
        name?: string;
        score?: number;
        committee_verdict?: string;
        committee_thesis?: string;
        why?: string;
        ai_approve?: boolean;
        ai_rationale?: string;
        close?: number;
        weight?: number;
      }[];
      roundtable?: { summary?: string; source?: string };
    };
    roundtable?: { summary?: string; source?: string };
    ai_review?: {
      summary?: string;
      source?: string;
      reviews?: {
        symbol?: string;
        name?: string;
        ai_approve?: boolean;
        ai_confidence?: number;
        ai_rationale?: string;
        committee_verdict?: string;
      }[];
    };
    orders?: { symbol: string; name?: string; ok?: boolean; quantity?: number; message?: string }[];
    metrics?: { equity?: number; paper_return?: number };
  };
};

type PnlPayload = {
  equity?: number;
  cash?: number;
  pnl_day?: number;
  pnl_total?: number;
  return_day?: number;
  return_total?: number;
  initial_balance?: number;
  curve?: PnlPoint[];
  positions?: { symbol: string; name?: string; shares: number; cost_price?: number }[];
};

export default function Overview() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [agent, setAgent] = useState<AgentState | null>(null);
  const [pnl, setPnl] = useState<PnlPayload | null>(null);
  const [err, setErr] = useState("");

  async function refresh() {
    try {
      await api.health();
      setApiOk(true);
    } catch {
      setApiOk(false);
      return;
    }
    try {
      const [a, p] = await Promise.all([api.agent(), api.pnl()]);
      setAgent(a);
      setPnl(p);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, []);

  const dayColor =
    (pnl?.pnl_day ?? 0) > 0 ? "#c62828" : (pnl?.pnl_day ?? 0) < 0 ? "#0f7a4a" : undefined;
  const totalColor =
    (pnl?.pnl_total ?? 0) > 0 ? "#c62828" : (pnl?.pnl_total ?? 0) < 0 ? "#0f7a4a" : undefined;
  const rt = agent?.last_result?.roundtable || agent?.last_result?.picks?.roundtable;

  return (
    <>
      <section className="hero">
        <div className="hero-inner">
          <h1>龙头股研究系统</h1>
          <p>因子库 + 利润断层/事件池 + AI 投委会圆桌。这里看盈亏；研报细节在「圆桌研报」。</p>
          <div className="cta-row">
            <Link className="btn btn-primary" to="/research">
              圆桌研报
            </Link>
            <Link className="btn btn-ink" to="/agent">
              研究循环
            </Link>
            <button className="btn btn-ghost" type="button" onClick={refresh}>
              刷新盈亏
            </button>
          </div>
          {apiOk === false && (
            <p className="status error" style={{ marginTop: "1rem" }}>
              后端未连接：python -m ashare.main serve
            </p>
          )}
          {apiOk && (
            <p className="status ok" style={{ marginTop: "1rem" }}>
              API 已连接
              {agent?.running ? ` · 研究运行中（${agent.phase || "run"}）` : " · 已停止"}
            </p>
          )}
        </div>
      </section>

      <section className="section">
        <h2>每日盈亏</h2>
        <p className="lead">
          模拟盘盯市：累计盈亏相对本金 {num(pnl?.initial_balance, 0)} 元；仅投委会判定 buy 的标的才会尝试买入。
        </p>
        {err && <p className="status error">{err}</p>}
        {agent?.last_error && <p className="status error">{agent.last_error}</p>}
        <dl className="metrics">
          <div className="metric">
            <dt>当前权益</dt>
            <dd>{pnl?.equity != null ? num(pnl.equity, 0) : "—"}</dd>
          </div>
          <div className="metric">
            <dt>今日盈亏</dt>
            <dd style={{ color: dayColor }}>{pnl?.pnl_day != null ? num(pnl.pnl_day, 2) : "—"}</dd>
          </div>
          <div className="metric">
            <dt>今日涨跌</dt>
            <dd style={{ color: dayColor }}>{pnl?.return_day != null ? pct(pnl.return_day) : "—"}</dd>
          </div>
          <div className="metric">
            <dt>累计盈亏</dt>
            <dd style={{ color: totalColor }}>{pnl?.pnl_total != null ? num(pnl.pnl_total, 2) : "—"}</dd>
          </div>
          <div className="metric">
            <dt>累计收益</dt>
            <dd style={{ color: totalColor }}>{pnl?.return_total != null ? pct(pnl.return_total) : "—"}</dd>
          </div>
        </dl>

        <div className="panel">
          <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>权益折线</h3>
          <EquityLineChart data={pnl?.curve || []} valueKey="equity" label="权益" />
        </div>
        <div className="panel" style={{ marginTop: "1rem" }}>
          <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>每日盈亏折线</h3>
          <EquityLineChart data={pnl?.curve || []} valueKey="pnl_day" label="日盈亏" />
        </div>
      </section>

      <section className="section">
        <h2>当前持仓</h2>
        {pnl?.positions?.length ? (
          <div className="panel">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid var(--line)" }}>
                  <th>名称</th>
                  <th>代码</th>
                  <th>数量</th>
                  <th>成本</th>
                </tr>
              </thead>
              <tbody>
                {pnl.positions.map((p) => (
                  <tr key={p.symbol} style={{ borderBottom: "1px solid var(--line)" }}>
                    <td style={{ padding: "0.5rem 0", fontWeight: 600 }}>{p.name || "—"}</td>
                    <td className="muted">{p.symbol}</td>
                    <td>{p.shares}</td>
                    <td>{p.cost_price != null ? num(p.cost_price) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">暂无持仓。等圆桌给出 buy 且现金够 1 手后会出现。</p>
        )}
      </section>

      <section className="section">
        <h2>最新研究结论</h2>
        <p className="lead">事件池筛出龙头候选，因子库排序后由 AI 投委会交叉论证；buy / watch / pass 可复盘。</p>
        {rt?.summary && (
          <div className="panel" style={{ marginBottom: "1rem" }}>
            <p style={{ marginTop: 0, fontFamily: "var(--font-display)", fontWeight: 600 }}>
              投委会纪要
              <span className="muted" style={{ fontWeight: 400, marginLeft: "0.5rem", fontFamily: "var(--font-body)" }}>
                {rt.source || ""}
              </span>
            </p>
            <p>{rt.summary}</p>
          </div>
        )}
        {(agent?.last_result?.picks?.picks || []).length ? (
          <div className="panel">
            {(agent?.last_result?.picks?.picks || []).map((p) => (
              <div key={p.symbol} style={{ borderBottom: "1px solid var(--line)", padding: "0.75rem 0" }}>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
                  <span className={`badge badge-${p.committee_verdict || "watch"}`}>
                    {(p.committee_verdict || (p.ai_approve ? "buy" : "pass")).toUpperCase()}
                  </span>{" "}
                  {p.name || p.symbol}{" "}
                  <span className="muted" style={{ fontWeight: 400, fontFamily: "var(--font-body)" }}>
                    {p.symbol}
                    {p.close != null ? ` · 参考价 ${num(p.close)}` : ""}
                    {p.score != null ? ` · 因子分 ${num(p.score, 3)}` : ""}
                  </span>
                </div>
                <p style={{ margin: "0.35rem 0 0" }}>{p.committee_thesis || p.ai_rationale || p.why || "—"}</p>
              </div>
            ))}
            {(agent?.last_result?.orders || []).length > 0 && (
              <div style={{ marginTop: "0.75rem" }}>
                <p className="muted" style={{ marginBottom: "0.35rem" }}>
                  成交结果
                </p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(agent?.last_result?.orders || []).map((o, i) => (
                    <li key={i}>
                      {o.name || o.symbol}：{o.ok ? `买入 ${o.quantity || "—"} 股` : o.message || "未成交"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="muted">
            还没有研报结论。打开 <Link to="/research">圆桌研报</Link> 跑一轮，或等研究循环写入。
          </p>
        )}
        {agent?.last_result?.proposal?.rationale && (
          <div className="panel" style={{ marginTop: "1rem" }}>
            <h3 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>参数层说明</h3>
            <p>{agent.last_result.proposal.rationale}</p>
          </div>
        )}
      </section>
    </>
  );
}
