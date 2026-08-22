import type { ReactNode } from "react";

type Kpi = { label: string; value: ReactNode; hint?: string; tone?: "up" | "down" | "warn" | "ok" };

type Props = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  kpis?: Kpi[];
  status?: ReactNode;
  children: ReactNode;
};

export default function PageShell({ title, subtitle, actions, kpis, status, children }: Props) {
  return (
    <div className="dash-viewport">
      <header className="dash-header">
        <div className="dash-header-top">
          <div>
            <h1 className="dash-title">{title}</h1>
            {subtitle && <p className="dash-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="dash-actions">{actions}</div>}
        </div>
        {status && <div className="dash-status">{status}</div>}
        {kpis && kpis.length > 0 && (
          <div className="kpi-strip">
            {kpis.map((k) => (
              <div key={k.label} className={`kpi-card${k.tone ? ` kpi-${k.tone}` : ""}`}>
                <div className="kpi-label">{k.label}</div>
                <div className="kpi-value">{k.value}</div>
                {k.hint && <div className="kpi-hint">{k.hint}</div>}
              </div>
            ))}
          </div>
        )}
      </header>
      <div className="dash-body">{children}</div>
    </div>
  );

}
