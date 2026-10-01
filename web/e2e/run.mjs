// Headless-browser checks against a running web app + API (not part of CI).
//   API:  cd backend && uvicorn app.main:app --port 8000
//   Web:  cd web && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run build && npx next start -p 3000
//   Run:  cd web/e2e && npm install && node run.mjs     (WEB, CHROME env vars optional)
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const WEB = process.env.WEB || "http://localhost:3000";
const CHROME = process.env.CHROME || "/usr/bin/google-chrome";
let failures = 0;
const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"}  ${m}`); if (!c) failures++; };

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"], headless: true });

async function fresh({ dark = false, accept = true } = {}) {
  const context = await browser.newContext({ colorScheme: dark ? "dark" : "light", viewport: { width: 1200, height: 900 } });
  await context.grantPermissions([], {});
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(WEB);
  if (accept) {
    await page.getByRole("button", { name: /I understand/i }).click();
    await page.waitForSelector("html[data-ack]");
  }
  return { context, page, errors };
}

async function axe(page, label) {
  await page.evaluate(axeSource);
  const res = await page.evaluate(async () =>
    // eslint-disable-next-line no-undef
    await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } }));
  const v = res.violations.map((x) => `${x.id}(${x.impact}): ${x.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  ok(v.length === 0, `axe: ${label}${v.length ? "\n      " + v.join("\n      ") : ""}`);
}

const settle = (page) => page.waitForLoadState("networkidle").catch(() => {});

// ---- 1. Disclaimer gate still blocks until accepted; axe on gate
{
  const { context, page } = await fresh({ accept: false });
  await page.getByRole("dialog").waitFor();
  ok(true, "gate dialog shown on first visit");
  ok(!(await page.locator("[data-gated]").first().isVisible()), "app content hidden behind the gate");
  await axe(page, "disclaimer gate (light)");
  await context.close();
}

// ---- 2. Main flows (light)
{
  const { context, page, errors } = await fresh();
  ok((await page.locator("html").getAttribute("lang")) === "en", "html lang=en");
  // skip link is first tab stop and moves focus to main
  await page.reload(); await page.waitForSelector("html[data-ack]");
  await page.keyboard.press("Tab");
  ok((await page.evaluate(() => document.activeElement?.textContent)) === "Skip to main content", "skip link is first focusable");
  await page.keyboard.press("Enter");
  ok((await page.evaluate(() => document.activeElement?.id)) === "main", "skip link focuses <main>");

  await page.getByRole("heading", { name: "Recent headlines" }).waitFor({ timeout: 60000 });
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 90000 });
  await settle(page);
  ok(await page.getByText(/not a trading signal/i).first().isVisible(), "news labelled 'not a trading signal'");
  const newsLinks = await page.locator("section[aria-labelledby=news-title] a").evaluateAll((as) => as.map((a) => [a.rel, a.target, a.href]));
  ok(newsLinks.every(([rel, t, h]) => rel.includes("noopener") && t === "_blank" && h.startsWith("http")), `news links safe (${newsLinks.length} items; empty state is also valid)`);
  await axe(page, "home, forecast view (light)");

  // horizon switch: request uses new horizon and the verdict heading follows it
  const waitFc = page.waitForResponse((r) => r.url().includes("/api/forecast/") && r.url().includes("horizon=20"), { timeout: 90000 });
  await page.getByRole("button", { name: "20d", exact: true }).click();
  const r = await waitFc;
  const body = await r.json();
  ok(r.status() === 200 && body.horizon_days === 20, "horizon=20 request returns a 20-day forecast");
  ok(body.backtest.embargo_days >= 20, `embargo (${body.backtest.embargo_days}) >= horizon (20)`);
  await page.getByText("(20-trading-day forecasts)").waitFor({ timeout: 30000 });
  ok(true, "plain-language backtest heading follows chosen horizon");
  ok((await page.locator("[aria-labelledby=bt-title]").innerText()).match(/guessing|Inconclusive/i) !== null, "plain-language verdict shown for horizon 20");
  ok((await page.getByRole("button", { name: "20d", exact: true }).getAttribute("aria-pressed")) === "true", "horizon button aria-pressed");
  // invalid horizon rejected by the backend
  const bad = await page.evaluate(async (base) => (await fetch(`${base}/api/forecast/AAPL?horizon=999`)).status, process.env.API || "http://localhost:8000");
  ok(bad === 422 || bad === 400, `backend rejects horizon=999 (${bad})`);

  // chart text alternative + table
  await page.getByText("View chart data as a table").click();
  ok((await page.locator("details table tbody tr").count()) > 10, "chart data table has rows incl. forecast");
  await axe(page, "home, forecast view with horizon 20 + table open (light)");

  // ---- alerts
  const priceTxt = await page.locator("ul[aria-label=Watchlist] li button[aria-pressed=true]").first().getAttribute("aria-label");
  await page.getByLabel("Price (USD)").fill("0.5");
  await page.getByLabel(/is$/).selectOption("below");
  await page.getByRole("button", { name: "Add alert" }).click(); // below 0.5: should not fire
  await page.getByLabel(/is$/).selectOption("above");
  await page.getByLabel("Price (USD)").fill("1");
  await page.getByRole("button", { name: "Add alert" }).click(); // above $1: fires
  ok(await page.getByText(/only fire while this app is open/i).isVisible(), "alerts UI states they only fire while the app is open");
  await page.getByRole("region", { name: "Alert notices" }).getByText(/AAPL above \$1\.00/).waitFor({ timeout: 40000 });
  ok(true, `in-app notice fired for 'above $1' (${priceTxt?.split(",").slice(0, 2).join(",")})`);
  ok((await page.getByRole("region", { name: "Alert notices" }).getByText(/AAPL below \$0\.50/).count()) === 0, "'below $0.50' alert did not fire");
  const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => /alert/i.test(k)));
  ok(stored.length === 1, `alerts persisted in localStorage only (${stored})`);
  ok((await page.getByText(/Triggered at/).count()) === 1, "triggered alert shown in list");
  await page.reload();
  await page.getByRole("list", { name: "Your alerts" }).waitFor();
  ok((await page.getByRole("list", { name: "Your alerts" }).locator("li").count()) === 2, "alerts survive reload");
  // validation
  await page.getByLabel("Price (USD)").fill("-3");
  await page.getByRole("button", { name: "Add alert" }).click();
  ok((await page.getByRole("list", { name: "Your alerts" }).locator("li").count()) === 2, "invalid alert price not added");
  await axe(page, "home with alerts list (light)");

  // ---- compare
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("heading", { name: "Compare symbols" }).waitFor();
  await page.getByRole("table").first().waitFor({ timeout: 90000 });
  ok((await page.locator("table tbody tr").count()) >= 2, "compare table lists the selected symbols");
  ok(((await page.locator("[role=img]").first().getAttribute("aria-label")) || "").includes("%"), "compare chart has a text alternative with the numbers");
  ok((await page.locator("table svg line[stroke-dasharray]").count()) >= 2, "legend uses dash patterns, not colour alone");
  const w = page.waitForResponse((r) => r.url().includes("/api/compare") && r.url().includes("range=1y"), { timeout: 60000 });
  await page.getByRole("button", { name: "1y", exact: true }).click();
  ok((await w).status() === 200, "range switch re-queries compare");
  await axe(page, "compare view (light)");
  ok(errors.length === 0, `no page errors (${errors.join("; ")})`);
  await context.close();
}

// ---- 3. Dark mode axe
{
  const { context, page } = await fresh({ dark: true });
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 90000 });
  await settle(page);
  ok(await page.evaluate(() => document.documentElement.classList.contains("dark")), "dark mode active");
  await axe(page, "home forecast view (dark)");
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("table").first().waitFor({ timeout: 90000 });
  await axe(page, "compare view (dark)");
  await page.goto(`${WEB}/privacy`); await axe(page, "/privacy (dark)");
  await page.goto(`${WEB}/terms`); await axe(page, "/terms (dark)");
  await context.close();
}
{
  const { context, page } = await fresh({ accept: false });
  await page.goto(`${WEB}/privacy`); await axe(page, "/privacy (light)");
  ok(await page.getByText(/needs review by a qualified lawyer/i).isVisible(), "/privacy says it still needs lawyer review");
  ok(await page.getByText(/IP addresses/).first().isVisible(), "/privacy describes IP handling");
  await page.goto(`${WEB}/terms`); await axe(page, "/terms (light)");
  await context.close();
}

// ---- 3b. /model page: gate-exempt, honest report card, axe (light + dark)
for (const dark of [false, true]) {
  const { context, page } = await fresh({ dark, accept: false });
  await page.goto(`${WEB}/model`);
  ok((await page.getByRole("dialog").count()) === 0, `/model is gate-exempt (${dark ? "dark" : "light"})`);
  await page.locator("section[aria-labelledby=report-title] table").waitFor({ timeout: 120000 });
  const rows = await page.locator("section[aria-labelledby=report-title] table tbody tr").count();
  ok(rows >= 3, `report card table lists ${rows} tickers`);
  ok(await page.getByText(/not financial advice/i).first().isVisible(), "/model shows the disclaimer");
  ok(await page.getByText(/Not better than guessing|Inconclusive|Better than guessing/).first().isVisible(), "/model shows plain-language verdicts");
  ok((await page.locator("section[aria-labelledby=report-title] table th[scope=col]").count()) >= 6, "report table has proper headers");
  await page.getByText(/No model clearly beat|At least one model beat/).first().waitFor({ timeout: 120000 });
  ok((await page.locator("section[aria-labelledby^=mc-title] table tbody tr").count()) === 5, "model comparison lists 5 models (naive baseline + 4)");
  ok(await page.getByText(/not live results/i).first().isVisible(), "model comparison says backtest, not live");
  await axe(page, `/model (${dark ? "dark" : "light"})`);
  await context.close();
}
{
  const { context, page } = await fresh({ accept: true });
  ok((await page.locator("nav[aria-label=Site] a[href='/model']").count()) === 1, "nav links to /model");
  ok((await page.locator("footer a[href='/model']").count()) === 1, "footer links to /model");
  ok((await page.getByText("Support this project").count()) === 0, "no support link when NEXT_PUBLIC_SUPPORT_URL is unset");
  await context.close();
}
{
  const { context, page } = await fresh({ accept: false });
  await page.route("**/api/model-report", (r) => r.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ error: { code: "DATA_UNAVAILABLE", message: "x", retryable: false } }) }));
  await page.goto(`${WEB}/model`);
  await page.getByText(/Report card unavailable/).waitFor({ timeout: 30000 });
  ok(true, "/model failure state is friendly and the methodology text remains");
  ok(await page.getByText(/Baseline:/).isVisible(), "methodology still visible on failure");
  await axe(page, "/model failure state");
  await context.close();
}

// ---- 3c. Stock view: volatility + model comparison; /track-record populated by the real scheduled task
{
  const { context, page } = await fresh();
  await page.getByRole("heading", { name: /Expected range \/ risk/ }).waitFor({ timeout: 120000 });
  await page.getByText(/Typical move over 5 trading days/).waitFor({ timeout: 120000 });
  await page.getByText(/Model comparison \(AAPL/).waitFor({ timeout: 120000 });
  await page.locator("section[aria-labelledby^=mc-title] table").waitFor({ timeout: 120000 });
  ok(true, "stock view shows volatility range and model comparison from the real backend");
  await page.waitForLoadState("networkidle").catch(() => {});
  await axe(page, "stock view with volatility + model comparison (real data)");
  await context.close();
}
if (process.env.LOG_TASK_TOKEN) {
  const api = process.env.API || "http://localhost:8000";
  const r = await fetch(`${api}/api/_tasks/run-prediction-log`, { method: "POST", headers: { Authorization: `Bearer ${process.env.LOG_TASK_TOKEN}` } });
  const out = await r.json();
  ok(r.status === 200 && out.logged.length > 0, `scheduled task logged predictions (${out.logged.join(",")}) ${JSON.stringify(out.skipped)}`);
  const { context, page } = await fresh({ accept: false });
  await page.goto(`${WEB}/track-record`);
  ok((await page.getByRole("dialog").count()) === 0, "/track-record is gate-exempt");
  await page.locator("section[aria-labelledby=log] tbody tr").first().waitFor({ timeout: 60000 });
  ok((await page.locator("section[aria-labelledby=log] tbody tr").count()) === out.logged.length, "log table shows the logged predictions");
  ok(await page.getByText(/Waiting \(resolves after 5 trading days\)/).first().isVisible(), "new predictions show as waiting, not as results");
  ok(await page.getByText(/Too early|No resolved predictions yet/).first().isVisible(), "no verdict claimed with no resolved data");
  ok(await page.getByText(/chain check right now: intact/).isVisible(), "hash chain reported intact");
  await axe(page, "/track-record (real data)");
  await context.close();
}

// ---- 4. Offline watchlist
{
  const { context, page } = await fresh();
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 90000 });
  await settle(page);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); await settle(page); // let the SW take control and cache the shell
  ok(await page.evaluate(() => !!navigator.serviceWorker.controller), "service worker controls the page");
  const aaplOnline = await page.locator("ul[aria-label=Watchlist] li").first().innerText();
  await page.waitForTimeout(1500);
  await context.setOffline(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByText(/You're offline/).waitFor({ timeout: 15000 });
  ok(true, "app shell loads offline with an 'offline / may be outdated' label");
  const first = page.locator("ul[aria-label=Watchlist] li").first();
  await first.getByText(/\$\d/).waitFor({ timeout: 15000 });
  ok(/\$\d/.test(await first.innerText()), `watchlist shows last-known price offline (was: ${aaplOnline.replace(/\n/g, " ")})`);
  ok(await page.getByText(/may be outdated/i).first().isVisible(), "'may be outdated' wording visible");
  await axe(page, "offline watchlist (light)");
  const cached = await page.evaluate(async () => {
    const urls = [];
    for (const k of await caches.keys()) for (const r of await (await caches.open(k)).keys()) urls.push(new URL(r.url).pathname);
    return urls;
  });
  ok(!cached.some((u) => u.startsWith("/api/")) && cached.includes("/offline.html"), `SW cache has shell, no API entries (${cached.length} entries)`);
  await context.setOffline(false);
  await page.waitForSelector("text=You're offline", { state: "detached", timeout: 10000 });
  ok(true, "offline label disappears when back online");
  await context.close();
}

// ---- 5. Resilience regressions: API down -> friendly error + last-good data; 503 HTML -> friendly error
{
  const { context, page } = await fresh();
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 90000 });
  await settle(page);
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
  await page.reload(); await page.waitForSelector("html[data-ack]");
  await page.getByText(/May be outdated/).first().waitFor({ timeout: 30000 });
  ok(true, "API down: last-good data shown with 'May be outdated'");
  // the client auto-retries for ~90s ("refreshing…"); afterwards a Try again / Refresh control appears
  ok((await page.getByText(/while refreshing/).count()) + (await page.getByRole("button", { name: /Try again|Refresh/ }).count()) > 0, "API down: auto-retry in progress or retry control offered");
  await page.unroute("**/api/**");
  await page.route("**/api/news/**", (route) => route.fulfill({ status: 503, contentType: "text/html", body: "<html>Service Unavailable</html>" }));
  await page.reload(); await page.waitForSelector("html[data-ack]");
  await page.getByText(/Headlines unavailable/).waitFor({ timeout: 90000 }).catch(() => {});
  ok((await page.locator("body").innerText()).includes("Recent headlines"), "news 503(html): panel degrades gracefully, page still works");
  ok(!(await page.locator("body").innerText()).includes("<html>"), "raw HTML error body never shown");
  await context.close();
}

await browser.close();
console.log(failures ? `\n${failures} check(s) FAILED` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
