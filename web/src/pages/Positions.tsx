import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ExitScoreCard from "../components/exit/ExitScoreCard";
import PositionExitChart from "../components/exit/PositionExitChart";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";
import { api } from "../api";

export default function Positions() {
  const [data, setData] = useState<Record<string, any> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .exitBook()
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  const positions = data?.positions || [];
  const charts = data?.charts || {};
  const counts = data?.counts || {};

  return (
    <PageShell
      title="持仓 / 退出"
      subtitle="Exit Engine 只输出信号，不自动下单 · HOLD / REDUCE / EXIT"
      actions={
        <button className="btn btn-ghost" type="button" onClick={() => api.exitBook().then(setData)}>
          刷新
        </button>
      }
      kpis={[
        { label: "持仓", value: positions.length },
        { label: "持有", value: counts.HOLD ?? 0 },
        { label: "减仓", value: counts.REDUCE ?? 0 },
        { label: "退出", value: counts.EXIT ?? 0 },
      ]}
    >
      <ScrollPane>
        {err && <p className="error">{err}</p>}
        <p className="muted">{data?.note}</p>

        {positions.length === 0 ? (
          <p className="muted">暂无纸面持仓。买入后将显示退出分与原因。</p>
        ) : (
          <div className="positions-grid">
            {positions.map((p: any) => (
              <div key={p.symbol} className="persona-panel compact">
                <ExitScoreCard
                  symbol={p.symbol}
                  name={p.name}
                  price={p.current_price}
                  cost={p.cost_price}
                  shares={p.shares}
                  exit={p.exit}
                />
                <PositionExitChart data={charts[p.symbol]} />
              </div>
            ))}
          </div>
        )}

        <Link className="btn btn-ghost" to="/alpha-lab">
          Exit 表现见 Alpha 实验室 →
        </Link>
      </ScrollPane>
    </PageShell>
  );
}
