type Tab = { id: string; label: string; badge?: string | number };

type Props = {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
};

export default function PageTabs({ tabs, active, onChange }: Props) {
  return (
    <nav className="dash-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={active === t.id}
          className={`dash-tab${active === t.id ? " active" : ""}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.badge != null && t.badge !== "" && <span className="dash-tab-badge">{t.badge}</span>}
        </button>
      ))}
    </nav>
  );
}
