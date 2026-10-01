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
      return json({ symbol: p.split("/").pop(), horizon_days: h, last_close: 124, last_date: "2026-09-30", predicted_return: 0.01, predicted_price: 125.2, interval_80: { low: 118, high: 131 }, path: fcPath, backtest: mkBacktest(h), notes: ["Interval is empirical."], disclaimer: "Educational only.", ...fresh }); }
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
  await page.getByRole("button", { name: "10d", exact: true }).click();
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
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("table").first().waitFor({ timeout: 15000 });
  await axe(page, `[${scheme}] compare`);
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
