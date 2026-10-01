import assert from "node:assert/strict";
import { test } from "node:test";
import { buildRows, CHART_RANGES, DEFAULT_RANGE, parseRange } from "./chartRange";

test("range options are exactly 1M..5Y and the default is one of them", () => {
  assert.deepEqual(CHART_RANGES.map((r) => r.label), ["1M", "3M", "6M", "1Y", "2Y", "5Y"]);
  assert.ok(CHART_RANGES.some((r) => r.id === DEFAULT_RANGE));
});

test("parseRange accepts known values and falls back safely", () => {
  for (const r of CHART_RANGES) assert.equal(parseRange(r.id), r.id);
  for (const bad of [null, undefined, "", "10y", "{bad json", 5, {}, "6MO"]) assert.equal(parseRange(bad), DEFAULT_RANGE);
});

const hist = [{ date: "d1", close: 100 }, { date: "d2", close: 110 }];
const path = [{ date: "d3", mid: 112, low: 105, high: 120 }, { date: "d4", mid: 114, low: 104, high: 125 }];

test("forecast overlay joins at the last close and follows it", () => {
  const rows = buildRows(hist, path, false);
  assert.equal(rows.length, 4);
  assert.deepEqual(rows[1], { date: "d2", close: 110, mid: 110, band: [110, 110] });
  assert.deepEqual(rows[2], { date: "d3", mid: 112, band: [105, 120] });
  assert.equal(rows[0].mid, undefined);
});

test("normalized view scales history and forecast from the same base", () => {
  const rows = buildRows(hist, path, true);
  assert.equal(rows[0].close, 0);
  assert.ok(Math.abs(rows[1].close! - 10) < 1e-9 && Math.abs(rows[1].mid! - 10) < 1e-9);
  assert.ok(Math.abs(rows[2].mid! - 12) < 1e-9);
  assert.ok(Math.abs(rows[2].band![0] - 5) < 1e-9 && Math.abs(rows[3].band![1] - 25) < 1e-9);
});

test("no history or no forecast", () => {
  assert.deepEqual(buildRows([], path, false), []);
  const rows = buildRows(hist, undefined, false);
  assert.equal(rows.length, 2);
  assert.equal(rows[1].mid, undefined);
});
