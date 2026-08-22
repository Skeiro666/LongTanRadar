import type { RoundtableData } from "../../types/research";

const STANCE_LABEL: Record<string, string> = {
  bull: "看多",
  bear: "看空",
  neutral: "中性",
  watch: "观察",
};

function stanceLabel(s?: string) {
  if (!s) return "";
  return STANCE_LABEL[s.toLowerCase()] || s;
}

function bubbleSide(idx: number, id?: string): "left" | "right" | "chair" {
  if (id === "chair") return "chair";
  return idx % 2 === 0 ? "left" : "right";
}

type Props = {
  roundtable?: RoundtableData | null;
  compact?: boolean;
};

export default function RoundtableTheater({ roundtable: rt, compact = false }: Props) {
  if (!rt) {
    return (
      <div className="persona-panel compact">
        <h3>圆桌</h3>
        <p className="persona-muted">跑完一轮研究后，多角色辩论与主席总结会出现在这里。</p>
      </div>
    );
  }
  const roles = rt.roles || [];

  return (
    <div className={`persona-panel${compact ? " compact flush" : ""}`}>
      <div className="persona-panel-body">
        {!compact && <h3>圆桌对话 · ROUNDTABLE</h3>}
        {compact && <h3>圆桌</h3>}
        <p className="persona-muted" style={{ marginTop: 0 }}>
          Benchmark · {rt.source || "—"}
          {rt.chair_model ? ` · 主席 ${rt.chair_model}` : ""}
        </p>

        {rt.summary && <div className="persona-summary">{rt.summary}</div>}

        {(rt.models_used || []).length > 0 && (
          <p className="persona-muted" style={{ fontSize: "0.82rem" }}>
            {(rt.models_used || []).map((m) => `${m.role}=${m.model}`).join(" · ")}
          </p>
        )}

        <div className="persona-chat-scroll">
          {roles.map((r, i) => (
            <div key={r.id || r.name || i} className={`persona-bubble ${bubbleSide(i, r.id)}`}>
              <div className="persona-bubble-head">
                <span className="persona-bubble-name">{r.name || r.id}</span>
                <span className="persona-bubble-meta">
                  {stanceLabel(r.stance)}
                  {r.confidence != null ? ` · ${(r.confidence * 100).toFixed(0)}%` : ""}
                </span>
              </div>
              <div className="persona-bubble-meta">模型 {r.model || "—"}</div>
              {(r.points || []).length > 0 && (
                <ul>
                  {(r.points || []).map((p, j) => (
                    <li key={j}>{p}</li>
                  ))}
                </ul>
              )}
              {(r.challenges || []).length > 0 && (
                <p className="persona-muted" style={{ margin: "0.4rem 0 0", fontSize: "0.85rem" }}>
                  质疑：{(r.challenges || []).join("；")}
                </p>
              )}
              {r.falsify && (
                <p style={{ margin: "0.4rem 0 0", fontSize: "0.88rem" }}>
                  <strong style={{ color: "var(--p-red-glow)" }}>证伪：</strong>
                  {r.falsify}
                </p>
              )}
            </div>
          ))}
        </div>

        {!compact && (rt.debate || []).length > 0 && (
          <div style={{ marginTop: "0.75rem", flexShrink: 0 }}>
            <div className="persona-muted" style={{ marginBottom: "0.5rem" }}>
              交叉盘问
            </div>
            {(rt.debate || []).map((d, i) => (
              <div key={i} className="persona-debate">
                {(d.from || d.from_role) && (d.to || d.to_role) ? (
                  <>
                    <strong>{d.from || d.from_role}</strong> → <strong>{d.to || d.to_role}</strong>
                    <br />
                  </>
                ) : null}
                {d.point || d.rebuttal}
              </div>
            ))}
          </div>
        )}

        {!compact && rt.replay_notes && (
          <p className="persona-muted" style={{ marginTop: "0.75rem", flexShrink: 0 }}>
            复盘：{rt.replay_notes}
          </p>
        )}
      </div>
    </div>
  );
}
