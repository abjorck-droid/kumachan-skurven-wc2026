// /api/savebonus v1.2 stoppage-pot tests, through the real Pages Function router
// against a mutable in-memory Airtable stub (same pattern as test_api_save.mjs).
// Covers: pot rows written as prediction_type "stoppage_bet" + pot "stoppage";
// wild types allowed only on pot fixtures; third slot pot-only; outcome/exact/Duel
// key shapes + validation; Stoppage2x budget of one (classic tokens rejected on pot
// rows and vice versa); kickoff immutability incl. the Duel's 3rd-place anchor;
// clearing a future pot row deletes it; /api/public seals stoppage_bet rows until
// kickoff and reveals them after. Node 18+, stdlib only.
import { check, summary } from "./page_harness.mjs";

const ROUTE = new URL("../functions/api/%5B%5Broute%5D%5D.js", import.meta.url).href;
const FID_3RD = 1591865, FID_FINAL = 1591866, FID_GROUP = 100;
const FUTURE = "2099-01-01T00:00:00.000Z", PAST = "2020-01-01T00:00:00.000Z";

function makeStore() {
  let auto = 0;
  const rid = () => "rec" + (++auto).toString().padStart(4, "0");
  const tables = {
    PoolPlayers: [{ id: rid(), fields: { name: "Andreas", magic_link_token: "tok-a" } },
                  { id: rid(), fields: { name: "Cal", magic_link_token: "tok-c" } }],
    Teams: [{ id: rid(), fields: { team_id: 9, code: "ESP", name: "Spain" } },
            { id: rid(), fields: { team_id: 26, code: "ARG", name: "Argentina" } },
            { id: rid(), fields: { team_id: 2, code: "FRA", name: "France" } },
            { id: rid(), fields: { team_id: 10, code: "ENG", name: "England" } }],
    SideGames: [{ id: rid(), fields: { name: "The Duel", base_points: 25 } }],
    Footballers: [], Standings: [], Scorers: [],
    Matches: [
      { id: rid(), fields: { fixture_id: FID_3RD, round: "3rd Place Final", kickoff_utc: FUTURE, status: "Scheduled" } },
      { id: rid(), fields: { fixture_id: FID_FINAL, round: "Final", kickoff_utc: FUTURE, status: "Scheduled" } },
      { id: rid(), fields: { fixture_id: FID_GROUP, round: "Group Stage - 1", kickoff_utc: FUTURE, status: "Scheduled" } },
    ],
    Predictions: [],
  };
  const fetchImpl = async (url, opts = {}) => {
    const u = new URL(url);
    const [, , , tableEnc] = u.pathname.split("/");
    const table = decodeURIComponent(tableEnc || "");
    const method = (opts.method || "GET").toUpperCase();
    const body = opts.body ? JSON.parse(opts.body) : null;
    const ok = (obj) => ({ ok: true, status: 200, json: async () => obj, text: async () => JSON.stringify(obj) });
    if (!tables[table]) return { ok: false, status: 404, text: async () => "no table " + table };
    if (method === "GET") return ok({ records: tables[table] });
    if (method === "DELETE") {
      const ids = u.searchParams.getAll("records[]");
      tables[table] = tables[table].filter((r) => !ids.includes(r.id));
      return ok({ records: ids.map((i) => ({ id: i, deleted: true })) });
    }
    if (method === "PATCH" || method === "POST") {
      if (body.performUpsert) {
        const mergeOn = body.performUpsert.fieldsToMergeOn;
        for (const rec of body.records) {
          const match = tables[table].find((r) => mergeOn.every((f) => r.fields[f] === rec.fields[f]));
          if (match) Object.assign(match.fields, rec.fields);
          else tables[table].push({ id: rid(), fields: rec.fields });
        }
      } else {
        for (const rec of body.records) {
          const match = tables[table].find((r) => r.id === rec.id);
          if (match) Object.assign(match.fields, rec.fields);
          else tables[table].push({ id: rid(), fields: rec.fields || {} });
        }
      }
      return ok({ records: [] });
    }
    return { ok: false, status: 400, text: async () => "unhandled " + method };
  };
  return { tables, fetchImpl };
}

