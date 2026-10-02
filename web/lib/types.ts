export type Warning = { code: string; message: string };

/** Freshness fields the backend adds to quote/history/forecast responses. */
export type Freshness = {
  data_as_of: string;
  fetched_at: string;
  is_delayed: boolean;
  stale: boolean;
  warnings: Warning[];
};

export type Quote = Freshness & {
  symbol: string;
  price: number;
  previous_close: number;
  change: number;
  change_percent: number;
  as_of: string;
};


export type Metrics = { rmse: number; mae: number; directional_accuracy: number | null };

export type Backtest = {
  method: string;
  n_test_points: number;
  /** ~ n_test_points / horizon: how many non-overlapping tests that is worth */
  n_independent_tests?: number;
  small_sample?: boolean;
  /** share of test periods in which the price rose (what "always guess up" would score) */
  up_rate?: number;
  /** 90% bootstrap interval for skill_vs_baseline */
  skill_ci_90?: [number, number];
  model: Metrics;
  naive_baseline: Metrics;
  /** 1 - model RMSE / naive RMSE: positive = model error is lower than guessing "price stays flat" */
  skill_vs_baseline: number;
  beats_baseline: boolean;
  too_few_independent?: boolean;
  note: string;
};

/** Split-conformal calibration of the forecast range and the coverage measured by replaying it through past data. */
export type Conformal = {
  used: boolean;
  method: string;
  target_coverage: number;
  /** half-width in units of (daily volatility x sqrt(horizon)); a normal-theory 80% band would use normal_multiplier */
  multiplier: number | null;
  normal_multiplier: number;
  n_calibration: number;
  n_calibration_independent: number;
  /** share of past outcomes that landed inside the range this recipe would have given (null if it could not be measured) */
  measured_coverage: number | null;
  measured_coverage_ci_90: [number, number] | null;
  n_evaluation: number;
  n_evaluation_independent: number;
  supported: boolean;
  reason_not_used: string | null;
  fallback: string | null;
};

export type Forecast = Freshness & {
  symbol: string;
  horizon_days: number;
  last_close: number;
  last_date: string;
  predicted_return: number;
  predicted_price: number;
  interval_80: { low: number; high: number };
  /** false at long horizons: the range is a volatility cone, not a backtest-calibrated 80% interval */
  interval_calibrated?: boolean;
  interval_method?: string;
  interval_method_name?: "split_conformal" | "walk_forward_residuals" | "volatility_cone";
  conformal?: Conformal;
  path: { date: string; mid: number; low: number; high: number }[];
  backtest: Backtest;
  notes: string[];
  disclaimer: string;
};

export type SearchResult = { symbol: string; name: string; exchange: string };

export type NewsItem = { headline: string; source: string; url: string; published_at: string };
export type News = Freshness & { symbol: string; items: NewsItem[]; note: string };

export type CompareSeries = { symbol: string; start_price: number; end_price: number; change_percent: number; points: number[] };
export type Compare = Freshness & {
  range: string;
  dates: string[];
  series: CompareSeries[];
  failed: { symbol: string; code: string; message: string }[];
  base: string;
};

export type ReportRow = {
  symbol: string;
  verdict: "better" | "inconclusive" | "not_better";
  skill_vs_baseline: number;
  skill_ci_90: [number, number];
  model_rmse: number;
  baseline_rmse: number;
  hit_rate: number | null;
  up_rate: number;
  n_test_points: number;
  n_independent_tests: number;
  small_sample: boolean;
  /** true when the 80% range is a conformal band whose coverage was measured on past data */
  range_tested?: boolean;
  /** share of past outcomes that landed inside the 80% range (replayed on past data); null if not measured */
  range_coverage?: number | null;
  range_independent_tests?: number;
  data_as_of: string;
};
export type ModelReport = Freshness & {
  horizon_days: number;
  rows: ReportRow[];
  failed: { symbol: string; code: string; message: string }[];
  method: string;
  summary: { better: number; inconclusive: number; not_better: number; total: number };
  disclaimer: string;
};

export type Verdict = "better" | "inconclusive" | "not_better";
export type ModelRow = {
  model: string;
  label: string;
  description: string;
  rmse: number;
  mae: number;
  hit_rate: number | null;
  skill_vs_naive: number;
  skill_ci_90: [number, number];
  beats_naive: boolean;
  verdict: Verdict | "baseline";
};
export type ModelComparison = Freshness & {
  symbol: string;
  horizon_days: number;
  embargo_days: number;
  n_folds: number;
  n_test_points: number;
  n_independent_tests: number;
  small_sample: boolean;
  up_rate: number;
  method: string;
  models: ModelRow[];
  any_beats_naive: boolean;
  /** volatility (size-of-move) models judged on the same walk-forward test; null if there was not enough history */
  risk_models?: { headline_model: string; garch: GarchInfo; models: Omit<VolModelRow, "forecast_daily_vol" | "beats_naive">[] } | null;
  n_candidates: number;
  note: string;
  disclaimer: string;
};

