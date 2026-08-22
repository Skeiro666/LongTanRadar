export type BacktestResult = {
  initial_balance: number;
  final_equity: number;
  total_return: number;
  annualized: number;
  max_drawdown: number;
  sharpe: number;
  turnover: number;
  win_rate: number;
  trades: number;
  yearly: Record<string, number>;
  equity_curve: [string, number][];
  strategy?: string;
};

export type ModelMeta = {
  run_id: string;
  model_path: string;
  ic: number;
  mse: number;
  params: Record<string, number>;
  feature_importance: Record<string, number>;
  n_train: number;
  n_valid: number;
};

export type AppConfig = {
  strategy: { name: string };
  ml: Record<string, unknown>;
  ai: { enabled?: boolean; has_key?: boolean; model?: string };
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string }>("/api/health"),
  config: () => req<AppConfig>("/api/config"),
  models: () => req<ModelMeta[]>("/api/models"),
  latestBacktest: () => req<BacktestResult>("/api/backtest/latest"),
  train: (body: Record<string, number | undefined>) =>
    req<ModelMeta>("/api/train", { method: "POST", body: JSON.stringify(body) }),
  backtest: (body: { strategy: string; run_id?: string; start?: string; end?: string }) =>
    req<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(body) }),
  review: () => req<{ text: string | null; message?: string }>("/api/review", { method: "POST" }),
  paper: () => req<Record<string, unknown>>("/api/paper"),
  picksLatest: () => req<any>("/api/picks/latest"),
  picksRun: (body: { top_n?: number }) =>
    req<any>("/api/picks/run", { method: "POST", body: JSON.stringify(body) }),
  account: () => req<any>("/api/account"),
  orders: () => req<any[]>("/api/orders"),
  tradePicks: (body: { regenerate?: boolean; confirm_live?: boolean }) =>
    req<any>("/api/trade/picks", { method: "POST", body: JSON.stringify(body) }),
  tradeAuto: () => req<any>("/api/trade/auto", { method: "POST", body: "{}" }),
  tradeOrder: (body: { symbol: string; side: string; quantity: number; price?: number }) =>
    req<any>("/api/trade/order", { method: "POST", body: JSON.stringify(body) }),
  agent: () => req<any>("/api/agent"),
  agentStart: (body?: { interval_sec?: number; run_now?: boolean }) =>
    req<any>("/api/agent/start", { method: "POST", body: JSON.stringify(body || {}) }),
  agentStop: () => req<any>("/api/agent/stop", { method: "POST", body: "{}" }),
  agentReset: () => req<any>("/api/agent/reset", { method: "POST", body: "{}" }),
  agentCycle: () => req<any>("/api/agent/cycle", { method: "POST", body: "{}" }),
  pnl: () => req<any>("/api/pnl"),
  researchLatest: () => req<any>("/api/research/latest"),
  researchRun: (body?: { top_n?: number }) =>
    req<{ status: string; run_id?: string; poll?: string }>("/api/research/run", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  researchProgress: () => req<any>("/api/research/progress"),
  researchRefreshNews: () => req<any>("/api/research/refresh-news", { method: "POST", body: "{}" }),
  researchSessions: (limit = 50) => req<any>(`/api/research/sessions?limit=${limit}`),
  researchSession: (id: string) => req<any>(`/api/research/session/${id}`),
  researchCandidates: (candidateSource = "") =>
    req<any>(
      `/api/research/candidates${candidateSource ? `?candidate_source=${encodeURIComponent(candidateSource)}` : ""}`
    ),
  researchHypotheses: (symbol = "") =>
    req<any>(`/api/research/hypotheses${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),
  researchOutcomes: (horizon = "5") => req<any>(`/api/research/outcomes?horizon=${horizon}`),
  researchAttribution: (horizon = "5") => req<any>(`/api/research/attribution?horizon=${horizon}`),
  researchAlphaDashboard: (horizon = "5") => req<any>(`/api/research/alpha-dashboard?horizon=${horizon}`),
  notifications: (limit = 100) => req<any>(`/api/notifications?limit=${limit}`),
  notificationStats: () => req<any>("/api/notifications/stats"),
  alphaLab: () => req<any>("/api/alpha-lab"),
  notificationStatus: (symbol: string, researchId = "") =>
    req<any>(
      `/api/notifications/status?symbol=${encodeURIComponent(symbol)}${researchId ? `&research_id=${encodeURIComponent(researchId)}` : ""}`
    ),
  optimizerExperiments: (limit = 20) => req<any>(`/api/optimizer/experiments?limit=${limit}`),
  newsDiscovery: () => req<any>("/api/news/discovery"),
  news: (symbol: string, name = "") =>
    req<any>(`/api/news/${encodeURIComponent(symbol)}?name=${encodeURIComponent(name)}`),
  factors: () => req<any>("/api/factors"),
  mlRankTrain: () => req<any>("/api/ml/rank/train", { method: "POST", body: "{}" }),
  mlWeightExperiments: (limit = 20) => req<any>(`/api/ml/weight-experiments?limit=${limit}`),
  mlWeightExperimentRun: () =>
    req<any>("/api/ml/weight-experiment", { method: "POST", body: "{}" }),
  aiCost: () => req<any>("/api/ai/cost"),
};

export function pct(n: number | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

export function num(n: number | undefined, d = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(d);
}
