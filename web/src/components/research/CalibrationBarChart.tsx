import { insufficientSample } from "../../i18n/zh";

type Point = {
  bucket?: string;
  sample_count?: number;
  t10_excess_return?: number | null;
  mean?: number | null;
  status?: string;
};

type Props = { title: string; series?: Point[] };

export default function CalibrationBarChart({ title, series }: Props) {
  if (!series?.length) return null;
  const valueOf = (p: Point) => (p.t10_excess_return != null ? p.t10_excess_return : p.mean);
  const valid = series.filter((p) => p.status !== "INSUFFICIENT_SAMPLE" && valueOf(p) != null);
  if (!valid.length) {
    return (
      <div className="calibration-chart">
        <h4>{title}</h4>
        <p className="muted">{insufficientSample()} — 不绘制误导曲线</p>
      </div>
    );
  }
  const maxAbs = Math.max(...valid.map((p) => Math.abs(Number(valueOf(p)))), 0.001);
  return (
    <div className="calibration-chart">
      <h4>{title}</h4>
      <div className="cal-bars">
        {series.map((p) => {
          const raw = valueOf(p);
          const insuf = p.status === "INSUFFICIENT_SAMPLE" || raw == null;
          const v = Number(raw || 0);
          const h = insuf ? 4 : Math.max(4, (Math.abs(v) / maxAbs) * 80);
          return (
            <div key={p.bucket} className="cal-bar-wrap" title={insuf ? `n=${p.sample_count}` : `${(v * 100).toFixed(2)}%`}>
              <div
                className={`cal-bar ${v >= 0 ? "up" : "down"}`}
                style={{ height: `${h}px`, opacity: insuf ? 0.25 : 1 }}
              />
              <span className="cal-label">{p.bucket}</span>
              <span className="muted cal-n">n={p.sample_count ?? 0}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
