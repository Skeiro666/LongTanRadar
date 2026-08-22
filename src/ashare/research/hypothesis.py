from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ashare.news.models import ExtractedEvent, RawNews, make_id


# event_type → (inference, hypothesis, validation_questions)
_TEMPLATES: dict[str, tuple[str, str, list[str]]] = {
    "ORDER": (
        "订单若确认执行，可能提升未来收入。",
        "如果订单确认收入占主营比例较高且毛利率不差于现有业务，则未来利润可能改善。",
        ["订单金额相对营收占比？", "收入确认周期？", "是否已计入在手订单？", "毛利率与现有业务比较？", "客户集中度与违约风险？"],
    ),
    "EARNINGS_GUIDANCE": (
        "业绩预告可能改变近期盈利预期。",
        "如果预告口径与最终报表一致且非一次性损益主导，则盈利趋势可能延续。",
        ["预告是区间还是上限？", "是否含非经常性损益？", "与上年同期基数？", "是否已有市场一致预期（无数据则不可用）？"],
    ),
    "PRICE_INCREASE": (
        "产品提价可能改善单位毛利。",
        "如果提价能传导且销量不显著下滑，则毛利率可能上升。",
        ["提价产品收入占比？", "涨价幅度？", "原材料成本是否同步上涨？", "竞争对手是否跟涨？", "历史类似提价后的销量？"],
    ),
    "CAPACITY_EXPANSION": (
        "产能扩张可能增加未来供给。",
        "如果新产能按期达产且需求能消化，则收入规模可能上升；若供给过剩则可能压制价格。",
        ["投产时间表？", "资本开支与折旧？", "行业供需？", "公司市占率？"],
    ),
    "M_AND_A": (
        "并购可能改变业务边界与报表并表范围。",
        "如果对价合理且协同可兑现，则中长期价值可能提升；否则商誉与整合风险上升。",
        ["交易是否完成？", "对价与估值？", "并表时点？", "商誉规模？", "监管审批？"],
    ),
    "RESTRUCTURE": (
        "重组可能改变资产质量与股权结构。",
        "如果重组落地且主业更清晰，则估值逻辑可能重估；失败则消耗时间与费用。",
        ["方案是否过会？", "置入资产质量？", "摊薄与控制权？"],
    ),
    "SHARE_BUYBACK": (
        "回购可能减少流通股本、传递管理层信号。",
        "如果回购真实执行且非高位突击，则每股指标可能改善。",
        ["回购额度与进度？", "资金来源？", "是否同时减持？"],
    ),
    "INSIDER_SELL": (
        "减持可能增加供给并传递内部人看法。",
        "如果减持规模大或密集，则需下调对公司质量或估值的信心。",
        ["减持比例？", "是否预披露计划？", "是否业绩敏感期？"],
    ),
    "INSIDER_BUY": (
        "增持可能传递内部人对价值的看法。",
        "如果增持真实出资且非象征性，则内部人与股东利益更一致。",
        ["增持金额相对薪酬/持股？", "是否杠杆增持？"],
    ),
    "REGULATORY": (
        "监管处罚可能带来罚款、业务限制与声誉损失。",
        "如果处罚触及主营牌照或持续经营，则基本面可能恶化。",
        ["罚没金额？", "是否暂停业务？", "是否牵涉实控人？"],
    ),
    "LITIGATION": (
        "诉讼结果不确定，或有负债可能兑现。",
        "如果败诉概率高且标的金额大，则净资产与现金流可能受损。",
        ["诉请金额？", "一审/终审？", "计提情况？"],
    ),
    "POLICY_SUPPORT": (
        "政策若落地可能改善行业需求或成本。",
        "如果公司是直接受益主体且补贴/配额可持续，则盈利可能改善；否则仅为情绪。",
        ["是否点名公司/细分行业？", "执行细则？", "持续时间？", "受益映射是否有数据（无则 unavailable）？"],
    ),
    "OTHER": (
        "该报道尚未映射到可验证的经营变量。",
        "在缺少可核验事实前，不应假设该信息改变盈利。",
        ["信息源是否公告？", "是否已有代码/公司名映射？"],
    ),
}


@dataclass
class ResearchHypothesis:
    hypothesis_id: str
    event_id: str
    symbol: str
    event_type: str
    type: str
    fact: str
    inference: str
    hypothesis: str
    validation_questions: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = "HYPOTHESIS"
        d["layers"] = {"FACT": self.fact, "INFERENCE": self.inference, "HYPOTHESIS": self.hypothesis}
        return d


class ResearchHypothesisEngine:
    """Rule templates only. Does not call LLM. Does not emit BUY."""

    def from_event(
        self,
        ev: ExtractedEvent | dict[str, Any],
        *,
        news: RawNews | None = None,
    ) -> ResearchHypothesis:
        if isinstance(ev, dict):
            etype = str(ev.get("event_type") or "OTHER")
            eid = str(ev.get("event_id") or "")
            sym = str(ev.get("symbol") or "")
            title = str(ev.get("title") or ev.get("reason") or "")
            evid = [eid, str(ev.get("news_id") or ev.get("evidence_id") or "")]
        else:
            etype = ev.event_type or "OTHER"
            eid = ev.event_id
            sym = ev.symbol
            title = ev.title
            evid = [ev.event_id, ev.news_id or ev.evidence_id]
        inf, hyp, qs = _TEMPLATES.get(etype, _TEMPLATES["OTHER"])
        fact = (news.title.strip() if news and news.title else title).strip()
        h = ResearchHypothesis(
            hypothesis_id=make_id("H"),
            event_id=eid,
            symbol=sym,
            event_type=etype,
            type="HYPOTHESIS",
            fact=fact,
            inference=inf,
            hypothesis=hyp,
            validation_questions=list(qs),
            evidence_ids=[x for x in evid if x],
        )
        if isinstance(ev, ExtractedEvent):
            if not ev.facts:
                ev.facts = [h.fact]
            if not ev.inferences:
                ev.inferences = [h.inference]
        return h

    def from_events(self, events: list[Any], *, news: RawNews | None = None) -> list[ResearchHypothesis]:
        return [self.from_event(e, news=news) for e in events]
