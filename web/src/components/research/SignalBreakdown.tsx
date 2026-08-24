import type { SignalContribution } from "../../types/terminal";
import { labelSignal } from "../../i18n/zh";

type Props = { items?: SignalContribution[] };

export default function SignalBreakdown({ items }: Props) {
  if (!items?.length) return null;
  return (
    <div className="signal-breakdown">
      <div className="signal-breakdown-label">信号贡献（相对权重，非因果归因）</div>
      <div className="signal-breakdown-bar">
        {items.map((it) => (
          <div
            key={it.name}
            className="signal-seg"
            style={{ flex: Math.max(it.relative_contribution, 0.02) }}
            title={`${labelSignal(it.name)}: ${(it.relative_contribution * 100).toFixed(0)}%`}
          />
        ))}
      </div>
      <div className="signal-breakdown-legend">
        {items.map((it) => (
          <span key={it.name} className="signal-legend-item">
            {labelSignal(it.name)} {(it.relative_contribution * 100).toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  );
}
