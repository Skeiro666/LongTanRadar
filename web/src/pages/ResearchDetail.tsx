import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CandidateCardView from "../components/research/CandidateCardView";
import PageShell from "../components/layout/PageShell";
import ScrollPane from "../components/layout/ScrollPane";
import { api } from "../api";
import type { CandidateCard } from "../types/terminal";

export default function ResearchDetail() {
  const { researchId, symbol } = useParams<{ researchId: string; symbol: string }>();
  const [detail, setDetail] = useState<(CandidateCard & { versions?: Record<string, string>; note?: string }) | null>(
    null
  );
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!researchId || !symbol) return;
    api
      .researchDetail(researchId, symbol)
      .then(setDetail)
      .catch((e) => setErr(String(e)));
  }, [researchId, symbol]);

  const versions = detail?.versions;

  return (
    <PageShell
      title={`研究快照 · ${symbol || ""}`}
      subtitle="当时为什么这么判断？— 冻结快照，非今日重算"
      actions={
        <Link className="btn btn-ghost" to="/research">
          ← 研究终端
        </Link>
      }
    >
      <ScrollPane>
        {err && <p className="error">{err}</p>}
        {!detail && !err && <p className="muted">加载中…</p>}
        {versions && (
          <p className="muted">
            因子 {versions.factor_version} · 新闻 {versions.news_version || "—"} · 提示词{" "}
            {versions.prompt_version || versions.prompt_bundle} · 模型 {versions.model_version || versions.model_bundle}
          </p>
        )}
        {detail && <CandidateCardView card={detail} expanded />}
        {detail?.note && <p className="muted">{detail.note}</p>}
      </ScrollPane>
    </PageShell>
  );
}
