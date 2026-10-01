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

export type HistoryPoint = { date: string; close: number; volume: number };
export type History = Freshness & { symbol: string; range: string; points: HistoryPoint[] };

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
  note: string;
};

export type Forecast = Freshness & {
  symbol: string;
  horizon_days: number;
  last_close: number;
  last_date: string;
  predicted_return: number;
  predicted_price: number;
  interval_80: { low: number; high: number };
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
