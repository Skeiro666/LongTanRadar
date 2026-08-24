"""V5.4 Programmatic lab conclusions — no LLM."""

from __future__ import annotations

from typing import Any


def build_lab_summary(pack: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sig = pack.get("signal_attribution") or {}
    min_n = int(sig.get("minimum_sample") or 30)

    def _primary_mean(src: str, h: str = "5") -> tuple[float | None, int]:
        cell = ((sig.get("by_primary_source") or {}).get(src) or {}).get(h) or {}
        if cell.get("insufficient_sample"):
            return None, int(cell.get("sample_count") or 0)
        sel = (cell.get("selection_alpha") or {}).get("mean")
        return (float(sel) if sel is not None else None), int(cell.get("sample_count") or 0)

    for src, label in [("event", "Event"), ("profit", "Profit"), ("quant", "Quant"), ("news", "News")]:
        if src == "profit" and sig.get("profit_data_unavailable"):
            lines.append("Profit Inflection 数据不足 (DATA_UNAVAILABLE)，无法评估 Discovery Alpha。")
            continue
        m, n = _primary_mean(src)
        if n < min_n:
            lines.append(f"{label} Alpha：样本不足 (n={n}，需要 ≥{min_n})。")
        elif m is not None:
            lines.append(f"{label} Primary T+5 Selection α 均值 {m*100:+.2f}% (n={n})。")

    nd = ((sig.get("cohorts") or {}).get("news_discovery") or {}).get("incremental") or {}
    nd5 = nd.get("5") or {}
    if nd5.get("insufficient_sample"):
        lines.append("News Discovery Alpha：样本不足，尚不能确认新闻能否发现新候选。")
    elif nd5.get("incremental_selection_alpha") is not None:
        v = float(nd5["incremental_selection_alpha"])
        lines.append(
            f"News Discovery incremental α T+5 {v*100:+.2f}% "
            f"({'尚不足' if v <= 0 else '有正向信号'})。"
        )

    ab = pack.get("ai_council_ablation") or {}
    if not ab.get("available"):
        lines.append("AI Council Ablation：数据不足 (UNPROVEN)。")
    else:
        h5 = (ab.get("horizons") or {}).get("5") or {}
        incr = h5.get("ai_incremental_alpha")
        st = ab.get("status") or "UNPROVEN"
        if incr is not None:
            lines.append(f"AI Incremental α T+5 {float(incr)*100:+.2f}% · 状态 {st}。")
        else:
            lines.append(f"AI Council Ablation：{st}。")

    te = pack.get("token_efficiency") or {}
    if te.get("available") and te.get("token_reduction_pct") is not None:
        lines.append(
            f"Adaptive Routing 估算节省 Token {te['token_reduction_pct']}% "
            f"(跳过 LOW {te.get('routing_skips', 0)} 次)。"
        )

    if not lines:
        lines.append("暂无足够研究 outcome；请先运行一轮 research。")
    lines.append("以上为程序统计结论，非 LLM 生成；样本量不足时不作长期有效判断。")
    return lines
