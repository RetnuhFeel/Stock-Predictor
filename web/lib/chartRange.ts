import type { TimelineRange } from "./types";

export const CHART_RANGES: { id: TimelineRange; label: string; long: string }[] = [
  { id: "1mo", label: "1M", long: "1 month" },
  { id: "3mo", label: "3M", long: "3 months" },
  { id: "6mo", label: "6M", long: "6 months" },
  { id: "1y", label: "1Y", long: "1 year" },
  { id: "2y", label: "2Y", long: "2 years" },
  { id: "5y", label: "5Y", long: "5 years" },
];
export const DEFAULT_RANGE: TimelineRange = "6mo"; // what the chart showed before ranges were merged
export const RANGE_KEY = "chart.range.v1";

/** Safe parse of a saved value: anything unknown (corrupt, old, tampered) falls back to the default. */
export function parseRange(raw: unknown): TimelineRange {
  return CHART_RANGES.some((r) => r.id === raw) ? (raw as TimelineRange) : DEFAULT_RANGE;
}

export const rangeLong = (id: string) => CHART_RANGES.find((r) => r.id === id)?.long ?? id;

export type ChartPoint = { date: string; close?: number; mid?: number; band?: [number, number] };

/** Chart rows: history closes, then the forecast path joined at the last close so the overlay lines up at the right edge. */
export function buildRows(
  history: { date: string; close: number }[],
  forecastPath: { date: string; mid: number; low: number; high: number }[] | undefined,
  normalized: boolean,
): ChartPoint[] {
  if (!history.length) return [];
  const base = history[0].close;
  const f = (v: number) => (normalized ? (v / base - 1) * 100 : v);
  const rows: ChartPoint[] = history.map((p) => ({ date: p.date, close: f(p.close) }));
  if (forecastPath?.length) {
    const last = rows[rows.length - 1];
    last.mid = last.close;
    last.band = [last.close!, last.close!];
    for (const p of forecastPath) rows.push({ date: p.date, mid: f(p.mid), band: [f(p.low), f(p.high)] });
  }
  return rows;
}
