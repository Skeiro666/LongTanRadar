export type SignalContribution = {
  name: string;
  score: number;
  relative_contribution: number;
};

export type CandidateCard = {
  symbol: string;
  name?: string;
  price?: number;
  research_rating?: string;
  trading_action?: string;
  risk_status?: string;
  risk_reasons?: string[];
  discovery_source?: string;
  news_labels?: string[];
  news_alpha_bucket?: string;
  quadrant?: string;
  signal_contribution?: SignalContribution[];
  top_reasons?: string[];
  research_priority?: { level: string; reasons: string[] };
  news?: Record<string, unknown> | null;
  conflict?: Record<string, unknown>;
  council_summary?: Array<{
    role: string;
    stance?: string;
    confidence?: number;
    summary?: string;
    expandable?: boolean;
    full?: Record<string, unknown>;
  }>;
  research_id?: string;
  degraded?: { news?: boolean; reason?: string };
  historical_cohort?: Record<string, unknown> | null;
};

export type ResearchTerminal = {
  as_of?: string;
  generated_at?: string;
  market_status?: Record<string, unknown>;
  counts?: {
    candidates?: number;
    council?: number;
    news_discovery?: number;
    ratings?: Record<string, number>;
  };
  data_completeness?: { news_coverage?: string; pct?: number };
  candidates?: CandidateCard[];
  matrix?: Record<string, string[]>;
  news_discovery_status?: Record<string, unknown>;
};
