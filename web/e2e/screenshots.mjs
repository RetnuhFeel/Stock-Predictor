// Regenerates docs/img/* by driving the built app (headless Chrome) against a running API.
//   node screenshots.mjs        (WEB, CHROME, OUT env vars optional; needs ffmpeg for the GIF)
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const WEB = process.env.WEB || "http://localhost:3000";
const OUT = process.env.OUT || "../../docs/img";
const FRAMES = "/tmp/sp-frames";
mkdirSync(OUT, { recursive: true });
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"] });
const ctx = (opts) => browser.newContext({ reducedMotion: "reduce", deviceScaleFactor: 1, ...opts });
const accept = async (page) => { await page.getByRole("button", { name: /I understand/i }).click(); await page.waitForSelector("html[data-ack]"); };
const forecastReady = async (page) => {
  await page.getByText(/Experimental \d+-day estimate/).waitFor({ timeout: 120000 });
  await page.getByRole("heading", { name: "Recent headlines" }).waitFor();
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(600);
};
const shot = (page, name, opts = {}) => page.screenshot({ path: `${OUT}/${name}`, type: "png", ...opts });

// Lists: Trending default + a user list (desktop) and mobile
{
  const c = await ctx({ colorScheme: "light", viewport: { width: 1280, height: 800 } });
  const page = await c.newPage();
  await page.goto(WEB); await accept(page); await forecastReady(page);
  const sel = page.getByRole("combobox", { name: "List", exact: true });
  await page.getByRole("list", { name: /Trending/ }).locator("> li").first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(500);
  await shot(page, "lists-trending-light.png");
  await sel.selectOption("default");
  await page.waitForTimeout(800);
  await shot(page, "lists-user-light.png");
  await c.close();
  const m = await ctx({ colorScheme: "light", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const mp = await m.newPage();
  await mp.goto(WEB); await accept(mp);
  await mp.getByRole("list", { name: /Trending/ }).locator("> li").first().waitFor({ timeout: 120000 });
  await mp.waitForTimeout(500);
  await shot(mp, "mobile-lists.png");
  await m.close();
}
if (process.env.ONLY === "lists") { await browser.close(); console.log("done (lists only)"); process.exit(0); }

// Desktop light + dark
for (const scheme of ["light", "dark"]) {
  const c = await ctx({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });
  const page = await c.newPage();
  await page.goto(WEB); await accept(page); await forecastReady(page);
  await shot(page, `home-${scheme}.png`);
  if (scheme === "light") {
    await page.getByRole("button", { name: "Compare", exact: true }).click();
    await page.getByRole("table").first().waitFor({ timeout: 120000 });
    await page.waitForTimeout(600);
    await shot(page, "compare-light.png");
    await page.goto(`${WEB}/model`);
    await page.getByRole("table").first().waitFor({ timeout: 120000 });
    await page.waitForTimeout(400);
    await shot(page, "model-report-light.png", { fullPage: true });
  }
  await c.close();
}
// Mobile
{
  const c = await ctx({ colorScheme: "light", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const page = await c.newPage();
  await page.goto(WEB);
  await page.getByRole("dialog").waitFor();
  await shot(page, "mobile-gate.png");
  await accept(page); await forecastReady(page);
  await shot(page, "mobile-home.png");
  await c.close();
}

// Demo GIF: gate -> forecast -> 20d horizon -> compare -> model report
{
  const c = await ctx({ colorScheme: "light", viewport: { width: 1100, height: 700 } });
  const page = await c.newPage();
  let n = 0;
  const frames = [];
  const frame = async (seconds) => { const f = `${FRAMES}/f${String(n++).padStart(2, "0")}.png`; await page.screenshot({ path: f }); frames.push([f, seconds]); };
  await page.goto(WEB); await page.getByRole("dialog").waitFor(); await frame(2.5);
  await accept(page); await forecastReady(page); await frame(3);
  await page.getByText("Training model").waitFor({ state: "detached" }).catch(() => {});
  await page.locator("section[aria-labelledby=bt-title]").scrollIntoViewIfNeeded(); await page.waitForTimeout(300); await frame(3.5);
  await page.evaluate(() => window.scrollTo(0, 0));
  const w = page.waitForResponse((r) => r.url().includes("horizon=20"), { timeout: 120000 });
  await page.getByRole("button", { name: "20d", exact: true }).click(); await w;
  await page.getByText("(20-trading-day forecasts)").waitFor(); await page.waitForTimeout(500);
  await page.locator("section[aria-labelledby=bt-title]").scrollIntoViewIfNeeded(); await page.waitForTimeout(300); await frame(3.5);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("table").first().waitFor({ timeout: 120000 }); await page.waitForTimeout(600); await frame(3.5);
  await page.goto(`${WEB}/model`); await page.locator("section[aria-labelledby=report-title] table").waitFor({ timeout: 120000 }); await page.waitForTimeout(400); await frame(4);
  await c.close();

  const list = frames.map(([f, s]) => `file '${f}'\nduration ${s}`).join("\n") + `\nfile '${frames.at(-1)[0]}'\n`;
  writeFileSync(`${FRAMES}/list.txt`, list);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", `${FRAMES}/list.txt`,
    "-vf", "fps=4,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
    "-loop", "0", `${OUT}/demo.gif`], { stdio: "inherit" });
}
await browser.close();
console.log("done");
