import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, num, pct } from "../api";
import NewsQuantMatrix from "../components/research/NewsQuantMatrix";
import { EquityLineChart, type PnlPoint } from "../components/Charts";
import PageShell from "../components/layout/PageShell";
import PageTabs from "../components/layout/PageTabs";
import ScrollPane from "../components/layout/ScrollPane";
import type { ResearchTerminal } from "../types/terminal";

type AgentState = {
  running?: boolean;
  phase?: string;
  last_error?: string;
  last_result?: {
    proposal?: { rationale?: string; source?: string };
    picks?: {
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
      }[];
      roundtable?: { summary?: string; source?: string };
    };
    roundtable?: { summary?: string; source?: string };
    orders?: { symbol: string; name?: string; ok?: boolean; quantity?: number; message?: string }[];
  };
};

type PnlPayload = {
  equity?: number;
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
  const [tab, setTab] = useState("chart");
  const [chartKey, setChartKey] = useState<"equity" | "pnl_day">("equity");
  const [terminal, setTerminal] = useState<ResearchTerminal | null>(null);

  async function refresh() {
    try {
      await api.health();
      setApiOk(true);
    } catch {
      setApiOk(false);
      return;
    }
    try {
      const [a, p, term] = await Promise.all([api.agent(), api.pnl(), api.researchTerminal().catch(() => null)]);
      setAgent(a);
      setPnl(p);
      setTerminal(term as ResearchTerminal | null);
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

  const dayTone = (pnl?.pnl_day ?? 0) > 0 ? "up" : (pnl?.pnl_day ?? 0) < 0 ? "down" : undefined;
  const totalTone = (pnl?.pnl_total ?? 0) > 0 ? "up" : (pnl?.pnl_total ?? 0) < 0 ? "down" : undefined;
  const rt = agent?.last_result?.roundtable || agent?.last_result?.picks?.roundtable;
  const picks = agent?.last_result?.picks?.picks || [];
  const ratings = terminal?.counts?.ratings || {};
  const buyN = (ratings.BUY || 0) + (ratings.STRONG_BUY || 0);

  return (
    <PageShell
      title="Command · Research Terminal"
      subtitle="Market / Research Status · 模拟盘 · Alpha · 通知"
      actions={
        <>
          <Link className="btn btn-primary" to="/research">
            圆桌研报
          </Link>
          <Link className="btn btn-ink" to="/agent">
            研究循环
          </Link>
          <button className="btn btn-ghost" type="button" onClick={refresh}>
            刷新
          </button>
        </>
      }
      status={
        apiOk === false ? (
          <span className="status error">后端未连接 — python -m ashare.main serve</span>
        ) : apiOk ? (
          <span className="status ok">
            API 已连接
            {agent?.running ? ` · 研究运行中（${agent.phase || "run"}）` : " · 空闲"}
          </span>
        ) : null
      }
      kpis={[
        { label: "权益", value: pnl?.equity != null ? num(pnl.equity, 0) : "—" },
        { label: "今日盈亏", value: pnl?.pnl_day != null ? num(pnl.pnl_day, 2) : "—", tone: dayTone as "up" | "down" | undefined },
        { label: "今日涨跌", value: pnl?.return_day != null ? pct(pnl.return_day) : "—", tone: dayTone as "up" | "down" | undefined },
        { label: "累计盈亏", value: pnl?.pnl_total != null ? num(pnl.pnl_total, 2) : "—", tone: totalTone as "up" | "down" | undefined },
        { label: "累计收益", value: pnl?.return_total != null ? pct(pnl.return_total) : "—", tone: totalTone as "up" | "down" | undefined },
        { label: "持仓", value: pnl?.positions?.length ?? 0, hint: `本金 ${num(pnl?.initial_balance, 0)}` },
      ]}
    >
      {(err || agent?.last_error) && (
        <p className="status error" style={{ margin: "0.5rem 0 0" }}>
          {err}
          {agent?.last_error ? ` · ${agent.last_error}` : ""}
        </p>
      )}

      {terminal && (
        <div className="home-research-strip">
          <div className="home-strip-row">
            <span>BUY {buyN}</span>
            <span>WATCH {ratings.WATCH ?? 0}</span>
            <span>PASS {ratings.PASS ?? 0}</span>
            <span className="muted">News Discovery {terminal.counts?.news_discovery ?? 0}</span>
            <Link to="/research" className="btn btn-ghost">Research →</Link>
            <Link to="/alpha-lab" className="btn btn-ghost">Alpha Lab →</Link>
            <Link to="/token" className="btn btn-ghost">Token →</Link>
          </div>
          {terminal.matrix && (
            <NewsQuantMatrix matrix={terminal.matrix} candidates={terminal.candidates} />
          )}
        </div>
      )}

      <PageTabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "chart", label: "曲线" },
          { id: "positions", label: "持仓", badge: pnl?.positions?.length || undefined },
          { id: "research", label: "结论", badge: picks.length || undefined },
        ]}
      />

      <ScrollPane>
        {tab === "chart" && (
          <div className="panel compact">
            <div className="chart-toggle">
              <button type="button" className={chartKey === "equity" ? "active" : ""} onClick={() => setChartKey("equity")}>
                权益
              </button>
              <button type="button" className={chartKey === "pnl_day" ? "active" : ""} onClick={() => setChartKey("pnl_day")}>
                日盈亏
              </button>
            </div>
            <EquityLineChart
              data={pnl?.curve || []}
              valueKey={chartKey}
              label={chartKey === "equity" ? "权益" : "日盈亏"}
            />
          </div>
        )}

        {tab === "positions" &&
          (pnl?.positions?.length ? (
            <div className="panel compact">
              <table className="persona-table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>代码</th>
                    <th>数量</th>
                    <th>成本</th>
                  </tr>
                </thead>
                <tbody>
                  {pnl.positions.map((p) => (
                    <tr key={p.symbol}>
                      <td style={{ fontWeight: 600 }}>{p.name || "—"}</td>
                      <td className="muted">{p.symbol}</td>
                      <td>{p.shares}</td>
                      <td>{p.cost_price != null ? num(p.cost_price) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">暂无持仓。圆桌给出 buy 且现金够 1 手后会出现。</p>
          ))}

        {tab === "research" && (
          <>
            {rt?.summary && (
              <div className="panel compact" style={{ marginBottom: "0.75rem" }}>
                <h3>投委会纪要</h3>
                <p style={{ margin: 0 }}>{rt.summary}</p>
                <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.85rem" }}>
                  {rt.source || ""}
                </p>
              </div>
            )}
            {picks.length ? (
              <div className="dash-card-grid">
                {picks.map((p) => (
                  <div key={p.symbol} className="pick-card">
                    <div className="pick-card-title">
                      <span className={`badge badge-${p.committee_verdict || "watch"}`}>
                        {(p.committee_verdict || (p.ai_approve ? "buy" : "pass")).toUpperCase()}
                      </span>{" "}
                      {p.name || p.symbol}
                    </div>
                    <p className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.35rem" }}>
                      {p.symbol}
                      {p.close != null ? ` · ${num(p.close)}` : ""}
                      {p.score != null ? ` · ${num(p.score, 3)}` : ""}
                    </p>
                    <p>{p.committee_thesis || p.ai_rationale || p.why || "—"}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                还没有结论。去 <Link to="/research">圆桌研报</Link> 跑一轮。
              </p>
            )}
            {(agent?.last_result?.orders || []).length > 0 && (
              <div className="panel compact" style={{ marginTop: "0.75rem" }}>
                <h3>成交</h3>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(agent?.last_result?.orders || []).map((o, i) => (
                    <li key={i}>
                      {o.name || o.symbol}：{o.ok ? `买入 ${o.quantity || "—"} 股` : o.message || "未成交"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </ScrollPane>
    </PageShell>
  );
}
