import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_LISTS, MAX_SYMBOLS, TRENDING_ID, addSymbol, createList, deleteList, initialState, load, normalizeSymbol, removeSymbol,
  renameList, sanitize, selectList, serialize, validateName, type ListsState,
} from "./listsCore";

let n = 0;
const id = () => `id${++n}`;
const must = (r: ReturnType<typeof createList>): ListsState => {
  assert.ok(r.ok, r.ok ? "" : r.reason);
  return r.state;
};

test("normalizeSymbol validates like the API", () => {
  assert.equal(normalizeSymbol(" aapl "), "AAPL");
  assert.equal(normalizeSymbol("brk-b"), "BRK-B");
  assert.equal(normalizeSymbol("^GSPC"), null); // must start with a letter or digit, same as the backend
  for (const bad of ["", " ", "A$B", "TOOLONGSYMBOLXXXXX", "A B", "<script>"]) assert.equal(normalizeSymbol(bad), null, bad);
  assert.equal(normalizeSymbol(5), null);
  assert.equal(normalizeSymbol(null), null);
});

test("fresh start: Trending selected, one default list", () => {
  const s = load(null, null);
  assert.equal(s.selectedId, TRENDING_ID);
  assert.equal(s.lists.length, 1);
  assert.equal(s.lists[0].name, "My watchlist");
  assert.deepEqual(s.lists[0].symbols, ["AAPL", "MSFT", "NVDA"]);
});

test("migrates an existing watchlist.v1 into 'My watchlist' (keeps order, cleans junk, defaults to Trending)", () => {
  const s = load(null, JSON.stringify(["tsla", "AAPL", "aapl", 5, "A$B", "BRK-B"]));
  assert.deepEqual(s.lists[0].symbols, ["TSLA", "AAPL", "BRK-B"]);
  assert.equal(s.lists[0].name, "My watchlist");
  assert.equal(s.selectedId, TRENDING_ID);
  assert.deepEqual(load(null, "[]").lists[0].symbols, []); // an intentionally emptied watchlist stays empty
});

test("v2 wins over legacy, and round-trips", () => {
  let s = must(createList(load(null, null), "Tech", id));
  s = must(addSymbol(s, s.selectedId, "nvda"));
  const back = load(serialize(s), JSON.stringify(["ZZZ"]));
  assert.deepEqual(back, s);
});

test("corrupt or hostile storage never throws and falls back safely", () => {
  for (const raw of ["{", "null", "42", '"x"', "[]", '{"v":1}', '{"v":2}', '{"v":2,"lists":"no"}', "\u0000"]) {
    const s = load(raw, null);
    assert.equal(s.v, 2);
    assert.ok(s.lists.length >= 1 || raw.includes('"lists"'), raw);
    assert.equal(s.selectedId, TRENDING_ID);
  }
  assert.equal(load("{", "{").lists[0].name, "My watchlist"); // both corrupt: defaults
});

test("sanitize drops bad lists, dedupes, caps, repairs selection", () => {
  const many = Array.from({ length: 80 }, (_, i) => `S${i}`);
  const s = sanitize({
    v: 2, selectedId: "gone", lastUserListId: "gone",
    lists: [
      { id: "a", name: "  Alpha  ", symbols: ["aapl", "AAPL", "bad sym", ...many] },
      { id: "a", name: "Dup id", symbols: [] },
      { id: "b", name: "alpha", symbols: [] }, // same name, different case
      { id: "c", name: "Trending (3-day)", symbols: [] }, // reserved
      { id: "bad id!", name: "Bad id", symbols: [] },
      { id: "d", name: "   ", symbols: [] },
      "junk", null,
      { id: "e", name: "x".repeat(100), symbols: "nope" },
    ],
  })!;
  assert.deepEqual(s.lists.map((l) => l.id), ["a", "e"]);
  assert.equal(s.lists[0].name, "Alpha");
  assert.equal(s.lists[0].symbols.length, MAX_SYMBOLS);
  assert.equal(s.lists[0].symbols[0], "AAPL");
  assert.equal(new Set(s.lists[0].symbols).size, MAX_SYMBOLS);
  assert.equal(s.lists[1].name.length, 40);
  assert.deepEqual(s.lists[1].symbols, []);
  assert.equal(s.selectedId, TRENDING_ID);
  assert.equal(s.lastUserListId, "a");
});

