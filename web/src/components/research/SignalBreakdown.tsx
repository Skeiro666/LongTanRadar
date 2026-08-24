import type { SignalContribution } from "../../types/terminal";

type Props = { items?: SignalContribution[] };

export default function SignalBreakdown({ items }: Props) {
  if (!items?.length) return null;
  return (
    <div className="signal-breakdown">
      <div className="signal-breakdown-label">Signal Contribution (relative, not causal)</div>
      <div className="signal-breakdown-bar">
        {items.map((it) => (
          <div
            key={it.name}
            className="signal-seg"
            style={{ flex: Math.max(it.relative_contribution, 0.02) }}
            title={`${it.name}: ${(it.relative_contribution * 100).toFixed(0)}%`}
          />
        ))}
      </div>
      <div className="signal-breakdown-legend">
        {items.map((it) => (
          <span key={it.name} className="signal-legend-item">
            {it.name} {(it.relative_contribution * 100).toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  );
}
