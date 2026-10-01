export type Quote = {
  symbol: string;
  price: number;
  previous_close: number;
  change: number;
  change_percent: number;
  as_of: string;
};

export type HistoryPoint = { date: string; close: number; volume: number };
export type History = { symbol: string; range: string; points: HistoryPoint[] };

export type Metrics = { rmse: number; mae: number; directional_accuracy: number | null };

export type Forecast = {
  symbol: string;
  horizon_days: number;
  last_close: number;
  last_date: string;
  predicted_return: number;
  predicted_price: number;
  interval_80: { low: number; high: number };
  path: { date: string; mid: number; low: number; high: number }[];
  backtest: {
    method: string;
    n_test_points: number;
    model: Metrics;
    naive_baseline: Metrics;
    skill_vs_baseline: number;
    beats_baseline: boolean;
    note: string;
  };
  notes: string[];
  disclaimer: string;
};

export type SearchResult = { symbol: string; name: string; exchange: string };
