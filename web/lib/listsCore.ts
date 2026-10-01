// Pure logic for watchlists ("lists"): no React, no browser APIs, so it can be unit-tested with plain Node.
// Schema v2: { v: 2, lists: [{ id, name, symbols[] }], selectedId, lastUserListId }.
// The built-in Trending list is virtual: it is never stored in `lists`, only selected via id "trending".

export const TRENDING_ID = "trending";
export const TRENDING_NAME = "Trending (3-day)";
export const MAX_LISTS = 20;
export const MAX_SYMBOLS = 50;
export const MAX_NAME = 40;
export const DEFAULT_LIST_NAME = "My watchlist";
export const DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA"];

export type UserList = { id: string; name: string; symbols: string[] };
export type ListsState = { v: 2; lists: UserList[]; selectedId: string; lastUserListId: string | null };
export type Result = { ok: true; state: ListsState; message?: string } | { ok: false; reason: string };

// Same shape the API accepts (backend/app/symbols.py).
const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-=^]{0,14}$/;

export function normalizeSymbol(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const s = raw.trim().toUpperCase();
  return SYMBOL_RE.test(s) ? s : null;
}

export function initialState(withDefaults = true): ListsState {
  const list: UserList = { id: "default", name: DEFAULT_LIST_NAME, symbols: withDefaults ? [...DEFAULT_SYMBOLS] : [] };
  return { v: 2, lists: [list], selectedId: TRENDING_ID, lastUserListId: list.id };
}

function cleanSymbols(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const out: string[] = [];
  for (const x of input) {
    const s = normalizeSymbol(x);
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= MAX_SYMBOLS) break;
  }
  return out;
}

function cleanName(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const n = input.replace(/\s+/g, " ").trim().slice(0, MAX_NAME);
  return n ? n : null;
}

/** Make any parsed value into a valid state, dropping what can't be trusted. */
export function sanitize(input: unknown): ListsState | null {
  if (!input || typeof input !== "object") return null;
  const o = input as Record<string, unknown>;
  if (o.v !== 2 || !Array.isArray(o.lists)) return null;
  const lists: UserList[] = [];
  const ids = new Set<string>();
  const names = new Set<string>();
  for (const raw of o.lists) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    const name = cleanName(r.name);
    const id = typeof r.id === "string" && /^[A-Za-z0-9_-]{1,40}$/.test(r.id) ? r.id : null;
    if (!name || !id || ids.has(id) || names.has(name.toLowerCase()) || name.toLowerCase() === TRENDING_NAME.toLowerCase()) continue;
    ids.add(id);
    names.add(name.toLowerCase());
    lists.push({ id, name, symbols: cleanSymbols(r.symbols) });
    if (lists.length >= MAX_LISTS) break;
  }
  const selectedId = typeof o.selectedId === "string" && (o.selectedId === TRENDING_ID || ids.has(o.selectedId)) ? o.selectedId : TRENDING_ID;
  const last = typeof o.lastUserListId === "string" && ids.has(o.lastUserListId) ? o.lastUserListId : (lists[0]?.id ?? null);
  return { v: 2, lists, selectedId, lastUserListId: last };
}

/**
 * Load state from raw localStorage strings. `rawV2` wins if valid; otherwise a valid legacy `watchlist.v1`
 * array (["AAPL", ...]) becomes the "My watchlist" list; otherwise a fresh default. Never throws.
 * The legacy value is only read, never deleted, so rolling back to an older version still works.
 */
export function load(rawV2: string | null, rawLegacy: string | null): ListsState {
  if (rawV2) {
    try {
      const s = sanitize(JSON.parse(rawV2));
      if (s) return s;
    } catch {
      /* corrupt: fall through to migration/defaults */
    }
  }
  if (rawLegacy) {
    try {
      const parsed = JSON.parse(rawLegacy);
      if (Array.isArray(parsed)) {
        const state = initialState(false);
        state.lists[0].symbols = cleanSymbols(parsed);
        return state;
      }
    } catch {
      /* corrupt legacy: ignore */
    }
  }
  return initialState(true);
}

export const serialize = (s: ListsState) => JSON.stringify(s);

