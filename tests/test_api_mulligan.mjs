// /api/mulligan (hosted Pages Function): guard + dry-run + commit, through the real module
// against a mutable in-memory Airtable stub. Mirrors test_mulligan_entry.py.
import { check, summary } from "./page_harness.mjs";

const ROUTE = new URL("../functions/api/%5B%5Broute%5D%5D.js", import.meta.url).href;
const { mulliganGuard, saveMulligan, onRequest } = await import(ROUTE);

const OPEN = new Date("2026-06-27T12:00:00Z");     // inside the June 24–28 window
const CLOSED = new Date("2026-06-20T12:00:00Z");   // before it

// Teams: NOR original DH (rank 40), USA eligible (17), URU ineligible (16), + bracket teams.
const TEAMS = {
  900: { team_id: 900, code: "NOR", group: "F", fifa_ranking: 40 },
  910: { team_id: 910, code: "USA", group: "D", fifa_ranking: 17 },
  920: { team_id: 920, code: "URU", group: "E", fifa_ranking: 16 },
  100: { team_id: 100, code: "AT0", group: "A", fifa_ranking: 3 },
  101: { team_id: 101, code: "AT1", group: "A", fifa_ranking: 22 },
  102: { team_id: 102, code: "BT0", group: "B", fifa_ranking: 9 },
};
const BY_ID = TEAMS;
const BY_CODE = Object.fromEntries(Object.values(TEAMS).map((t) => [t.code, t]));
const DH = { key: "darkhorse", type: "dark_horse", side_game: "Dark Horse", team_id: 900 };

function guardThrows(label, fn, frag) {
  try { fn(); check(label, false); }
  catch (e) { check(label, String(e.message).includes(frag)); }
}

// ---- mulliganGuard (pure) ----------------------------------------------------
const g = (repl, picks = [DH], mull = 1, toks = null, now = OPEN) =>
  mulliganGuard("darkhorse", repl, picks, BY_CODE, BY_ID, mull, toks, now);

guardThrows("closed window rejected", () => g({ team_id: 910 }, [DH], 1, null, CLOSED), "window is not open");
guardThrows("spent mulligan rejected", () => g({ team_id: 910 }, [DH], 0), "already used");
g({ team_id: 910 }); check("USA (17) is a legal Dark Horse replacement", true);
guardThrows("Uruguay (16) rejected", () => g({ team_id: 920 }), "not Dark-Horse-eligible");
guardThrows("no-op re-pick rejected", () => g({ team_id: 900 }), "identical");
guardThrows("replacement without a team rejected", () => g({ team_id: null }), "needs a team");
guardThrows("non-eligible target type rejected",
  () => mulliganGuard("side|Golden Boot", { team_id: 910 },
    [{ key: "side|Golden Boot", type: "side_game" }], BY_CODE, BY_ID, 1, null, OPEN),
  "not a mulligan-eligible pick");
guardThrows("unknown target rejected", () => mulliganGuard("R16-9", { team_id: 910 }, [DH], BY_CODE, BY_ID, 1, null, OPEN), "not found");
g({ team_id: 910, token: "Double" }, [DH], 1, { Double: 1 }); check("token available passes", true);
guardThrows("token exhausted rejected", () => g({ team_id: 910, token: "AllIn" }, [DH], 1, { AllIn: 0 }), "no AllIn tokens remaining");

const BRK = [{ key: "R16-1", type: "bracket_slot", bracket_slot: "R16-1", team_id: 100 },
             { key: "R16-2", type: "bracket_slot", bracket_slot: "R16-2", team_id: 101 }];
mulliganGuard("R16-2", { team_id: 102 }, BRK, BY_CODE, BY_ID, 1, null, OPEN);
check("valid bracket-slot swap passes", true);
guardThrows("bracket swap creating a duplicate rejected",
  () => mulliganGuard("R16-2", { team_id: 100 }, BRK, BY_CODE, BY_ID, 1, null, OPEN), "duplicate");

