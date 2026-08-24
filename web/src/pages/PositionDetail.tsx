import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ExitScoreCard from "../components/exit/ExitScoreCard";
import PositionExitChart from "../components/exit/PositionExitChart";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";
import { api } from "../api";

export default function PositionDetail() {
  const { symbol } = useParams<{ symbol: string }>();
  const [row, setRow] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!symbol) return;
    api
      .exitSymbol(symbol)
      .then(setRow)
      .catch((e) => setErr(String(e)));
  }, [symbol]);

  const exit = row?.exit || {};
  const thesis = exit.thesis_decay || {};

  return (
    <PageShell
      title={`持仓详情 · ${symbol || ""}`}
      subtitle="买入逻辑 / 当前逻辑 / 退出逻辑"
      actions={
        <Link className="btn btn-ghost" to="/positions">
          ← 持仓列表
        </Link>
      }
    >
      <ScrollPane>
        {err && <p className="error">{err}</p>}
        {!row && !err && <p className="muted">加载中…</p>}
        {row && (
          <>
            <ExitScoreCard
              symbol={row.symbol}
              name={row.name}
              price={row.current_price}
              cost={row.cost_price}
              shares={row.shares}
              exit={exit}
            />
            <div className="persona-panel compact" style={{ marginTop: "0.75rem" }}>
              <h3>价格走势</h3>
              <PositionExitChart data={row.chart} height={220} />
            </div>
            <div className="dash-grid-2" style={{ marginTop: "0.75rem" }}>
              <div className="persona-panel compact">
                <h3>买入 Thesis</h3>
                <pre className="council-expand" style={{ maxHeight: 200 }}>
                  {JSON.stringify(thesis.buy_thesis || { note: "未记录买入论点" }, null, 2)}
                </pre>
              </div>
              <div className="persona-panel compact">
                <h3>当前 / 退出 Thesis</h3>
                <p className="muted">衰减等级：{thesis.level || "—"}</p>
                <pre className="council-expand" style={{ maxHeight: 200 }}>
                  {JSON.stringify(
                    {
                      current: thesis.current_thesis,
                      components: thesis.components,
                      exit_reasons: exit.reason_texts,
                      event_state: exit.event_state,
                    },
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>
          </>
        )}
      </ScrollPane>
    </PageShell>
  );
}
