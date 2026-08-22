import { useEffect, useState } from "react";
import { api } from "../api";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";

type ModuleRow = {
  module: string;
  samples: number;
  t5_alpha?: number | null;
  t10_alpha?: number | null;
  t20_alpha?: number | null;
  incremental_alpha?: number | null;
  cost_usd?: number | null;
  efficiency?: number | null;
  status: string;
};

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export default function AlphaLab() {
  const [data, setData] = useState<{ modules?: ModuleRow[]; as_of?: string } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.alphaLab().then(setData).catch((e) => setErr(String(e)));
  }, []);

  const rows = data?.modules || [];

  return (
    <PageShell title="Alpha Lab" subtitle="V5.4 · Ablation · Calibration · Evidence > Opinion">
      <ScrollPane>
        {err && <p className="error">{err}</p>}
        {data?.as_of && <p className="muted">As of {data.as_of}</p>}
        <div className="persona-panel compact">
          <h3>Module Validation</h3>
          {rows.length === 0 ? (
            <p className="muted">跑完一轮研究后显示模块 Alpha 表。</p>
          ) : (
            <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Samples</th>
                  <th>T+5 α</th>
                  <th>T+10 α</th>
                  <th>T+20 α</th>
                  <th>Δ α</th>
                  <th>Cost</th>
                  <th>Efficiency</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.module}>
                    <td>{r.module}</td>
                    <td>{r.samples}</td>
                    <td>{fmtPct(r.t5_alpha)}</td>
                    <td>{fmtPct(r.t10_alpha)}</td>
                    <td>{fmtPct(r.t20_alpha)}</td>
                    <td>{fmtPct(r.incremental_alpha)}</td>
                    <td>{r.cost_usd != null ? `$${Number(r.cost_usd).toFixed(2)}` : "—"}</td>
                    <td>{r.efficiency != null ? r.efficiency.toFixed(2) : "—"}</td>
                    <td>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </ScrollPane>
    </PageShell>
  );
}