// ---- in-memory Airtable for saveMulligan -------------------------------------
function makeStore() {
  let auto = 0; const rid = () => "rec" + (++auto).toString().padStart(4, "0");
  const tables = {
    PoolPlayers: [{ id: "recCAL", fields: { name: "Cal", magic_link_token: "tok-c", mulligans_remaining: 1,
      tokens_remaining_double: 2, tokens_remaining_triple: 2, tokens_remaining_allin: 1 } }],
    Teams: Object.values(TEAMS).map((t) => ({ id: "recT" + t.team_id, fields: { ...t } })),
    SideGames: [{ id: "recSGDH", fields: { name: "Dark Horse" } }],
    Predictions: [{ id: "recDH", fields: { label: "Cal|darkhorse", prediction_type: "dark_horse",
      predicted_team: ["recT900"], side_game: ["recSGDH"] } }],
    Mulligans: [],
  };
  const fetchImpl = async (url, opts = {}) => {
    const u = new URL(url);
    const table = decodeURIComponent(u.pathname.split("/")[3]);
    const method = (opts.method || "GET").toUpperCase();
    const body = opts.body ? JSON.parse(opts.body) : null;
    const ok = (obj) => ({ ok: true, status: 200, json: async () => obj, text: async () => JSON.stringify(obj) });
    if (!tables[table]) return { ok: false, status: 404, text: async () => "no table " + table };
    if (method === "GET") return ok({ records: tables[table] });
    if (method === "POST") { const recs = body.records.map((r) => ({ id: rid(), fields: r.fields }));
      tables[table].push(...recs); return ok({ records: recs }); }
    if (method === "PATCH") {
      if (body.performUpsert) {
        const on = body.performUpsert.fieldsToMergeOn;
        for (const rec of body.records) {
          const m = tables[table].find((r) => on.every((f) => r.fields[f] === rec.fields[f]));
          if (m) Object.assign(m.fields, rec.fields); else tables[table].push({ id: rid(), fields: rec.fields });
        }
      } else for (const rec of body.records) {
        const m = tables[table].find((r) => r.id === rec.id); if (m) Object.assign(m.fields, rec.fields);
      }
      return ok({ records: [] });
    }
    return { ok: false, status: 400, text: async () => "unhandled " + method };
  };
  return { tables, fetchImpl };
}
const PROW = { id: "recCAL", fields: { name: "Cal", mulligans_remaining: 1,
  tokens_remaining_double: 2, tokens_remaining_triple: 2, tokens_remaining_allin: 1 } };

// ---- saveMulligan: dry-run writes nothing ------------------------------------
{
  const store = makeStore(); globalThis.fetch = store.fetchImpl;
  const res = await saveMulligan({ AIRTABLE_PAT: "p", AIRTABLE_BASE_ID: "b" }, PROW, "darkhorse", { team_id: 910 }, "", true, OPEN);
  check("dry-run flags itself + uncommitted", res.dryRun === true && res.committed === false);
  check("dry-run leaves the mulligan unspent", res.mulligans_remaining === 1);
  check("dry-run plan shows replacement label + new team",
    res.wouldWrite.replacement.label === "Cal|darkhorse|mull" &&
    res.wouldWrite.replacement.predicted_team[0] === "recT910");
  check("dry-run wrote no new rows", store.tables.Predictions.length === 1 && store.tables.Mulligans.length === 0);
}

// ---- saveMulligan: commit writes the sibling row, the link, and spends the mulligan ----
{
  const store = makeStore(); globalThis.fetch = store.fetchImpl;
  const res = await saveMulligan({ AIRTABLE_PAT: "p", AIRTABLE_BASE_ID: "b" }, PROW, "darkhorse", { team_id: 910 }, "USA looked strong", false, OPEN);
  check("commit reports the new label + code", res.committed === true && res.new_label === "Cal|darkhorse|mull" && res.replacement_code === "USA");
  const labels = store.tables.Predictions.map((r) => r.fields.label);
  check("sibling replacement row created", labels.includes("Cal|darkhorse|mull"));
  check("original Dark Horse row preserved", labels.includes("Cal|darkhorse"));
  check("Mulligans row links original→replacement", store.tables.Mulligans.length === 1 &&
    store.tables.Mulligans[0].fields.original_prediction[0] === "recDH");
  check("mulligan spent (remaining→0)", store.tables.PoolPlayers[0].fields.mulligans_remaining === 0);
}

// ---- through the router: ineligible replacement → 400, writes nothing --------
{
  const store = makeStore(); globalThis.fetch = store.fetchImpl;
  // Note: onRequest uses the real clock, so we can't drive an in-window commit through it
  // (date-dependent). We assert the eligibility 400 path, which fires before any window-pass needed
  // only when in window — so here we just confirm the route exists and rejects ineligible/edge input.
  const req = new Request("https://x.test/api/mulligan?p=tok-c", { method: "POST",
    body: JSON.stringify({ target: "darkhorse", replacement: { team_id: 920 } }),
    headers: { "Content-Type": "application/json" } });
  const res = await onRequest({ request: req, env: { AIRTABLE_PAT: "p", AIRTABLE_BASE_ID: "b" } });
  check("route is wired (not 404)", res.status !== 404);
  check("route rejects with 400 + leaves data untouched",
    res.status === 400 && store.tables.Predictions.length === 1 && store.tables.Mulligans.length === 0);
}

// ---- bootstrap exposes the window + remaining (date-independent) --------------
{
  const store = makeStore(); globalThis.fetch = store.fetchImpl;
  const req = new Request("https://x.test/api/bootstrap?p=tok-c", { method: "GET" });
  const res = await onRequest({ request: req, env: { AIRTABLE_PAT: "p", AIRTABLE_BASE_ID: "b" } });
  const body = await res.json();
  check("bootstrap returns mulliganWindow", Array.isArray(body.mulliganWindow) && body.mulliganWindow[0] === "2026-06-24");
  check("bootstrap returns mulligansRemaining", body.mulligansRemaining === 1);
}

summary("test_api_mulligan");
