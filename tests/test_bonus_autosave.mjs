// Bonus-bet autosave + auto-retry wiring (site/index.html). Self-contained:
// needs a fetch spy and controllable timers, so it doesn't use page_harness's
// reject-fetch loadPage. Verifies: editing an *editable* bonus row debounce-saves
// to /api/savebonus; overlapping edits collapse into one POST; non-bonus and
// kicked-off rows never autosave; a transient failure auto-retries (with the
// same idempotent payload) and stops on success; a 4xx validation error does
// NOT retry. Node 18+, stdlib only.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "site", "index.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const code = scripts[scripts.length - 1][1];

function stubEl() {
  return { addEventListener() {}, style: {}, textContent: "", innerHTML: "",
    classList: { toggle() {}, add() {}, remove() {} }, disabled: false, dataset: {} };
}
const els = {};
const document = {
  querySelector(s) { return (els[s] ||= stubEl()); },
  querySelectorAll() { return []; },
  getElementById(id) { return (els["#" + id] ||= stubEl()); },
  addEventListener() {},
};

const fetchCalls = [];
let fetchPlan = [];          // queue of {ok,status,json} | "reject"; default = success
const timers = [];
const sandbox = {
  document, location: { search: "", hostname: "test.invalid" },
  URLSearchParams, console, CSS: { escape: (s) => s }, confirm: () => true,
  setTimeout: (fn) => { const id = timers.length; timers.push({ fn, cancelled: false }); return id; },
  clearTimeout: (id) => { if (timers[id]) timers[id].cancelled = true; },
  fetch: (url, opts) => {
    const body = JSON.parse(opts.body);
    fetchCalls.push({ url, body });
    const plan = fetchPlan.length ? fetchPlan.shift() : { ok: true, status: 200 };
    if (plan === "reject") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve({ ok: plan.ok, status: plan.status,
      json: () => Promise.resolve(plan.json || { saved: body.picks.length }) });
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: "index.html#script" });
const T = sandbox.window.__T;

const pending = () => timers.filter((t) => !t.cancelled).length;
// Run scheduled timers to completion, awaiting microtasks so retries that
// schedule further timers also fire. Capped so a runaway loop can't hang.
async function runTimers(maxRounds = 12) {
  for (let i = 0; i < maxRounds; i++) {
    const due = timers.filter((t) => !t.cancelled);
    if (!due.length) return;
    due.forEach((t) => { t.cancelled = true; });   // mark before firing
    // Drain generously per fired timer: a save's await chain (fetch → json → catch
    // → finally) must fully settle before the round ends, otherwise the next round
    // sees no due timer and returns while a save is still in flight.
    for (const t of due) { t.fn(); for (let k = 0; k < 8; k++) await Promise.resolve(); }
  }
}
function ev(key, role, value) {
  return { target: { dataset: { key, role }, value, classList: { contains: () => false }, closest: () => null } };
}
function reset() { fetchCalls.length = 0; timers.length = 0; fetchPlan = []; T.bonusReset(); }
const badgeOf = (key) => (els["#bsave-" + key] || {}).textContent;

let n = 0, bad = 0;
const check = (label, cond) => { n++; if (!cond) { bad++; console.error("  ✗ " + label); } else console.log("  ✓ " + label); };

// 1) Editing a not-started bonus row autosaves, debounced; type+value → one POST.
T.set({ LOCKED: false, META: { "bonus|500|1": { type: "bonus_bet", match_id: 500, started: false } }, VALUES: {} });
reset();
T.onChange(ev("bonus|500|1", "bet_type", "BTTS"));
check("bet_type change debounces (1 timer, no immediate POST)", pending() === 1 && fetchCalls.length === 0);
T.onChange(ev("bonus|500|1", "bet_value", "Yes"));
check("a second change collapses into the same single timer", pending() === 1);
await runTimers();
check("one POST to /api/savebonus after debounce", fetchCalls.length === 1 && /\/api\/savebonus/.test(fetchCalls[0].url));
check("payload carries the completed bet", fetchCalls[0].body.picks.length === 1 &&
  fetchCalls[0].body.picks[0].bet_type === "BTTS" && fetchCalls[0].body.picks[0].bet_value === "Yes");

// 2) Token and note edits on a bonus row also autosave.
reset();
T.onChange(ev("bonus|500|1", "note", "derby energy"));
check("note edit on a bonus row schedules autosave", pending() === 1);