export type VolModelRow = {
  model: string;
  label: string;
  description: string;
  typical_error_pct: number;
  skill_vs_naive: number;
  skill_ci_90: [number, number];
  beats_naive: boolean;
  verdict: Verdict | "baseline";
  forecast_daily_vol: number;
  annualized_vol: number;
  horizon_vol?: number;
  /** share of past h-day moves that stayed inside +/- this model's 1-sigma range */
  one_sigma_coverage?: number;
  /** same error metric, judged against the headline model (EWMA) instead of the naive baseline; absent on the headline */
  vs_headline?: { model: string; skill: number; skill_ci_90: [number, number]; verdict: Verdict };
};
export type GarchInfo = {
  available: boolean;
  reason?: string | null;
  converged?: boolean;
  n_failed_fold_fits?: number;
  params?: { alpha: number; gamma: number; beta: number; persistence: number; half_life_days: number | null; long_run_annual_vol: number; asymmetric: boolean };
  vs_headline?: { model: string; skill: number; skill_ci_90: [number, number]; verdict: Verdict };
  horizon_vol?: number;
  annualized_vol?: number;
  one_sigma_pct?: number;
};
export type Volatility = Freshness & {
  symbol: string;
  horizon_days: number;
  last_close: number;
  headline_model: string;
  forecast_daily_vol: number;
  annualized_vol: number;
  horizon_vol: number;
  risk_range: { one_sigma_pct: number; low: number; high: number; nominal_coverage: number; backtest_coverage: number };
  verdict: Verdict;
  skill_vs_naive: number;
  skill_ci_90: [number, number];
  models: VolModelRow[];
  garch?: GarchInfo;
  n_test_points: number;
  n_independent_tests: number;
  small_sample: boolean;
  embargo_days: number;
  method: string;
  notes: string[];
  disclaimer: string;
};

export type LogRow = {
  id: number;
  symbol: string;
  horizon_days: number;
  made_at: string;
  base_date: string;
  base_close: number;
  predicted_return: number;
  interval_low: number;
  interval_high: number;
  backtest_skill: number | null;
  model: string;
  status: "pending" | "resolved";
  resolved_at: string | null;
  realized_date: string | null;
  realized_close: number | null;
  realized_return: number | null;
  entry_hash: string;
  in_interval?: boolean;
  direction_correct?: boolean;
};
export type Scorecard = {
  verdict: "no_data" | "too_early" | Verdict;
  n_resolved: number;
  n_pending: number;
  n_dates: number;
  n_independent: number;
  min_for_verdict: number;
  horizon_days?: number;
  skill_vs_naive?: number;
  skill_ci_90?: [number, number] | null;
  model_rmse?: number;
  naive_rmse?: number;
  hit_rate?: number;
  up_rate?: number;
  interval_coverage?: number;
  interval_nominal?: number;
};
export type PredictionLog = Freshness & {
  items: LogRow[];
  total: number;
  limit: number;
  offset: number;
  scorecard: Scorecard;
  chain_ok: boolean;
  outcomes_ok?: boolean;
  unsealed_resolved?: number;
  symbols: string[];
  horizon_days: number;
  storage: { backend: string; durable: boolean };
  disclaimer: string;
};

export type TrendingItem = { rank: number; symbol: string; name: string; return_percent: number; last_close: number; as_of: string };
export type Trending = Freshness & {
  days: number;
  limit: number;
  items: TrendingItem[];
  universe_size: number;
  evaluated: number;
  method: string;
  note: string;
  disclaimer: string;
};

export type SpikeVerdict = "better" | "worse" | "inconclusive";
export type SpikeRange = { coverage: number; mean_width: number; interval_score: number; score_gain_vs_baseline?: number; score_gain_ci_90?: [number, number]; verdict?: SpikeVerdict };
export type SpikeDay = {
  date: string; baseline_mid: number; band_low: number; band_high: number; median: number; mean: number; sim_low: number; sim_high: number;
  spike_up: number; spike_down: number; p_jump_up: number; p_jump_down: number; p_touch_high: number; p_touch_low: number;
};
export type SpikeBacktest =
  | { available: false; reason: string }
  | {
      available: true; n_origins: number; horizon_days: number; small_sample: boolean; nominal_coverage: number; embargo_days: number; method: string;
      baseline: SpikeRange; jump_unclamped: SpikeRange; spike_clamped: SpikeRange;
      point: { baseline_rmse: number; spike_median_rmse: number; naive_rmse: number; skill_vs_baseline: number; skill_ci_90: [number, number]; verdict: SpikeVerdict };
      mean_clamped_fraction_at_horizon: number; summary: string;
    };
export type Spikes = Freshness & {
  experimental: true; symbol: string; horizon_days: number; last_close: number; last_date: string;
  baseline_interval: { low: number; high: number };
  model: { name: string; n_paths: number; seed: number; bounds: string; jump_threshold_sigma: number; calibration_days: number };
  calibration: {
    robust_sigma_daily: number; diffusion_sigma_daily: number; jump_threshold_pct: number; n_jumps_up: number; n_jumps_down: number;
    jump_freq_up_per_day: number; jump_freq_down_per_day: number; mean_jump_up_pct: number | null; mean_jump_down_pct: number | null; few_jumps: boolean;
  };
  path: SpikeDay[];
  sample_paths: number[][];
  clamping: { method: string; fraction_of_path_days_clamped: number; fraction_of_paths_touching_band: number; terminal_at_high: number; terminal_at_low: number };
  backtest: SpikeBacktest;
  notes: string[];
  disclaimer: string;
};

export type TimelineRange = "1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y";
export type Timeline = Freshness & {
  symbol: string;
  range: TimelineRange;
  points: { date: string; close: number }[];
  n_points_total: number;
  downsampled: boolean;
  summary: {
    start_date: string; end_date: string; start_close: number; end_close: number; period_return_pct: number;
    high: number; high_date: string; low: number; low_date: string; max_drawdown_pct: number;
  };
  note: string;
  disclaimer: string;
};
