import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type PnlPoint = {
  date: string;
  equity: number;
  pnl_day?: number;
  pnl_total?: number;
};

export function EquityLineChart({
  data,
  valueKey = "equity",
  label = "权益",
}: {
  data: PnlPoint[];
  valueKey?: "equity" | "pnl_day" | "pnl_total";
  label?: string;
}) {
  if (!data?.length) {
    return <p className="muted">暂无曲线数据，等 AI 跑完一轮或刷新总览。</p>;
  }
  const rows = data.map((p) => ({
    date: p.date,
    value: Number(p[valueKey] ?? 0),
  }));
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.08)" strokeDasharray="3 6" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#a8a8a8" }} minTickGap={32} />
          <YAxis tick={{ fontSize: 11, fill: "#a8a8a8" }} width={64} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(v: number) => [Number(v).toFixed(2), label]}
            contentStyle={{
              background: "#121212",
              border: "1px solid rgba(230,0,18,0.45)",
              borderRadius: 0,
              color: "#f5f5f5",
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={valueKey === "pnl_day" ? "#ffb347" : "#ff2244"}
            strokeWidth={2}
            dot={{ r: 3 }}
            isAnimationActive
            animationDuration={700}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