// 3) A non-bonus (match) change must NOT autosave (it has its own Save button).
reset();
T.set({ LOCKED: false, META: { "match|100": { type: "match_outcome", match_id: 100 } }, VALUES: {} });
T.onChange(ev("match|100", "outcome", "Home"));
check("match-outcome change schedules no bonus autosave", pending() === 0 && fetchCalls.length === 0);

// 4) A kicked-off bonus row is immutable → no autosave.
reset();
T.set({ LOCKED: true, META: { "bonus|600|1": { type: "bonus_bet", match_id: 600, started: true } }, VALUES: {} });
T.onChange(ev("bonus|600|1", "bet_type", "BTTS"));
check("kicked-off bonus row → no autosave", pending() === 0 && fetchCalls.length === 0);

// 5) After the main lock, a not-started bonus row still autosaves.
reset();
T.set({ LOCKED: true, META: { "bonus|700|1": { type: "bonus_bet", match_id: 700, started: false } }, VALUES: {} });
T.onChange(ev("bonus|700|1", "bet_type", "Over 2.5 goals"));
check("locked main picks, bonus still editable → autosave scheduled", pending() === 1);

// 6) Transient failure (network reject, then 5xx) auto-retries, then succeeds.
reset();
T.set({ LOCKED: false, META: { "bonus|800|1": { type: "bonus_bet", match_id: 800, started: false } },
        VALUES: { "bonus|800|1": { bet_type: "BTTS", bet_value: "Yes" } } });
fetchPlan = ["reject", { ok: false, status: 503 }, { ok: true, status: 200 }];
T.onChange(ev("bonus|800|1", "bet_value", "Yes"));
await runTimers();
check("transient failures retry until success (3 POSTs)", fetchCalls.length === 3);
check("every retry resends the same idempotent payload (same slot key)",
  fetchCalls.every((c) => c.body.picks.length === 1 && c.body.picks[0].key === "bonus|800|1"));

// 7) A 4xx validation error does NOT retry (surfaced once).
reset();
fetchPlan = [{ ok: false, status: 400, json: { error: "match already kicked off" } }];
T.onChange(ev("bonus|800|1", "bet_value", "No"));
await runTimers();
check("4xx validation error is not retried (1 POST only)", fetchCalls.length === 1);

// 8) Inline indicator: edit → "Saving…", success → "Saved ✓", then auto-clears.
reset();
T.set({ LOCKED: false, META: { "bonus|900|1": { type: "bonus_bet", match_id: 900, started: false } },
        VALUES: { "bonus|900|1": { bet_type: "BTTS", bet_value: "Yes" } } });
T.onChange(ev("bonus|900|1", "bet_value", "Yes"));
check("row badge shows 'Saving…' immediately on edit", badgeOf("bonus|900|1") === "Saving…");
await runTimers(1);   // fire the debounce → one successful save; leave the 2s clear timer pending
check("row badge shows 'Saved ✓' after a successful save", badgeOf("bonus|900|1") === "Saved ✓");
await runTimers();    // fire the clear timer
check("row badge auto-clears after success", badgeOf("bonus|900|1") === "");

// 9) Inline indicator: a non-retryable failure shows "Not saved" and stays.
reset();
fetchPlan = [{ ok: false, status: 400, json: { error: "nope" } }];
T.set({ LOCKED: false, META: { "bonus|901|1": { type: "bonus_bet", match_id: 901, started: false } },
        VALUES: { "bonus|901|1": { bet_type: "BTTS", bet_value: "No" } } });
T.onChange(ev("bonus|901|1", "bet_value", "No"));
await runTimers();
check("row badge shows 'Not saved' on a non-retryable failure", badgeOf("bonus|901|1") === "Not saved");

// 10) Inline indicator: a transient failure shows "Retrying…" before it settles.
reset();
fetchPlan = ["reject", { ok: true, status: 200 }];
T.set({ LOCKED: false, META: { "bonus|902|1": { type: "bonus_bet", match_id: 902, started: false } },
        VALUES: { "bonus|902|1": { bet_type: "BTTS", bet_value: "Yes" } } });
T.onChange(ev("bonus|902|1", "bet_value", "Yes"));
await runTimers(1);   // fire debounce → first attempt rejects → "Retrying…"
check("row badge shows 'Retrying…' after a transient failure", badgeOf("bonus|902|1") === "Retrying…");
await runTimers(1);   // fire the retry → success
check("row badge recovers to 'Saved ✓' after a successful retry", badgeOf("bonus|902|1") === "Saved ✓");

console.log(`\ntest_bonus_autosave: ${n - bad}/${n} checks passed`);
if (bad) process.exit(1);
