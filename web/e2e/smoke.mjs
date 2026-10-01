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
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("table").first().waitFor({ timeout: 15000 });
  await axe(page, `[${scheme}] compare`);
  await page.goto(`${WEB}/model`);
  await page.getByRole("table").waitFor({ timeout: 15000 });
  ok((await page.getByRole("dialog").count()) === 0, `[${scheme}] /model is gate-exempt`);
  ok((await page.locator("table tbody tr").count()) === 3, `[${scheme}] /model table rows`);
  await axe(page, `[${scheme}] /model`);
  for (const path of ["/terms", "/privacy"]) { await page.goto(`${WEB}${path}`); await axe(page, `[${scheme}] ${path}`); }
  ok(errors.length === 0, `[${scheme}] no uncaught page errors ${errors.join("; ")}`);
  await context.close();
}
await browser.close();
console.log(failures ? `\n${failures} check(s) FAILED` : "\nAll smoke checks passed");
process.exit(failures ? 1 : 0);
