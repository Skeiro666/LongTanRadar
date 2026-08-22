export type PipelineTimingRow = {
  phase: string;
  label: string;
  typical: string;
  note: string;
  status?: string;
  duration_sec?: number | null;
  error?: string;
};

export type ProgressStep = {
  ts?: string;
  phase: string;
  level?: string;
  message?: string;
  label?: string;
  detail?: unknown;
  duration_sec?: number;
  status?: string;
  type?: string;
};

export type ResearchProgress = {
  status: "idle" | "running" | "done" | "error";
  run_id?: string;
  started_at?: string;
  finished_at?: string;
  elapsed_sec?: number;
  current_phase?: string;
  steps?: ProgressStep[];
  pipeline_timing?: PipelineTimingRow[];
  error?: string;
  result?: ResearchPayload;
  run_log?: {
    run_id?: string;
    elapsed_sec?: number;
    pipeline_timing?: PipelineTimingRow[];
    steps?: ProgressStep[];
  };
};

export type NewsCandidate = {
  symbol?: string;
  name?: string;
  event_type?: string;
  event_direction?: string;
  reason?: string;
  event_impact?: number;
  confidence?: number;
  source_quality?: string;
  mapping_method?: string;
  novelty_available?: boolean;
  novelty_score?: number;
  price_in_risk?: string;
  price_in_score?: number;
  lifecycle_status?: string;
  lifecycle_reason?: string;
  reject_reason?: string;
  research_hypotheses?: { layers?: { HYPOTHESIS?: string }; hypothesis?: string }[];
  price_reaction?: { available?: boolean; news_signal?: string; price_signal?: string };
};

export type CandidateUnionItem = {
  symbol?: string;
  name?: string;
  in_council?: boolean;
  candidate_sources?: string[];
  candidate_score?: number;
  trigger?: { type?: string };
};

export type RejectedNews = {
  reject_reason?: string;
  event_type?: string;
  title?: string;
  reason?: string;
};

export type AttributionBucket = {
  n?: number;
  mean_return?: number;
  mean_excess_return?: number;
  insufficient_sample?: boolean;
};

export type PlatformReport = {
  research_id?: string;
  symbol?: string;
  name?: string;
  rating?: string;
  action?: string;
  candidate_sources?: string[];
  chairman?: { confidence?: number; base_case?: string; risks?: string[] };
  news?: {
    counts?: { last_24h?: number; last_7d?: number; last_30d?: number };
    net_event_score?: number;
    incomplete?: boolean;
    link_filter?: { n_weak_dropped?: number; n_linked?: number };
    last_7d?: {
      id?: string;
      title?: string;
      published_at?: string;
      media?: string;
      classification?: string;
      url?: string;
    }[];
    conflicts?: string[];
    expectation?: { available?: boolean; note?: string };
    timeline?: {
      event_id?: string;
      event_time?: string;
      event_type?: string;
      direction?: string;
      impact_score?: number;
      evidence_id?: string;
    }[];
  };
};

export type ResearchPick = {
  symbol?: string;
  name?: string;
  committee_verdict?: string;
  score?: number;
  research_rating?: string;
  trading_action?: string;
  decision_source?: string;
  committee_thesis?: string;
  ai_rationale?: string;
  why?: string;
  committee_risks?: string;
  committee_horizon?: string;
};

export type PoolItem = {
  symbol?: string;
  name?: string;
  board_count?: number;
  profit_gap_score?: number;
  event_tags?: string[];
  thesis?: string;
};

export type RoundtableRole = {
  id?: string;
  name?: string;
  stance?: string;
  confidence?: number;
  model?: string;
  points?: string[];
  challenges?: string[];
  falsify?: string;
};

export type RoundtableData = {
  summary?: string;
  source?: string;
  replay_notes?: string;
  models_used?: { role?: string; model?: string }[];
  chair_model?: string;
  roles?: RoundtableRole[];
  debate?: {
    from?: string;
    to?: string;
    point?: string;
    from_role?: string;
    to_role?: string;
    rebuttal?: string;
  }[];
};

export type BenchmarkSnapshot = {
  requested?: string;
  actual?: string;
  index?: string;
  fallback?: boolean;
  fallback_reason?: string | null;
  as_of?: string;
};

export type OutcomeRow = {
  symbol?: string;
  horizons?: Record<
    string,
    {
      actual_return?: number;
      market_alpha?: number;
      selection_alpha?: number;
      excess_return?: number;
    }
  >;
};

export type ResearchPayload = {
  as_of?: string;
  strategy?: string;
  universe_size?: number;
  scored?: number;
  run_log?: ResearchProgress["run_log"];
  screen?: { sources?: Record<string, number> };
  pool?: PoolItem[];
  picks?: ResearchPick[];
  platform_reports?: PlatformReport[];
  news_discovery?: {
    available?: boolean;
    news_data_incomplete?: boolean;
    n_news?: number;
    n_events?: number;
    n_candidates?: number;
    n_rejected?: number;
    news_candidates?: NewsCandidate[];
    rejected?: RejectedNews[];
  };
  candidate_union?: {
    n_union?: number;
    n_research?: number;
    universe?: CandidateUnionItem[];
  };
  research_outcomes?: {
    available?: boolean;
    horizon?: string;
    n?: number;
    benchmark?: {
      available?: boolean;
      snapshot?: BenchmarkSnapshot;
      primary?: string;
    };
    benchmark_snapshot?: BenchmarkSnapshot;
    outcomes?: OutcomeRow[];
    ai_incremental_alpha?: {
      available?: boolean;
      canonical?: boolean;
      method?: string;
      insufficient_sample?: boolean;
      ai_incremental_alpha?: number;
      sample_count?: number;
      baseline_topk?: { mean_return?: number };
      ai_topk?: { mean_return?: number };
    };
    ai_topk_ablation?: {
      available?: boolean;
      insufficient_sample?: boolean;
      ai_incremental_alpha?: number;
      sample_count?: number;
      baseline_topk?: { mean_return?: number };
      ai_topk?: { mean_return?: number };
    };
    ai_incremental_alpha_legacy?: { note?: string; conclusion?: string };
    role_ablation?: {
      available?: boolean;
      experimental?: boolean;
      by_role?: Record<
        string,
        { delta_vs_full_council?: number | null; topk_mean_return?: number | null }
      >;
    };
    model_benchmark?: {
      available?: boolean;
      alpha_per_100k_tokens?: number | null;
      models?: { model?: string; tokens?: number; cost_usd?: number }[];
      roles?: { role?: string; tokens?: number; cost_usd?: number }[];
    };
    discovery_attribution?: { sources?: Record<string, AttributionBucket> };
    attribution?: { by_source_bucket?: Record<string, AttributionBucket> };
  };
  ai_cost?: {
    n_calls?: number;
    total_tokens?: number;
    estimated_usd?: number;
    cache_saved_tokens?: number;
  };
  roundtable?: RoundtableData;
  decision_chain?: {
    canonical_source?: string;
    paper_trading_source?: string;
    roundtable_controls_trading?: boolean;
  };
  decision_consistency?: { ok?: boolean; errors?: string[] };
  canonical_decisions?: Record<string, unknown>[];
};
