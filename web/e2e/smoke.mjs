// CI smoke test: runs fully offline. The API is mocked with Playwright routes, so no backend or market data is needed.
//   Web must be built with NEXT_PUBLIC_API_BASE_URL=http://api.test and served on WEB (default http://localhost:3000).
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const axeSource = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");
const WEB = process.env.WEB || "http://localhost:3000";
const API = "http://api.test";
let failures = 0;
const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"}  ${m}`); if (!c) failures++; };

const fresh = { data_as_of: "2026-09-30", fetched_at: "2026-10-01T12:00:00Z", is_delayed: false, stale: false, warnings: [] };
const dates = Array.from({ length: 120 }, (_, i) => new Date(Date.UTC(2026, 3, 1 + i * 1.4)).toISOString().slice(0, 10));
const closes = dates.map((_, i) => 100 + i * 0.2 + Math.sin(i / 5) * 3);
const fcPath = Array.from({ length: 5 }, (_, i) => ({ date: `2026-10-0${i + 1}`, mid: 125 + i, low: 120 + i, high: 130 + i }));
const mkBacktest = (h) => ({ method: `expanding-window walk-forward, 6 folds, ${h}-day embargo`, embargo_days: h, horizon_days: h, n_test_points: 600, n_independent_tests: Math.floor(600 / h),
  small_sample: false, up_rate: 0.56, skill_ci_90: [-0.08, -0.01], model: { rmse: 0.03, mae: 0.02, directional_accuracy: 0.5 },
  naive_baseline: { rmse: 0.028, mae: 0.019, directional_accuracy: 0.56 }, skill_vs_baseline: -0.04, beats_baseline: false, note: "Indicative only." });
const row = (symbol, v) => ({ symbol, verdict: v, skill_vs_baseline: v === "better" ? 0.05 : -0.04, skill_ci_90: v === "better" ? [0.01, 0.09] : [-0.08, 0.01], model_rmse: 0.03,
  baseline_rmse: 0.029, hit_rate: 0.52, up_rate: 0.57, n_test_points: 600, n_independent_tests: 120, small_sample: false, data_as_of: "2026-09-30" });

const sc0 = { verdict: "no_data", n_resolved: 0, n_pending: 0, n_dates: 0, n_independent: 0, min_for_verdict: 30 };
const emptyLog = { items: [], total: 0, limit: 25, offset: 0, scorecard: sc0, chain_ok: true, symbols: ["SPY", "AAPL"], horizon_days: 5, storage: { backend: "sqlite", durable: false }, disclaimer: "Educational only.", ...fresh };
const logRow = (id, status) => ({ id, symbol: id % 2 ? "SPY" : "AAPL", horizon_days: 5, made_at: `2026-09-${10 + id}T22:30:00Z`, base_date: `2026-09-${10 + id}`, base_close: 100, predicted_return: 0.004, interval_low: 95, interval_high: 106,
  backtest_skill: -0.03, model: "gbm", status, resolved_at: status === "resolved" ? "2026-09-30T22:30:00Z" : null, realized_date: status === "resolved" ? "2026-09-30" : null, realized_close: status === "resolved" ? 101 : null,
  realized_return: status === "resolved" ? 0.01 : null, entry_hash: "ab".repeat(32), ...(status === "resolved" ? { in_interval: true, direction_correct: true } : {}) });
const fullLog = { ...emptyLog, items: [logRow(2, "resolved"), logRow(1, "pending")], total: 2, scorecard: { ...sc0, verdict: "too_early", n_resolved: 1, n_pending: 1, n_dates: 1, n_independent: 1, horizon_days: 5, skill_vs_naive: -0.02, skill_ci_90: null,
  hit_rate: 1, up_rate: 1, interval_coverage: 1, interval_nominal: 0.8 } };

