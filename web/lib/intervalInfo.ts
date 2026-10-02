import type { Forecast } from "./types";

/** Plain-language description of how the forecast range was made and how well that recipe did on past data. */
export type IntervalInfo = {
  /** short label used next to the price range and in the chart legend */
  label: string;
  /** true only when the range's coverage was measured on past data and looked usable */
  tested: boolean;
  /** one or two sentences, always shown */
  summary: string;
  /** an extra warning, if any */
  caveat?: string;
};

const p0 = (x: number) => `${Math.round(x * 100)}%`;

export function intervalInfo(f?: Pick<Forecast, "interval_calibrated" | "interval_method_name" | "conformal" | "horizon_days">): IntervalInfo {
  if (!f) return { label: "80% interval", tested: false, summary: "" };
  const c = f.conformal;
  if (c?.used && c.measured_coverage != null) {
    const ci = c.measured_coverage_ci_90;
    const cov = c.measured_coverage;
    const spread = ci ? `, plausible range ${p0(ci[0])} to ${p0(ci[1])}` : "";
    const out: IntervalInfo = {
      label: "80% range (tested on past data)",
      tested: true,
      summary:
        `How it is made: recent volatility, stretched or shrunk by how wrong past forecasts of this kind were (a “conformal” calibration that only uses data available at the time). ` +
        `Replayed on past data, the real price landed inside ranges built this way ${p0(cov)} of the time (target ${p0(c.target_coverage)}${spread}; about ${c.n_evaluation_independent} independent ${f.horizon_days}-day periods, calibrated on ${c.n_calibration} past forecasts).`,
    };
    if (cov < c.target_coverage - 0.1) out.caveat = "That is clearly below the 80% target, so this range may be too narrow.";
    else if (cov > c.target_coverage + 0.1) out.caveat = "That is above the 80% target, so this range may be wider than needed.";
    return out;
  }
  const why = c?.reason_not_used ? ` We checked it against past data but could not use the result: ${c.reason_not_used}.` : "";
  if (f.interval_calibrated === false) {
    return {
      label: "volatility range (not backtest-calibrated)",
      tested: false,
      summary: "Uncalibrated range: at this horizon there are too few independent backtest periods to calibrate an interval, so this is a volatility range around today’s price, not a tested 80% interval. The point estimate is shown for reference and is mostly noise." + why,
    };
  }
  if (c) {
    return {
      label: "80% range (coverage not verified)",
      tested: false,
      summary: "This range comes from how wrong the model was on past data it had not seen, but we could not verify how often it would have been right." + why,
    };
  }
  return { label: "80% interval", tested: false, summary: "" }; // older saved response without the conformal fields
}
