/** 研究终端中文展示层 — API 仍保留英文枚举，UI 统一中文化 */

const RATING: Record<string, string> = {
  BUY: "买入",
  STRONG_BUY: "强买",
  WATCH: "观察",
  PASS: "放弃",
  HOLD: "观察",
  NEUTRAL: "中性",
  GATE_SKIP: "门禁跳过",
  SKIP: "跳过",
};

const TRADING_ACTION: Record<string, string> = {
  NONE: "无",
  NO_ACTION: "无操作",
  SMALL_POSITION: "小仓",
  FULL_POSITION: "满仓",
  WAIT_FOR_CONFIRMATION: "等待确认",
  REDUCE: "减仓",
  EXIT: "退出",
};

const DISCOVERY: Record<string, string> = {
  "QUANT + NEWS": "量化+新闻",
  QUANT: "量化",
  NEWS: "新闻",
  EVENT: "事件",
  ML: "机器学习",
  UNKNOWN: "未知",
};

const NEWS_LABEL: Record<string, string> = {
  "NEWS DISCOVERY": "新闻发现",
  "QUANT CONFIRMED": "量化确认",
  "NEWS ONLY": "纯新闻",
};

const PRIORITY: Record<string, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
};

const SIGNAL: Record<string, string> = {
  Leader: "龙头",
  Profit: "利润",
  Event: "事件",
  News: "新闻",
  ML: "机器学习",
  Council: "投委会",
};

const CONFLICT_REASON: Record<string, string> = {
  "RS Weak": "相对强弱偏弱",
  "Momentum Weak": "动量偏弱",
  "Volume Weak": "量能偏弱",
  "Price Strong": "价格偏强",
};

const COUNCIL_ROLE: Record<string, string> = {
  Fundamental: "基本面",
  Quant: "量化",
  Event: "事件",
  Valuation: "估值",
  Bear: "空方",
  Chairman: "主席",
  Chair: "主席",
};

const STANCE: Record<string, string> = {
  BULLISH: "看多",
  BEARISH: "看空",
  NEUTRAL: "中性",
  BUY: "买入",
  WATCH: "观察",
  PASS: "放弃",
};

const STATUS: Record<string, string> = {
  INSUFFICIENT_SAMPLE: "样本不足",
  DATA_UNAVAILABLE: "数据不可用",
  UNPROVEN: "未验证",
  OK: "正常",
  PENDING: "待结算",
  SENT: "已发送",
  FAILED: "失败",
  COOLDOWN: "冷却中",
  DUPLICATE: "重复",
  DEGRADED: "降级",
};

const NOTIFY_LEVEL: Record<string, string> = {
  BUY: "买入",
  STRONG_BUY: "强买",
  RISK_EXIT: "风险退出",
  RATING_EXIT: "评级退出",
};

const SOURCE_ALPHA: Record<string, string> = {
  Event: "事件",
  Profit: "利润",
  Quant: "量化",
  News: "新闻",
  ML: "机器学习",
  AI: "投委会 AI",
};

const ESCALATION_REASON: Record<string, string> = {
  high_importance: "高重要性",
  low_confidence: "低置信度",
  news_quant_conflict: "新闻量化冲突",
  major_event: "重大事件",
  candidate_score: "候选分",
  unknown: "未知",
};

const DIRECTION: Record<string, string> = {
  positive: "利好",
  negative: "利空",
  neutral: "中性",
  POSITIVE: "利好",
  NEGATIVE: "利空",
  NEUTRAL: "中性",
};

export function labelRating(v?: string | null): string {
  if (!v) return "—";
  const u = v.toUpperCase();
  return RATING[u] || v;
}

export function labelTradingAction(v?: string | null): string {
  if (!v) return "无";
  const u = v.toUpperCase();
  return TRADING_ACTION[u] || v;
}

export function labelDiscovery(v?: string | null): string {
  if (!v) return "—";
  return DISCOVERY[v] || v;
}

export function labelNewsLabel(v: string): string {
  return NEWS_LABEL[v] || v;
}

export function labelPriority(v?: string | null): string {
  if (!v) return "—";
  return PRIORITY[v.toUpperCase()] || v;
}

export function labelSignal(name: string): string {
  return SIGNAL[name] || name;
}

export function labelConflictReason(v: string): string {
  return CONFLICT_REASON[v] || v;
}

export function labelCouncilRole(v: string): string {
  return COUNCIL_ROLE[v] || v;
}

export function labelStance(v?: string | null): string {
  if (!v) return "中性";
  const u = v.toUpperCase();
  return STANCE[u] || v;
}

export function labelStatus(v?: string | null): string {
  if (!v) return "—";
  return STATUS[v.toUpperCase()] || STATUS[v] || v;
}

export function labelNotifyLevel(v?: string | null): string {
  if (!v) return "—";
  return NOTIFY_LEVEL[v.toUpperCase()] || v;
}

export function labelSourceAlpha(v: string): string {
  return SOURCE_ALPHA[v] || v;
}

export function labelEscalationReason(v: string): string {
  return ESCALATION_REASON[v.toLowerCase()] || v;
}

export function labelDirection(v?: string | null): string {
  if (!v) return "—";
  const s = String(v).toLowerCase();
  if (s.includes("pos") || s.includes("bull")) return "利好";
  if (s.includes("neg") || s.includes("bear")) return "利空";
  return DIRECTION[v] || DIRECTION[s] || v;
}

export function labelRisk(v?: string | null): string {
  if (!v) return "通过";
  if (v === "BLOCKED") return "拦截";
  if (v === "PASS") return "通过";
  return v;
}

export function insufficientSample(n?: number | null): string {
  return n != null ? `样本不足 (n=${n})` : "样本不足";
}

export function labelPerfLane(v: string): string {
  const map: Record<string, string> = {
    "News Discovery": "新闻发现",
    "News Evidence": "新闻证据",
    "News Only": "纯新闻",
    "News + Factor": "新闻+因子",
    "News + Council": "新闻+投委会",
    "No News": "无新闻",
    "News Discovery + Evidence": "新闻发现+证据",
  };
  return map[v] || v;
}

export const MATRIX_QUADS: { key: string; title: string }[] = [
  { key: "news_strong_quant_strong", title: "强新闻 · 强量化" },
  { key: "news_strong_quant_weak", title: "强新闻 · 弱量化" },
  { key: "news_weak_quant_strong", title: "弱新闻 · 强量化" },
  { key: "news_weak_quant_weak", title: "弱新闻 · 弱量化" },
];
