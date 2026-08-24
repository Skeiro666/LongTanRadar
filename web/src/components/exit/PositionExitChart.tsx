type ChartData = {
  dates?: string[];
  price?: number[];
  ma20?: (number | null)[];
  entry?: number | null;
  exit_action?: string;
  exit_score?: number;
};

type Props = { data?: ChartData | null; height?: number };

/** Lightweight SVG price chart — no extra chart library. */
export default function PositionExitChart({ data, height = 180 }: Props) {
  if (!data?.dates?.length || !data.price?.length) {
    return <p className="muted">暂无价格序列</p>;
  }
  const prices = data.price;
  const w = 560;
  const h = height;
  const pad = 16;
  const min = Math.min(...prices, ...(data.ma20 || []).filter((x): x is number => x != null), data.entry || prices[0]);
  const max = Math.max(...prices, ...(data.ma20 || []).filter((x): x is number => x != null), data.entry || prices[0]);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / Math.max(prices.length - 1, 1)) * (w - pad * 2);
  const y = (v: number) => h - pad - ((v - min) / span) * (h - pad * 2);

  const pricePath = prices.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p)}`).join(" ");
  const maPts = (data.ma20 || [])
    .map((v, i) => (v == null ? null : `${i === 0 || data.ma20![i - 1] == null ? "M" : "L"}${x(i)},${y(v)}`))
    .filter(Boolean)
    .join(" ");

  return (
    <div className="position-exit-chart">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={height} role="img" aria-label="持仓价格">
        <path d={pricePath} fill="none" stroke="var(--p-red-glow, #ff6b6b)" strokeWidth="2" />
        {maPts && <path d={maPts} fill="none" stroke="#888" strokeWidth="1.5" strokeDasharray="4 3" />}
        {data.entry != null && (
          <line x1={pad} x2={w - pad} y1={y(data.entry)} y2={y(data.entry)} stroke="#2ecc71" strokeWidth="1" strokeDasharray="6 4" />
        )}
        {data.exit_action && data.exit_action !== "HOLD" && (
          <circle cx={x(prices.length - 1)} cy={y(prices[prices.length - 1])} r="5" fill="#e74c3c" />
        )}
      </svg>
      <div className="muted" style={{ fontSize: "0.75rem" }}>
        红线价格 · 灰虚线 MA20 · 绿虚线成本
        {data.exit_action && data.exit_action !== "HOLD" ? ` · 当前信号 ${data.exit_action}` : ""}
      </div>
    </div>
  );
}