export function validateName(state: ListsState, raw: string, exceptId?: string): { ok: true; name: string } | { ok: false; reason: string } {
  const name = cleanName(raw);
  if (!name) return { ok: false, reason: "Enter a name for the list." };
  if (raw.trim().length > MAX_NAME) return { ok: false, reason: `Names can be at most ${MAX_NAME} characters.` };
  const lower = name.toLowerCase();
  if (lower === TRENDING_NAME.toLowerCase() || lower === "trending") return { ok: false, reason: "That name is reserved for the built-in list." };
  if (state.lists.some((l) => l.id !== exceptId && l.name.toLowerCase() === lower)) return { ok: false, reason: "You already have a list with that name." };
  return { ok: true, name };
}

export function createList(state: ListsState, rawName: string, makeId: () => string = defaultId): Result {
  if (state.lists.length >= MAX_LISTS) return { ok: false, reason: `You can have at most ${MAX_LISTS} lists.` };
  const v = validateName(state, rawName);
  if (!v.ok) return v;
  let id = makeId();
  while (state.lists.some((l) => l.id === id)) id = makeId();
  const list: UserList = { id, name: v.name, symbols: [] };
  return { ok: true, state: { ...state, lists: [...state.lists, list], selectedId: id, lastUserListId: id }, message: `Created list ${v.name}.` };
}

export function renameList(state: ListsState, id: string, rawName: string): Result {
  const target = state.lists.find((l) => l.id === id);
  if (!target) return { ok: false, reason: "That list no longer exists." };
  const v = validateName(state, rawName, id);
  if (!v.ok) return v;
  return { ok: true, state: { ...state, lists: state.lists.map((l) => (l.id === id ? { ...l, name: v.name } : l)) }, message: `Renamed to ${v.name}.` };
}

export function deleteList(state: ListsState, id: string): Result {
  const target = state.lists.find((l) => l.id === id);
  if (!target) return { ok: false, reason: "That list no longer exists." };
  const lists = state.lists.filter((l) => l.id !== id);
  return {
    ok: true,
    state: {
      ...state,
      lists,
      selectedId: state.selectedId === id ? TRENDING_ID : state.selectedId,
      lastUserListId: state.lastUserListId === id ? (lists[0]?.id ?? null) : state.lastUserListId,
    },
    message: `Deleted list ${target.name}.`,
  };
}

export function selectList(state: ListsState, id: string): ListsState {
  if (id === state.selectedId) return state;
  if (id === TRENDING_ID) return { ...state, selectedId: TRENDING_ID };
  return state.lists.some((l) => l.id === id) ? { ...state, selectedId: id, lastUserListId: id } : state;
}

export function addSymbol(state: ListsState, listId: string, raw: string): Result {
  const list = state.lists.find((l) => l.id === listId);
  if (!list) return { ok: false, reason: "That list no longer exists." };
  const sym = normalizeSymbol(raw);
  if (!sym) return { ok: false, reason: `"${String(raw).trim().slice(0, 20)}" is not a valid ticker symbol.` };
  if (list.symbols.includes(sym)) return { ok: true, state, message: `${sym} is already in ${list.name}.` };
  if (list.symbols.length >= MAX_SYMBOLS) return { ok: false, reason: `${list.name} is full (${MAX_SYMBOLS} tickers).` };
  return {
    ok: true,
    state: { ...state, lists: state.lists.map((l) => (l.id === listId ? { ...l, symbols: [...l.symbols, sym] } : l)), lastUserListId: listId },
    message: `Added ${sym} to ${list.name}.`,
  };
}

export function removeSymbol(state: ListsState, listId: string, sym: string): Result {
  const list = state.lists.find((l) => l.id === listId);
  if (!list) return { ok: false, reason: "That list no longer exists." };
  return {
    ok: true,
    state: { ...state, lists: state.lists.map((l) => (l.id === listId ? { ...l, symbols: l.symbols.filter((s) => s !== sym) } : l)) },
    message: `Removed ${sym} from ${list.name}.`,
  };
}

let counter = 0;
function defaultId(): string {
  counter += 1;
  return `l${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}${counter}`;
}
