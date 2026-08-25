#!/usr/bin/env python3
"""
Expand leader history cache toward 3000+ EntryEvents.

EM stock_zt_pool_em currently returns empty — discovery falls back to:
  HS300 + ZZ500 + ZZ1000 + filtered A-share main board.
Limit-up universe is rebuilt from daily bars (as-of), not today's pool.

Incremental daily-bar download (skip existing parquet) → rebuild dataset.
No BUY / LLM / ML / param changes.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.data.akshare_source import fetch_many
from ashare.data.store import ParquetStore
from ashare.leader.entry_event_dataset import build_unified_dataset
from ashare.leader.historical_limit_up import rebuild_daily_limit_up_index
from ashare.symbols import to_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("expand_history")


def _allowed_symbol(sym: str) -> bool:
    s = to_symbol(sym)
    code, ex = s.split(".")
    if ex == "BJ":
        return False
    if code.startswith("688"):  # KCB
        return False
    if code.startswith("300") or code.startswith("301"):  # CYB
        return False
    return True


def _code_to_sym(code: str) -> str | None:
    raw = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)
    if len(raw) != 6:
        return None
    if raw.startswith(("4", "8")):
        return None
    if raw.startswith(("6", "9")):
        return f"{raw}.SH"
    return f"{raw}.SZ"


def index_constituents() -> list[str]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare import failed: %s", exc)
        return []
    out: list[str] = []
    for idx in ("000300", "000905", "000852"):
        try:
            df = ak.index_stock_cons_csindex(symbol=idx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("index %s failed: %s", idx, exc)
            continue
        # Prefer 成分券代码 — avoid matching 指数代码 first.
        code_col = None
        for c in df.columns:
            s = str(c)
            if "成分" in s and "代码" in s:
                code_col = c
                break
        if code_col is None:
            for c in df.columns:
                s = str(c).lower()
                if "stock" in s and "code" in s:
                    code_col = c
                    break
        if code_col is None:
            code_col = df.columns[4] if len(df.columns) > 4 else df.columns[0]
        for raw in df[code_col].tolist():
            sym = _code_to_sym(raw)
            if sym and _allowed_symbol(sym):
                out.append(to_symbol(sym))
        logger.info("index %s -> %d allowed so far=%d", idx, len(df), len(out))
    return list(dict.fromkeys(out))


def list_a_share_mainboard(limit: int = 4000) -> list[str]:
    try:
        import akshare as ak  # type: ignore

        df = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock_info_a_code_name failed: %s", exc)
        return []
    out: list[str] = []
    for _, r in df.iterrows():
        code = str(r.get("code") or "").zfill(6)
        name = str(r.get("name") or "")
        if "ST" in name.upper() or "退" in name:
            continue
        sym = _code_to_sym(code)
        if not sym or not _allowed_symbol(sym):
            continue
        out.append(to_symbol(sym))
        if len(out) >= limit:
            break
    return out


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    store = ParquetStore(ROOT / "data" / "cache")

    idx_syms = index_constituents()
    a_syms = list_a_share_mainboard(4500)
    # prioritize index (more liquid / historically traded) then rest of main board
    target_syms = list(dict.fromkeys(idx_syms + a_syms))

    cached = {
        p.stem.replace("_", ".")
        for p in store.daily_dir.glob("*.parquet")
        if not p.stem.startswith("IDX")
    }
    missing = [s for s in target_syms if s not in cached]
    batch = int((cfg.get("data") or {}).get("history_expand_batch", 800))
    to_fetch = missing[:batch]
    logger.info(
        "cached=%d target=%d missing=%d batch=%d fetch=%d idx=%d",
        len(cached),
        len(target_syms),
        len(missing),
        batch,
        len(to_fetch),
        len(idx_syms),
    )

    start = "2020-01-01"
    end = date.today().isoformat()
    downloaded = 0
    if to_fetch:
        logger.info("Downloading %d symbols %s -> %s", len(to_fetch), start, end)
        fetched = fetch_many(to_fetch, start=start, end=end, sleep_sec=0.2)
        for sym, df in fetched.items():
            store.save_daily(sym, df)
        downloaded = len(fetched)
        logger.info("saved %d / %d", downloaded, len(to_fetch))
    else:
        logger.info("No missing symbols in this batch")

    lu_meta = rebuild_daily_limit_up_index(
        store.daily_dir,
        out_path=ROOT / "data" / "cache" / "leader_history" / "limit_up_by_date.json",
    )
    logger.info("limit_up index: %s", lu_meta)

    report = build_unified_dataset(root=ROOT, cfg=cfg, max_symbols=None)
    meta = report["meta"]
    summary = {
        "note": "EM zt_pool empty; expanded via index+mainboard bars",
        "cached_after": len([p for p in store.daily_dir.glob("*.parquet") if not p.stem.startswith("IDX")]),
        "downloaded_this_run": downloaded,
        "still_missing": max(0, len(missing) - len(to_fetch)),
        "n_events": meta.get("n_events"),
        "research_scale_ok": meta.get("research_scale_ok"),
        "pullback_edge": report.get("pullback_edge_verdict"),
        "modes": {m: (report.get("by_mode") or {}).get(m, {}).get("n") for m in (report.get("by_mode") or {})},
        "llm": 0,
        "tokens": 0,
    }
    out = ROOT / "data" / "leader" / "history_expand_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_reports(ROOT, report, lu_meta, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _write_reports(root: Path, report: dict, lu_meta: dict, summary: dict) -> None:
    meta = report["meta"]
    ds = [
        "# ENTRY DATASET REPORT",
        "",
        f"- events: **{meta.get('n_events')}**",
        f"- symbols: {meta.get('n_symbols_scanned')}",
        f"- trading days covered: {meta.get('n_trading_days_covered')} ({meta.get('date_start')} -> {meta.get('date_end')})",
        f"- PRIMARY execution: **{meta.get('primary_execution')}**",
        f"- research scale (>=3000): **{meta.get('research_scale_ok')}**",
        f"- pullback edge verdict: **{report.get('pullback_edge_verdict')}**",
        f"- LLM/ML/Token: 0/0/0",
        "",
        "## Expand status",
        "",
        f"- {summary}",
        "",
        "## By mode (PRIMARY = T+1 open net)",
        "",
    ]
    for m, cell in (report.get("by_mode") or {}).items():
        ds.append(
            f"- **{m}**: n={cell.get('n')} quality={cell.get('sample_quality')} "
            f"net={cell.get('primary_net_mean')} win={cell.get('primary_net_win')} "
            f"LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}"
        )
    ds += ["", "## Pullback by health", ""]
    for h, cell in (report.get("pullback_by_health") or {}).items():
        ds.append(
            f"- **{h}**: n={cell.get('n')} quality={cell.get('sample_quality')} "
            f"net={cell.get('primary_net_mean')} LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}"
        )
    ds += ["", "## Limit-up history index", "", f"- {lu_meta}", ""]
    (root / "docs" / "research" / "ENTRY_DATASET_REPORT.md").write_text("\n".join(ds), encoding="utf-8")

    ea = [
        "# ENTRY EVENT AUDIT",
        "",
        "## Scale expansion",
        "",
        f"- events now: **{meta.get('n_events')}** (target >=3000: {meta.get('research_scale_ok')})",
        f"- symbols scanned: {meta.get('n_symbols_scanned')}",
        f"- date range: {meta.get('date_start')} -> {meta.get('date_end')}",
        f"- edge: **{report.get('pullback_edge_verdict')}**",
        f"- BUY pipeline changed? **No**",
        f"- discovery note: EM zt_pool empty; used index+mainboard bar download",
        "",
        f"- expand summary: {summary}",
        "",
    ]
    (root / "docs" / "research" / "ENTRY_EVENT_AUDIT.md").write_text("\n".join(ea), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