async function mockApi(context) {
  await context.route(`${API}/**`, async (route) => {
    const u = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
    const p = u.pathname;
    if (p.startsWith("/api/quote/")) return json({ symbol: p.split("/").pop(), price: 125, previous_close: 124, change: 1, change_percent: 0.8, as_of: "2026-09-30", ...fresh, note: "" });
    if (p.startsWith("/api/history/")) return json({ symbol: p.split("/").pop(), range: "6mo", points: dates.map((d, i) => ({ date: d, close: closes[i], volume: 1000 })), ...fresh });
    if (p.startsWith("/api/forecast/")) { const h = Number(u.searchParams.get("horizon") || 5);
      return json({ symbol: p.split("/").pop(), horizon_days: h, last_close: 124, last_date: "2026-09-30", predicted_return: 0.01, predicted_price: 125.2, interval_80: { low: 118, high: 131 }, interval_calibrated: h < 120, path: fcPath, backtest: mkBacktest(h), notes: ["Interval is empirical."], disclaimer: "Educational only.", ...fresh }); }
    if (p === "/api/search") return json({ results: [{ symbol: "AAPL", name: "Apple Inc.", exchange: "NMS" }, { symbol: "AMD", name: "Advanced Micro Devices", exchange: "NMS" }] });
    if (p.startsWith("/api/news/")) return json({ symbol: "AAPL", items: [{ headline: "Example headline", source: "Wire", url: "https://example.com/a", published_at: "2026-09-30T13:00:00Z" }], note: "context", ...fresh });
    if (p === "/api/compare") return json({ range: "6mo", dates: ["2026-04-01", "2026-09-30"], series: ["AAPL", "MSFT", "NVDA"].map((s, i) => ({ symbol: s, start_price: 100, end_price: 110 + i, change_percent: 10 + i, points: [0, 10 + i] })), failed: [], base: "Percent change.", ...fresh });
    if (p === "/api/model-report") return json({ horizon_days: 5, rows: [row("SPY", "not_better"), row("AAPL", "inconclusive"), row("MSFT", "better")], failed: [], method: "walk-forward",
      summary: { better: 1, inconclusive: 1, not_better: 1, total: 3 }, disclaimer: "Educational only.", ...fresh });
    if (p.startsWith("/api/compare-models/")) { const h = Number(u.searchParams.get("horizon") || 5);
      const m = (model, label, verdict, skill) => ({ model, label, description: "desc", rmse: 0.03, mae: 0.02, hit_rate: verdict === "baseline" ? null : 0.51, skill_vs_naive: skill, skill_ci_90: verdict === "baseline" ? [0, 0] : [skill - 0.04, skill + 0.04], beats_naive: verdict === "better", verdict });
      return json({ symbol: p.split("/").pop(), horizon_days: h, embargo_days: h, n_folds: 6, n_test_points: 600, n_independent_tests: 600 / h, small_sample: false, up_rate: 0.56, method: "wf",
        models: [m("naive", "Naive: price stays flat", "baseline", 0), m("drift", "Drift", "inconclusive", 0.01), m("gbm", "Gradient boosting", "not_better", -0.07)], any_beats_naive: false, n_candidates: 2, note: "Tested several models.", disclaimer: "Educational only.", ...fresh }); }
    if (p.startsWith("/api/volatility/")) { const h = Number(u.searchParams.get("horizon") || 5);
      const vm = (model, verdict, skill) => ({ model, label: model.toUpperCase() + " model", description: "d", typical_error_pct: 40, skill_vs_naive: skill, skill_ci_90: [skill - 0.05, skill + 0.05], beats_naive: false, verdict, forecast_daily_vol: 0.012, annualized_vol: 0.19 });
      return json({ symbol: p.split("/").pop(), horizon_days: h, last_close: 124, headline_model: "ewma", forecast_daily_vol: 0.012, annualized_vol: 0.19, horizon_vol: 0.027,
        risk_range: { one_sigma_pct: 2.7, low: 120.7, high: 127.4, nominal_coverage: 0.68, backtest_coverage: 0.72 }, verdict: "inconclusive", skill_vs_naive: 0.01, skill_ci_90: [-0.04, 0.06],
        models: [vm("naive", "baseline", 0), vm("ewma", "inconclusive", 0.01)], n_test_points: 600, n_independent_tests: 120, small_sample: false, embargo_days: h, method: "wf", notes: ["Fat tails exist."], disclaimer: "Educational only.", ...fresh }); }
    if (p === "/api/trending") { if (globalThis.__trendingFail) return json({ error: { code: "DATA_UNAVAILABLE", message: "x", retryable: true } }, 502);
      return json({ days: 3, limit: 5, items: [["AAPL", "Apple Inc.", 6.1], ["NVDA", "NVIDIA Corporation", 5.2], ["AMD", "Advanced Micro Devices, Inc.", 4.4], ["META", "Meta Platforms, Inc.", 3.9], ["TSLA", "Tesla, Inc.", 3.1]]
        .map(([symbol, name, r], i) => ({ rank: i + 1, symbol, name, return_percent: r, last_close: 120 + i, as_of: "2026-09-30" })), universe_size: 106, evaluated: 104, method: "close-to-close", note: "A plain momentum screen, not a recommendation or a prediction.", disclaimer: "Educational only.", ...fresh }); }
    if (p.startsWith("/api/timeline/")) { if (globalThis.__timelineFail) return json({ error: { code: "DATA_UNAVAILABLE", message: "x", retryable: true } }, 502);
      const rg = u.searchParams.get("range") || "6mo"; const n = { "1mo": 21, "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "5y": 400 }[rg]; const pts = Array.from({ length: Math.min(n, 120) }, (_, i) => ({ date: `2026-${String(1 + Math.floor(i / 28)).padStart(2, "0")}-${String(1 + (i % 28)).padStart(2, "0")}`, close: 100 + i * 0.5 + Math.sin(i / 4) * 4 }));
      return json({ symbol: p.split("/").pop(), range: rg, points: pts, n_points_total: n, downsampled: n > 120, summary: { start_date: pts[0].date, end_date: pts.at(-1).date, start_close: pts[0].close, end_close: pts.at(-1).close, period_return_pct: 59.5, high: 163.9, high_date: "2026-05-02", low: 96.2, low_date: "2026-01-03", max_drawdown_pct: -12.3 },
        note: "Adjusted closing prices. Past performance does not predict future results.", disclaimer: "Educational only.", ...fresh }); }
    if (p.startsWith("/api/spikes/")) { globalThis.__spikeCalls = (globalThis.__spikeCalls ?? 0) + 1; if (globalThis.__spikeFail) return json({ error: { code: "INSUFFICIENT_DATA", message: "Need at least 250 daily bars, got 100", retryable: false } }, 422);
      const h = Number(u.searchParams.get("horizon") || 5); const rg = (cov, gain, v) => ({ coverage: cov, mean_width: 0.08, interval_score: 0.11, ...(gain === undefined ? {} : { score_gain_vs_baseline: gain, score_gain_ci_90: [gain - 0.05, gain + 0.05], verdict: v }) });
      return json({ experimental: true, symbol: p.split("/").pop(), horizon_days: h, last_close: 124, last_date: "2026-09-30", baseline_interval: { low: 118, high: 131 },
        model: { name: "jump-diffusion Monte Carlo (experimental)", n_paths: 2000, seed: 42, bounds: "clamped: each day's simulated price is clipped to the standard forecast's normal band", jump_threshold_sigma: 2.5, calibration_days: 504 },
        calibration: { robust_sigma_daily: 0.012, diffusion_sigma_daily: 0.011, jump_threshold_pct: 3.1, n_jumps_up: 9, n_jumps_down: 12, jump_freq_up_per_day: 0.018, jump_freq_down_per_day: 0.024, mean_jump_up_pct: 4, mean_jump_down_pct: -4.2, few_jumps: false },
        path: fcPath.slice(0, Math.min(h, 5)).map((q, i) => ({ date: q.date, baseline_mid: q.mid, band_low: q.low, band_high: q.high, median: q.mid, mean: q.mid, sim_low: q.low + 1, sim_high: q.high - 1, spike_up: q.high - 1, spike_down: q.low + 1, p_jump_up: 0.04 * (i + 1), p_jump_down: 0.05 * (i + 1), p_touch_high: 0.03, p_touch_low: 0.04 })),
        sample_paths: [fcPath.slice(0, Math.min(h, 5)).map((q) => q.mid)],
        clamping: { method: "clip", fraction_of_path_days_clamped: 0.18, fraction_of_paths_touching_band: 0.35, terminal_at_high: 0.07, terminal_at_low: 0.05 },
        backtest: { available: true, n_origins: 100, horizon_days: h, small_sample: false, nominal_coverage: 0.8, embargo_days: h, method: "wf", baseline: rg(0.8), jump_unclamped: rg(0.9, -0.05, "worse"), spike_clamped: rg(0.78, 0.01, "inconclusive"),
          point: { baseline_rmse: 0.04, spike_median_rmse: 0.04, naive_rmse: 0.039, skill_vs_baseline: 0, skill_ci_90: [-0.01, 0.01], verdict: "inconclusive" }, mean_clamped_fraction_at_horizon: 0.2, summary: "Over 100 past forecast dates the standard 80% band contained the outcome 80% of the time." },
        notes: ["Spikes are simulated from this stock's own past jump frequency and size. They are not predictions."], disclaimer: "Educational only.", ...fresh }); }
    if (p === "/api/prediction-log") return json(globalThis.__log ?? emptyLog);
    return json({ error: { code: "NOT_FOUND", message: "unmocked", retryable: false } }, 404);
  });
}

async function axe(page, label) {
  await page.evaluate(axeSource);
  const res = await page.evaluate(async () => await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } })); // eslint-disable-line no-undef
  const v = res.violations.map((x) => `${x.id}(${x.impact}): ${x.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  ok(v.length === 0, `axe: ${label}${v.length ? "\n      " + v.join("\n      ") : ""}`);
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"], headless: true });
for (const scheme of ["light", "dark"]) {
  const context = await browser.newContext({ colorScheme: scheme, viewport: { width: 1200, height: 900 } });
  await mockApi(context);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(WEB);
  await page.getByRole("dialog").waitFor({ timeout: 30000 });
  ok(!(await page.locator("[data-gated]").first().isVisible()), `[${scheme}] disclaimer gate blocks the app until accepted`);
  await axe(page, `[${scheme}] gate`);
  await page.getByRole("button", { name: /I understand/i }).click();
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 30000 });
  await page.getByRole("heading", { name: "Recent headlines" }).waitFor();
  ok(await page.getByText(/not a trading signal/i).first().isVisible(), `[${scheme}] news labelled as context`);
  ok((await page.locator("[aria-labelledby=bt-title]").innerText()).match(/guessing/i) !== null, `[${scheme}] plain-language backtest verdict shown`);
  await page.waitForLoadState("networkidle");
  await axe(page, `[${scheme}] home / forecast`);
  await page.getByRole("button", { name: "10d, 10 trading days", exact: true }).click();
  await page.getByText("(10-trading-day forecasts)").waitFor({ timeout: 15000 });
  ok(true, `[${scheme}] horizon switch updates the verdict heading`);
  await page.getByRole("heading", { name: /Expected range \/ risk/ }).waitFor();
  await page.getByText(/Typical move over 10 trading days/).waitFor({ timeout: 15000 });
  ok(await page.getByText(/not which direction/).isVisible(), `[${scheme}] volatility panel says it is not a direction call`);
  await page.getByText(/Model comparison \(AAPL, 10-trading-day/).waitFor({ timeout: 15000 });
  ok(true, `[${scheme}] stock view shows model comparison for the chosen horizon`);
  await page.getByText(/No model clearly beat/).first().waitFor();
  await page.waitForLoadState("networkidle");
  await axe(page, `[${scheme}] stock view with volatility + model comparison`);
  // history range on the main chart: six options, default 6M, summary, range switch, % view, table, error state, no separate timeline section
  ok((await page.getByRole("heading", { name: /Performance timeline/ }).count()) === 0, `[${scheme}] no separate Performance timeline section`);
  const rangeGroup = page.getByRole("group", { name: "History range shown on the chart" });
  const labels = await rangeGroup.getByRole("button").allInnerTexts();
  ok(JSON.stringify(labels) === JSON.stringify(["1M", "3M", "6M", "1Y", "2Y", "5Y"]), `[${scheme}] chart offers 1M, 3M, 6M, 1Y, 2Y, 5Y (${labels.join(" ")})`);
  ok((await rangeGroup.getByRole("button", { name: "6M, 6 months", exact: true }).getAttribute("aria-pressed")) === "true", `[${scheme}] chart range defaults to 6M`);
  ok(await page.getByText("Worst drop from a peak").isVisible() && await page.getByText(/Return over 6 months/).isVisible(), `[${scheme}] range summary (return/high/low/drawdown) shown on the chart`);
  await rangeGroup.getByRole("button", { name: "5Y, 5 years", exact: true }).click();
  await page.getByText(/Return over 5 years/).waitFor({ timeout: 15000 });
  ok(await page.getByText(/The chart shows 120 of 400 trading days/).isVisible(), `[${scheme}] downsampling is disclosed`);
  ok(await page.getByText(/Experimental \d+-day estimate/).isVisible(), `[${scheme}] forecast stays visible when the range changes`);
  ok((await rangeGroup.getByRole("button", { name: "5Y, 5 years", exact: true }).getAttribute("aria-pressed")) === "true", `[${scheme}] range switch (5Y)`);
  await page.reload();
  await page.getByRole("group", { name: "History range shown on the chart" }).waitFor({ timeout: 30000 });
  ok((await page.getByRole("group", { name: "History range shown on the chart" }).getByRole("button", { name: "5Y, 5 years", exact: true }).getAttribute("aria-pressed")) === "true", `[${scheme}] chosen range is remembered after reload`);
  await page.evaluate(() => localStorage.setItem("chart.range.v1", "{corrupt"));
  await page.reload();
  await page.getByRole("group", { name: "History range shown on the chart" }).waitFor({ timeout: 30000 });
  ok((await page.getByRole("group", { name: "History range shown on the chart" }).getByRole("button", { name: "6M, 6 months", exact: true }).getAttribute("aria-pressed")) === "true", `[${scheme}] corrupt saved range falls back to 6M`);
  await page.getByLabel(/Show as % change from the start of the range/).check();
  await page.getByText("View chart data as a table").click();
  const rows = await page.locator("details table tbody tr").count();
  ok(rows >= 120, `[${scheme}] chart table lists history and forecast rows (${rows})`);
  await page.waitForLoadState("networkidle");
  await axe(page, `[${scheme}] chart with range selector, % view and table open`);
  await page.getByLabel(/Show as % change from the start of the range/).uncheck();
  // long-horizon warning and 256d option
  for (const h of ["5d", "10d", "20d", "60d", "120d", "180d", "256d"]) ok((await page.getByRole("button", { name: `${h}, ${h.replace("d", "")} trading days`, exact: true }).count()) === 1, `[${scheme}] horizon option ${h}`);
  await page.getByRole("button", { name: "256d, 256 trading days", exact: true }).click();
  await page.getByText(/Long-horizon forecasts \(256 trading days/).waitFor({ timeout: 15000 });
  ok(await page.getByText(/highly uncertain/).first().isVisible(), `[${scheme}] long-horizon uncertainty note shown at 256d`);
  await page.getByRole("button", { name: "10d, 10 trading days", exact: true }).click();
  ok((await page.getByText(/Long-horizon forecasts/).count()) === 0, `[${scheme}] long-horizon note hidden for short horizons`);
  await page.getByText("(10-trading-day forecasts)").waitFor({ timeout: 15000 });
  globalThis.__timelineFail = true;
  await page.evaluate(() => Object.keys(localStorage).filter((k) => k.includes("timeline")).forEach((k) => localStorage.removeItem(k)));
  await page.getByRole("group", { name: "History range shown on the chart" }).getByRole("button", { name: "1Y, 1 year", exact: true }).click();
  await page.getByText("Price history").first().waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: /retry|try again/i }).first().waitFor({ timeout: 20000 });
  ok(true, `[${scheme}] chart history error state offers retry`);
  globalThis.__timelineFail = false;
  await page.getByRole("button", { name: "1Y, 1 year", exact: true }).click().catch(() => {});
  // experimental spike scenario: off by default (nothing fetched), toggle on, badge + simulated-not-predicted text, table, error state
  ok(await page.getByText("Experimental", { exact: true }).first().isVisible(), `[${scheme}] spike panel carries an Experimental badge`);
  ok(!(await page.getByRole("checkbox", { name: "Show spike scenario" }).isChecked()) && !globalThis.__spikeCalls, `[${scheme}] spike scenario is off by default and not fetched`);
  ok(await page.getByText(/simulated, not predicted/i).first().isVisible(), `[${scheme}] says spikes are simulated, not predicted`);
  await page.getByRole("checkbox", { name: "Show spike scenario" }).check();
  await page.getByText(/Did it help in past tests/).waitFor({ timeout: 15000 });
  ok(await page.getByText(/clamped/i).first().isVisible(), `[${scheme}] spike panel states values are clamped to the normal range`);
  await page.getByText("Spike bands as a table").click();
  ok((await page.locator("section[aria-labelledby=spike-title] table tbody tr").count()) === 5, `[${scheme}] spike bands table rows`);
  await page.waitForLoadState("networkidle");
  await axe(page, `[${scheme}] spike scenario on`);
  globalThis.__spikeFail = true;
  await page.getByRole("button", { name: "20d, 20 trading days", exact: true }).click();
  await page.getByRole("button", { name: /retry|try again/i }).last().waitFor({ timeout: 20000 });
  ok(true, `[${scheme}] spike scenario error state offers retry`);
  globalThis.__spikeFail = false; globalThis.__spikeCalls = 0;
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("table").first().waitFor({ timeout: 15000 });
  await axe(page, `[${scheme}] compare`);
  // lists: Trending is the default, read-only; user lists are create/rename/delete-able and persisted
  await page.goto(WEB);
  await page.getByRole("combobox", { name: "List", exact: true }).waitFor({ timeout: 30000 });
  const sel = page.getByRole("combobox", { name: "List", exact: true });
  ok((await sel.inputValue()) === "trending", `[${scheme}] Trending (3-day) is the default list`);
  await page.getByRole("list", { name: /Trending \(3-day\), read-only/ }).waitFor();
  ok((await page.getByRole("list", { name: /Trending/ }).locator("> li").count()) === 5, `[${scheme}] trending shows 5 tickers`);
  ok(await page.getByText(/not a recommendation or a prediction/i).first().isVisible(), `[${scheme}] trending says it is not a recommendation`);
  ok((await page.getByRole("button", { name: /Remove .* from this list/ }).count()) === 0, `[${scheme}] trending rows have no remove buttons`);
  ok((await page.getByRole("button", { name: "Rename" }).count()) === 0, `[${scheme}] built-in list cannot be renamed`);
  await axe(page, `[${scheme}] trending list`);
  await page.getByRole("button", { name: "New list" }).click();
  await page.getByLabel("Name of the new list").fill("Trending");
  await page.getByRole("button", { name: "Create" }).click();
  ok(await page.getByRole("alert").filter({ hasText: /reserved/ }).isVisible(), `[${scheme}] reserved name rejected inline`);
  await page.getByLabel("Name of the new list").fill("Tech picks");
  await page.getByRole("button", { name: "Create" }).click();
  ok((await sel.inputValue()) !== "trending", `[${scheme}] new list is created and selected`);
  await page.getByText(/This list is empty/).first().waitFor();
  await sel.selectOption("trending");
  await page.getByLabel("Add NVDA to one of your lists").selectOption({ label: "Tech picks" });
  await page.getByText("Added NVDA to Tech picks.").first().waitFor({ state: "attached" });
  await sel.selectOption({ label: "Tech picks (1)" });
  ok((await page.getByRole("list", { name: /Tech picks tickers/ }).locator("> li").count()) === 1, `[${scheme}] ticker copied from Trending into the user list`);
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel(/New name for/).fill("Chips");
  await page.getByRole("button", { name: "Save" }).click();
  await sel.selectOption({ label: "Chips (1)" });
  await page.reload();
  await page.getByRole("combobox", { name: "List", exact: true }).waitFor({ timeout: 30000 });
  ok((await page.getByRole("combobox", { name: "List", exact: true }).locator("option:checked").innerText()).startsWith("Chips"), `[${scheme}] last-selected list persists across reload`);
  await axe(page, `[${scheme}] user list`);
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("alertdialog").waitFor();
  await page.getByRole("button", { name: "Cancel" }).click();
  ok((await page.getByRole("combobox", { name: "List", exact: true }).locator("option").count()) === 3, `[${scheme}] cancelling delete keeps the list`);
  await page.waitForFunction(() => document.activeElement?.tagName === "SELECT", null, { timeout: 3000 }).catch(() => {});
  ok(await page.evaluate(() => document.activeElement?.tagName === "SELECT"), `[${scheme}] focus returns to the list picker after cancel`);
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Yes, delete" }).click();
  ok((await page.getByRole("combobox", { name: "List", exact: true }).locator("option").count()) === 2, `[${scheme}] list deleted after confirm`);
  ok(await page.evaluate(() => document.activeElement?.tagName === "SELECT"), `[${scheme}] focus returns to the list picker after delete`);
  // search box is a real combobox: arrow keys + Enter, Escape closes, focus stays in the input
  const search = page.getByRole("combobox", { name: "Search symbol" });
  await search.fill("ap");
  await page.getByRole("option", { name: /AAPL/ }).waitFor();
  ok((await search.getAttribute("aria-expanded")) === "true", `[${scheme}] search combobox expands with suggestions`);
  await search.press("ArrowDown");
  ok((await page.getByRole("option", { name: /AAPL/ }).getAttribute("aria-selected")) === "true" && !!(await search.getAttribute("aria-activedescendant")), `[${scheme}] arrow key highlights an option (aria-activedescendant)`);
  await search.press("Escape");
  ok((await search.getAttribute("aria-expanded")) === "false" && (await page.getByRole("listbox", { name: "Search suggestions" }).count()) === 0, `[${scheme}] Escape closes the suggestions`);
  await search.fill("am");
  await page.getByRole("option", { name: /AMD/ }).waitFor();
  await search.press("ArrowDown"); await search.press("ArrowDown"); await search.press("Enter");
  await page.getByRole("heading", { name: "AMD", exact: true }).waitFor();
  ok(true, `[${scheme}] Enter picks the highlighted suggestion`);
  // legacy watchlist migration + corrupt data
  await page.evaluate(() => { localStorage.removeItem("lists.v2"); localStorage.setItem("watchlist.v1", JSON.stringify(["AAPL", "TSLA"])); });
  await page.reload();
  await page.getByRole("combobox", { name: "List", exact: true }).selectOption({ label: "My watchlist (2)" });
  ok(await page.getByRole("list", { name: /My watchlist tickers/ }).getByText("TSLA").isVisible(), `[${scheme}] legacy watchlist migrated to "My watchlist"`);
  await page.evaluate(() => localStorage.setItem("lists.v2", "{not json"));
  await page.reload();
  await page.getByRole("combobox", { name: "List", exact: true }).waitFor({ timeout: 30000 });
  ok(await page.getByRole("list", { name: /Trending/ }).isVisible(), `[${scheme}] corrupt saved lists fall back to Trending without crashing`);
  // trending failure state
  globalThis.__trendingFail = true;
  await page.evaluate(() => Object.keys(localStorage).filter((k) => k.includes("trending")).forEach((k) => localStorage.removeItem(k)));
  await page.reload();
  await page.getByRole("combobox", { name: "List", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: /retry|try again/i }).first().waitFor({ timeout: 20000 });
  ok(true, `[${scheme}] trending error state offers retry`);
  globalThis.__trendingFail = false;
  await page.goto(`${WEB}/model`);
  await page.getByRole("table").first().waitFor({ timeout: 15000 });
  ok((await page.getByRole("dialog").count()) === 0, `[${scheme}] /model is gate-exempt`);
  ok((await page.locator("section[aria-labelledby=report-title] table tbody tr").count()) === 3, `[${scheme}] /model report table rows`);
  await axe(page, `[${scheme}] /model`);
  // model comparison on /model (explorer) and in the stock view was checked above via /model; stock view:
  await page.goto(`${WEB}/model`);
  await page.getByText("Model comparison", { exact: false }).first().waitFor();
  await page.getByText(/No model clearly beat/).waitFor({ timeout: 15000 });
  ok((await page.locator("section[aria-labelledby^=mc-title] table tbody tr").count()) === 3, `[${scheme}] /model: model comparison table rows`);
  await axe(page, `[${scheme}] /model with model comparison`);
  // track record: empty state, then populated
  globalThis.__log = emptyLog;
  await page.goto(`${WEB}/track-record`);
  ok((await page.getByRole("dialog").count()) === 0, `[${scheme}] /track-record is gate-exempt`);
  await page.getByText(/No resolved predictions yet/).waitFor({ timeout: 15000 });
  ok(await page.getByText(/Pre-registered, not edited after the fact/).isVisible(), `[${scheme}] pre-registered explanation shown`);
  ok(await page.getByText(/erased whenever the server redeploys/).isVisible(), `[${scheme}] ephemeral-storage caveat shown`);
  ok(await page.getByText(/log is empty/).isVisible(), `[${scheme}] empty-state shown`);
  await axe(page, `[${scheme}] /track-record (empty)`);
  globalThis.__log = fullLog;
  await page.goto(`${WEB}/track-record`);
  await page.getByText(/Too early to say/).waitFor({ timeout: 15000 });
  ok((await page.locator("section[aria-labelledby=log] tbody tr").count()) === 2, `[${scheme}] track-record rows`);
  ok(await page.getByText(/Waiting \(resolves after 5 trading days\)/).isVisible(), `[${scheme}] pending prediction shown as waiting`);
  ok(await page.getByText(/Live results only/).isVisible(), `[${scheme}] live vs backtest distinction stated`);
  await axe(page, `[${scheme}] /track-record (populated)`);
  for (const path of ["/terms", "/privacy"]) { await page.goto(`${WEB}${path}`); await axe(page, `[${scheme}] ${path}`); }
  ok(errors.length === 0, `[${scheme}] no uncaught page errors ${errors.join("; ")}`);
  await context.close();
}
await browser.close();
console.log(failures ? `\n${failures} check(s) FAILED` : "\nAll smoke checks passed");
process.exit(failures ? 1 : 0);