test("create: validates names, caps count, selects the new list", () => {
  let s = initialState(false);
  const r = createList(s, "Growth", id);
  s = must(r);
  assert.equal(s.lists.at(-1)?.name, "Growth");
  assert.equal(s.selectedId, s.lists.at(-1)?.id);
  for (const bad of ["", "   ", "my WATCHLIST", "Trending", "trending (3-day)", "x".repeat(41)]) {
    assert.equal(createList(s, bad, id).ok, false, bad);
  }
  while (s.lists.length < MAX_LISTS) s = must(createList(s, `L${s.lists.length}`, id));
  const full = createList(s, "One too many", id);
  assert.ok(!full.ok && /at most 20/.test(full.reason));
});

test("create avoids id collisions", () => {
  const s = initialState(false);
  const ids = [s.lists[0].id, s.lists[0].id, "fresh"];
  const out = must(createList(s, "New", () => ids.shift() as string));
  assert.equal(out.lists.at(-1)?.id, "fresh");
});

test("rename: unique (case-insensitive), allows case-only change of itself, reserved blocked", () => {
  let s = must(createList(initialState(false), "Tech", id));
  const techId = s.selectedId;
  assert.equal(renameList(s, techId, "my watchlist").ok, false); // taken by the default list
  assert.equal(renameList(s, techId, "Trending").ok, false);
  assert.equal(renameList(s, "missing", "X").ok, false);
  s = must(renameList(s, techId, "TECH"));
  assert.equal(s.lists.find((l) => l.id === techId)?.name, "TECH");
  s = must(renameList(s, techId, "  Big   Tech "));
  assert.equal(s.lists.find((l) => l.id === techId)?.name, "Big Tech");
});

test("delete: removes list, falls back to Trending when it was selected, fixes lastUserListId", () => {
  let s = must(createList(initialState(false), "Tech", id));
  const techId = s.selectedId;
  s = must(deleteList(s, techId));
  assert.equal(s.selectedId, TRENDING_ID);
  assert.equal(s.lists.find((l) => l.id === techId), undefined);
  assert.equal(s.lastUserListId, s.lists[0].id);
  assert.equal(deleteList(s, techId).ok, false);
  // deleting a list that isn't selected keeps the selection
  s = must(createList(s, "A", id));
  const a = s.selectedId;
  s = selectList(s, s.lists[0].id);
  s = must(deleteList(s, a));
  assert.equal(s.selectedId, s.lists[0].id);
  // delete everything: allowed, Trending remains
  s = must(deleteList(s, s.lists[0].id));
  assert.deepEqual([s.lists.length, s.selectedId, s.lastUserListId], [0, TRENDING_ID, null]);
});

test("add/remove tickers: normalise, dedupe, cap, no mutation", () => {
  const base = initialState(false);
  const frozen = JSON.stringify(base);
  const lid = base.lists[0].id;
  let s = must(addSymbol(base, lid, " msft "));
  assert.equal(JSON.stringify(base), frozen); // immutable updates
  assert.deepEqual(s.lists[0].symbols, ["MSFT"]);
  const dup = addSymbol(s, lid, "MSFT");
  assert.ok(dup.ok && dup.state === s && /already in/.test(dup.message ?? ""));
  const bad = addSymbol(s, lid, "A$B");
  assert.ok(!bad.ok && /not a valid ticker/.test(bad.reason));
  assert.equal(addSymbol(s, "nope", "AAPL").ok, false);
  for (let i = 0; s.lists[0].symbols.length < MAX_SYMBOLS; i++) s = must(addSymbol(s, lid, `T${i}`));
  const full = addSymbol(s, lid, "ONEMORE");
  assert.ok(!full.ok && /full/.test(full.reason));
  s = must(removeSymbol(s, lid, "MSFT"));
  assert.ok(!s.lists[0].symbols.includes("MSFT"));
  assert.equal(removeSymbol(s, "nope", "X").ok, false);
});

test("selectList: remembers user lists, ignores unknown ids, Trending is always selectable", () => {
  let s = must(createList(initialState(false), "Tech", id));
  const tech = s.selectedId;
  s = selectList(s, TRENDING_ID);
  assert.equal(s.selectedId, TRENDING_ID);
  assert.equal(s.lastUserListId, tech); // remembered for "add from search while on Trending"
  assert.equal(selectList(s, "ghost"), s);
  s = selectList(s, tech);
  assert.equal(s.selectedId, tech);
  assert.deepEqual(load(serialize(s), null).selectedId, tech); // last selection survives a reload
});

test("validateName exposes reasons for the UI", () => {
  const s = initialState(false);
  const v = validateName(s, "My Watchlist");
  assert.ok(!v.ok && /already/.test(v.reason));
  assert.ok(validateName(s, "Ok name").ok);
});
