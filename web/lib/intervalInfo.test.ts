import assert from "node:assert/strict";
import { test } from "node:test";
import { intervalInfo } from "./intervalInfo";
import type { Conformal } from "./types";

const base: Conformal = {
  used: true, method: "m", target_coverage: 0.8, multiplier: 1.4, normal_multiplier: 1.28,
  n_calibration: 600, n_calibration_independent: 120, measured_coverage: 0.81, measured_coverage_ci_90: [0.73, 0.87],
  n_evaluation: 495, n_evaluation_independent: 99, supported: true, reason_not_used: null, fallback: null,
};

test("a used conformal range reports measured coverage, its plausible range and sample sizes", () => {
  const i = intervalInfo({ interval_calibrated: true, interval_method_name: "split_conformal", horizon_days: 5, conformal: base });
  assert.equal(i.tested, true);
  assert.match(i.summary, /81% of the time/);
  assert.match(i.summary, /73% to 87%/);
  assert.match(i.summary, /99 independent 5-day periods/);
  assert.match(i.summary, /600 past forecasts/);
  assert.equal(i.caveat, undefined);
});

test("under- and over-coverage get an explicit caveat", () => {
  const under = intervalInfo({ interval_calibrated: true, horizon_days: 20, conformal: { ...base, measured_coverage: 0.66 } });
  assert.match(under.caveat ?? "", /below the 80% target/);
  const over = intervalInfo({ interval_calibrated: true, horizon_days: 20, conformal: { ...base, measured_coverage: 0.93 } });
  assert.match(over.caveat ?? "", /wider than needed/);
});

test("an unused conformal result on a long horizon stays labelled uncalibrated and explains why", () => {
  const i = intervalInfo({
    interval_calibrated: false, horizon_days: 256,
    conformal: { ...base, used: false, supported: false, reason_not_used: "the history holds only about 5 independent 256-day test periods", fallback: "volatility_cone" },
  });
  assert.equal(i.tested, false);
  assert.match(i.label, /not backtest-calibrated/);
  assert.match(i.summary, /only about 5 independent 256-day test periods/);
});

test("short-horizon fallback does not claim the range was verified", () => {
  const i = intervalInfo({
    interval_calibrated: true, horizon_days: 5,
    conformal: { ...base, used: false, supported: false, reason_not_used: "too short", fallback: "walk_forward_residuals" },
  });
  assert.equal(i.tested, false);
  assert.match(i.label, /not verified/);
});

test("responses saved before the conformal fields existed still render", () => {
  assert.equal(intervalInfo({ interval_calibrated: true, horizon_days: 5 }).label, "80% interval");
  assert.match(intervalInfo({ interval_calibrated: false, horizon_days: 120 }).label, /not backtest-calibrated/);
  assert.equal(intervalInfo(undefined).label, "80% interval");
});
