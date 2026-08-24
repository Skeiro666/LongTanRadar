import { Link } from "react-router-dom";
import type { CandidateCard } from "../../types/terminal";
import { MATRIX_QUADS } from "../../i18n/zh";

type Props = {
  matrix?: Record<string, string[]>;
  candidates?: CandidateCard[];
  onSelect?: (c: CandidateCard) => void;
};

export default function NewsQuantMatrix({ matrix, candidates, onSelect }: Props) {
  const bySym = Object.fromEntries((candidates || []).map((c) => [c.symbol, c]));
  return (
    <div className="news-quant-matrix">
      {MATRIX_QUADS.map(({ key, title }) => {
        const syms = matrix?.[key] || [];
        return (
          <div key={key} className="matrix-cell">
            <h4>{title}</h4>
            <span className="muted">{syms.length} 只</span>
            <div className="matrix-symbols">
              {syms.slice(0, 8).map((sym) => {
                const c = bySym[sym];
                const rid = c?.research_id;
                if (rid && onSelect && c) {
                  return (
                    <button key={sym} type="button" className="matrix-link" onClick={() => onSelect(c)}>
                      {c.name || sym}
                    </button>
                  );
                }
                if (rid) {
                  return (
                    <Link key={sym} className="matrix-link" to={`/research/${rid}/${sym}`}>
                      {bySym[sym]?.name || sym}
                    </Link>
                  );
                }
                return (
                  <span key={sym} className="matrix-link muted">
                    {bySym[sym]?.name || sym}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