const { onRequest } = await import(ROUTE);
async function call(store, path, body, token = "tok-a") {
  globalThis.fetch = store.fetchImpl;
  const req = new Request(`https://x.test${path}${path.includes("?") ? "&" : "?"}p=${token}`,
    body === undefined ? { method: "GET" }
      : { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
  const res = await onRequest({ request: req, env: { AIRTABLE_PAT: "pat", AIRTABLE_BASE_ID: "base" } });
  return { status: res.status, body: await res.json() };
}
const savebonus = (store, picks, token) => call(store, "/api/savebonus", { picks }, token);
const rowByLabel = (store, lbl) => store.tables.Predictions.find((r) => r.fields.label === lbl);

// ---- pot rows are written ring-fenced --------------------------------------
{
  const store = makeStore();
  const r = await savebonus(store, [
    { key: `bonus|${FID_FINAL}|1`, bet_type: "Hat-trick in match", bet_value: "Yes" },
    { key: `stoppage|${FID_FINAL}|outcome`, team_id: 9 },
    { key: `stoppage|${FID_FINAL}|exact`, score_home: 2, score_away: 1 },
    { key: "stoppage|duel", player_text: "Mbappé" },
  ]);
  check("stoppage slate saves (status 200)", r.status === 200 && r.body.saved === 4);
  const b1 = rowByLabel(store, `Andreas|bonus|${FID_FINAL}|1`);
  check("pot bonus row: type stoppage_bet + pot stoppage",
    b1 && b1.fields.prediction_type === "stoppage_bet" && b1.fields.pot === "stoppage");
  const oc = rowByLabel(store, `Andreas|stoppage|${FID_FINAL}|outcome`);
  check("outcome row links the picked team", oc && Array.isArray(oc.fields.predicted_team) && oc.fields.predicted_team.length === 1);
  const ex = rowByLabel(store, `Andreas|stoppage|${FID_FINAL}|exact`);
  check("exact row carries both scores", ex && ex.fields.predicted_score_home === 2 && ex.fields.predicted_score_away === 1);
  const du = rowByLabel(store, "Andreas|stoppage|duel");
  check("Duel row: side-game link + text + 3rd-place match anchor",
    du && Array.isArray(du.fields.side_game) && du.fields.predicted_text === "Mbappé" && Array.isArray(du.fields.match));
}

// ---- menu + slot gating ----------------------------------------------------
{
  const store = makeStore();
  let r = await savebonus(store, [{ key: `bonus|${FID_GROUP}|1`, bet_type: "Hat-trick in match", bet_value: "Yes" }]);
  check("wild type rejected on a non-pot fixture", r.status === 400);
  r = await savebonus(store, [{ key: `bonus|${FID_GROUP}|3`, bet_type: "BTTS", bet_value: "Yes" }]);
  check("third slot rejected on a non-pot fixture", r.status === 400);
  r = await savebonus(store, [{ key: `bonus|${FID_GROUP}|1`, bet_type: "BTTS", bet_value: "Yes" }]);
  check("classic bet on a non-pot fixture still saves as bonus_bet", r.status === 200 &&
    rowByLabel(store, `Andreas|bonus|${FID_GROUP}|1`).fields.prediction_type === "bonus_bet");
  r = await savebonus(store, [{ key: `bonus|${FID_3RD}|3`, bet_type: "VAR overturn", bet_value: "No" }]);
  check("third slot + wild type accepted on a pot fixture", r.status === 200);
  r = await savebonus(store, [{ key: `stoppage|${FID_GROUP}|outcome`, team_id: 9 }]);
  check("outcome key rejected on a non-pot fixture", r.status === 400);
  r = await savebonus(store, [{ key: "stoppage|duel", player_text: "Ronaldo" }]);
  check("Duel value outside Messi/Mbappé/Level rejected", r.status === 400);
  r = await savebonus(store, [{ key: `stoppage|${FID_FINAL}|exact`, score_home: 2.5, score_away: 1 }]);
  check("non-integer exact score rejected", r.status === 400);
}

// ---- token rules -----------------------------------------------------------
{
  const store = makeStore();
  let r = await savebonus(store, [{ key: `stoppage|${FID_FINAL}|outcome`, team_id: 9, token: "Double" }]);
  check("classic token rejected on a pot row", r.status === 400);
  r = await savebonus(store, [{ key: `bonus|${FID_GROUP}|1`, bet_type: "BTTS", bet_value: "Yes", token: "Stoppage2x" }]);
  check("Stoppage2x rejected on a classic row", r.status === 400);
  r = await savebonus(store, [
    { key: `stoppage|${FID_FINAL}|outcome`, team_id: 9, token: "Stoppage2x" },
    { key: `stoppage|${FID_FINAL}|exact`, score_home: 1, score_away: 0, token: "Stoppage2x" },
  ]);
  check("two Stoppage2x in one save rejected (budget 1)", r.status === 400);
  r = await savebonus(store, [{ key: `stoppage|${FID_FINAL}|outcome`, team_id: 9, token: "Stoppage2x" }]);
  check("single Stoppage2x accepted", r.status === 200 && r.body.stoppageTokensUsed === 1);
  const me = store.tables.PoolPlayers.find((p) => p.fields.name === "Andreas");
  check("stoppage_token_remaining decremented to 0", me.fields.stoppage_token_remaining === 0);
  check("classic token reserves untouched by a pot-only save",
    me.fields.tokens_remaining_double === 4 && me.fields.tokens_remaining_allin === 1);
  // replacing the tokened row without the token refunds it
  r = await savebonus(store, [{ key: `stoppage|${FID_FINAL}|outcome`, team_id: 26 }]);
  check("re-save without token refunds Stoppage2x", r.status === 200 &&
    me.fields.stoppage_token_remaining === 1);
}

// ---- kickoff immutability + clearing ---------------------------------------
{
  const store = makeStore();
  await savebonus(store, [{ key: `bonus|${FID_FINAL}|1`, bet_type: "Own goal in match", bet_value: "Yes" }]);
  let r = await savebonus(store, []);   // clearing while still future → delete
  check("clearing a future pot row deletes it", r.status === 200 &&
    !rowByLabel(store, `Andreas|bonus|${FID_FINAL}|1`));
  store.tables.Matches.find((m) => m.fields.fixture_id === FID_3RD).fields.kickoff_utc = PAST;
  r = await savebonus(store, [{ key: `stoppage|${FID_3RD}|outcome`, team_id: 2 }]);
  check("pot pick on a kicked-off fixture rejected", r.status === 400);
  r = await savebonus(store, [{ key: "stoppage|duel", player_text: "Messi" }]);
  check("Duel locked once the 3rd-place game kicks off", r.status === 400);
  r = await savebonus(store, [{ key: `stoppage|${FID_FINAL}|outcome`, team_id: 26 }]);
  check("Final pot picks still open after the 3rd-place kickoff", r.status === 200);
}

// ---- /api/public sealing ----------------------------------------------------
{
  const store = makeStore();
  await savebonus(store, [
    { key: `stoppage|${FID_FINAL}|outcome`, team_id: 9 },
    { key: "stoppage|duel", player_text: "Level" },
  ]);
  // lock the player so their non-bet picks would normally be visible
  await call(store, "/api/lock", {});
  let pub = await call(store, "/api/public");
  let mine = (pub.body.picks || {}).Andreas || [];
  check("pot rows sealed pre-kickoff even for a locked player",
    mine.every((p) => p.type !== "stoppage_bet"));
  store.tables.Matches.find((m) => m.fields.fixture_id === FID_3RD).fields.status = "Live";
  pub = await call(store, "/api/public");
  mine = (pub.body.picks || {}).Andreas || [];
  check("Duel reveals at the 3rd-place kickoff (its anchor)",
    mine.some((p) => p.key === "stoppage|duel" && p.text === "Level" && p.pot === "stoppage"));
  check("Final pot rows stay sealed until the Final starts",
    !mine.some((p) => p.key === `stoppage|${FID_FINAL}|outcome`));
  store.tables.Matches.find((m) => m.fields.fixture_id === FID_FINAL).fields.status = "Live";
  pub = await call(store, "/api/public");
  mine = (pub.body.picks || {}).Andreas || [];
  check("Final pot rows reveal at the Final kickoff",
    mine.some((p) => p.key === `stoppage|${FID_FINAL}|outcome` && p.pot === "stoppage"));
}

summary("test_api_savebonus_stoppage");
