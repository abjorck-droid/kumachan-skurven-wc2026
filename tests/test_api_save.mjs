// /api/save integration tests: bracket validation + full-replace, through the
// real Pages Function router against a mutable in-memory Airtable stub.
import { makeTeams, makeStructure, check, summary } from "./page_harness.mjs";

const ROUTE = new URL("../functions/api/%5B%5Broute%5D%5D.js", import.meta.url).href;
const teams = makeTeams();
const { go, thirds } = makeStructure(teams);
const idOf = (code) => String(teams.find((t) => t.code === code).id);

// ---- in-memory Airtable ------------------------------------------------------
function makeStore() {
  let auto = 0;
  const rid = () => "rec" + (++auto).toString().padStart(4, "0");
  const tables = {
    PoolPlayers: [{ id: rid(), fields: { name: "Andreas", magic_link_token: "tok-a" } },
                  { id: rid(), fields: { name: "Cal", magic_link_token: "tok-c" } }],
    Teams: teams.map((t) => ({ id: rid(), fields: { team_id: t.id, code: t.code, name: t.name, group: t.group } })),
    SideGames: [], Footballers: [], Matches: [], Predictions: [],
  };
  const fetchImpl = async (url, opts = {}) => {
    const u = new URL(url);
    const [, , base, tableEnc] = u.pathname.split("/");
    const table = decodeURIComponent(tableEnc);
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
    if (method === "PATCH") {
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
        }
      }
      return ok({ records: [] });
    }
    return { ok: false, status: 400, text: async () => "unhandled " + method };
  };
  return { tables, fetchImpl };
}

const { onRequest } = await import(ROUTE);
async function callSave(store, picks, token = "tok-a") {
  globalThis.fetch = store.fetchImpl;
  const req = new Request(`https://x.test/api/save?p=${token}`, {
    method: "POST", body: JSON.stringify({ picks }), headers: { "Content-Type": "application/json" } });
  const res = await onRequest({ request: req, env: { AIRTABLE_PAT: "pat", AIRTABLE_BASE_ID: "base" } });
  return { status: res.status, body: await res.json() };
}

// ---- payload builders ----------------------------------------------------------
function structPicks(overrides = {}) {
  const ps = "ABCDEFGHIJKL".split("").map((g) => ({
    key: "group_order|" + g, type: "bracket_struct", bracket_slot: "group_order|" + g,
    player_text: overrides["group_order|" + g] ?? `${g}T0,${g}T1,${g}T2`,
  }));
  ps.push({ key: "thirds_advance", type: "bracket_struct", bracket_slot: "thirds_advance",
    player_text: overrides.thirds_advance ?? "A,B,C,D,E,F,G,H" });
  return ps;
}
// R32 match k under the official template (mirrors buildR32; fixture thirds = A\u2013H
// \u2192 Annex C row 495 "HGBCAFDE": 1A v 3H, 1B v 3G, 1D v 3B, 1E v 3C, 1G v 3A, 1I v 3F, 1K v 3D, 1L v 3E).
const TOF = { A: "H", B: "G", D: "B", E: "C", G: "A", I: "F", K: "D", L: "E" };
function entrantsOf(k) {
  const W = (l) => go[l][0], RU = (l) => go[l][1], TH = (l) => go[TOF[l]][2];
  return [
    [RU("A"), RU("B")], [W("E"), TH("E")], [W("F"), RU("C")], [W("C"), RU("F")],
    [W("I"), TH("I")], [RU("E"), RU("I")], [W("A"), TH("A")], [W("L"), TH("L")],
    [W("D"), TH("D")], [W("G"), TH("G")], [RU("K"), RU("L")], [W("H"), RU("J")],
    [W("B"), TH("B")], [W("J"), RU("H")], [W("K"), TH("K")], [RU("D"), RU("G")],
  ][k - 1];
}
// official feeds: R16 89\u201396 take winners of these R32 matches, etc.
const FEEDS1 = [[2, 5], [1, 3], [4, 6], [7, 8], [11, 12], [9, 10], [14, 16], [13, 15]];
const FEEDS2 = [[1, 2], [5, 6], [3, 4], [7, 8]];
const FEEDS3 = [[1, 2], [3, 4]];
function fullBracketPicks() {
  const picks = structPicks();
  const w32 = []; for (let k = 1; k <= 16; k++) w32.push(entrantsOf(k)[0]);
  w32.forEach((t, i) => picks.push({ key: "R16-" + (i + 1), type: "bracket_slot", bracket_slot: "R16-" + (i + 1), team_id: t }));
  const w16 = FEEDS1.map((f) => w32[f[0] - 1]);
  w16.forEach((t, i) => picks.push({ key: "QF-" + (i + 1), type: "bracket_slot", bracket_slot: "QF-" + (i + 1), team_id: t }));
  const w8 = FEEDS2.map((f) => w16[f[0] - 1]);
  w8.forEach((t, i) => picks.push({ key: "SF-" + (i + 1), type: "bracket_slot", bracket_slot: "SF-" + (i + 1), team_id: t }));
  const w4 = FEEDS3.map((f) => w8[f[0] - 1]);
  w4.forEach((t, i) => picks.push({ key: "F-" + (i + 1), type: "bracket_slot", bracket_slot: "F-" + (i + 1), team_id: t, token: i === 0 ? "Double" : undefined }));
  picks.push({ key: "Champion", type: "bracket_slot", bracket_slot: "Champion", team_id: w4[0], token: "AllIn" });
  return picks;
}

// ---- tests ---------------------------------------------------------------------
{ // valid full payload saves, stale rows replaced
  const store = makeStore();
  // pre-existing junk: an old random bracket pick + a side pick that must survive
  store.tables.Predictions.push(
    { id: "recOLD1", fields: { label: "Andreas|R32-1", prediction_type: "bracket_slot" } },   // old experiment row — never regenerated
    { id: "recOLD2", fields: { label: "Andreas|Champion", prediction_type: "bracket_slot", confidence_token: "Triple" } },
    { id: "recSIDE", fields: { label: "Andreas|side|Golden Boot", prediction_type: "side_game", predicted_text: "Mbappé" } },
    { id: "recCAL", fields: { label: "Cal|R16-3", prediction_type: "bracket_slot" } });
  const { status, body } = await callSave(store, fullBracketPicks());
  check("valid propagated payload accepted", status === 200);
  check("saves 31 slots + 13 struct rows", body.saved === 44);
  const labels = store.tables.Predictions.map((r) => r.fields.label);
  check("stale bracket row deleted (not in payload)", !labels.includes("Andreas|R32-1") && body.deleted === 1);
  check("Champion upserted in place (same label)", labels.filter((l) => l === "Andreas|Champion").length === 1);
  check("non-bracket pick survives", labels.includes("Andreas|side|Golden Boot"));
  check("opponent rows untouched", labels.includes("Cal|R16-3"));
  const champ = store.tables.Predictions.find((r) => r.fields.label === "Andreas|Champion");
  check("token written on champion", champ.fields.confidence_token === "AllIn");
  check("struct row carries codes", store.tables.Predictions.find((r) => r.fields.label === "Andreas|group_order|A").fields.predicted_text === "AT0,AT1,AT2");
  check("token reserves recomputed", body.tokensUsed.AllIn === 1 && body.tokensUsed.Double === 1);
}
{ // empty bracket wipes all bracket rows (the agreed regenerate-from-scratch path)
  const store = makeStore();
  store.tables.Predictions.push(
    { id: "recO1", fields: { label: "Andreas|R16-1", prediction_type: "bracket_slot" } },
    { id: "recO2", fields: { label: "Andreas|group_order|A", prediction_type: "bracket_struct" } });
  const { status, body } = await callSave(store, []);
  check("empty payload accepted", status === 200);
  check("wipe deletes all bracket rows", body.deleted === 2 && store.tables.Predictions.every((r) => !r.fields.label.startsWith("Andreas|R16") && !r.fields.label.startsWith("Andreas|group_order")));
}
{ // duplicate team in a round
  const picks = fullBracketPicks();
  picks.find((p) => p.key === "R16-2").team_id = picks.find((p) => p.key === "R16-1").team_id;
  const { status, body } = await callSave(makeStore(), picks);
  check("duplicate in round → 400", status === 400 && /duplicate/.test(body.error));
}
{ // nesting violation: champion not among finalists
  const picks = fullBracketPicks();
  picks.find((p) => p.key === "Champion").team_id = picks.find((p) => p.key === "F-2").team_id === idOf("AT0") ? idOf("BT0") : idOf("ET0");
  // (fixture-dependent: ensured non-final below)
  // ensure champion team is NOT in F set
  const fset = picks.filter((p) => /^F-/.test(p.key)).map((p) => String(p.team_id));
  if (fset.includes(String(picks.find((p) => p.key === "Champion").team_id)))
    picks.find((p) => p.key === "Champion").team_id = idOf("LT2");
  const { status, body } = await callSave(makeStore(), picks);
  check("non-nested champion → 400", status === 400 && /nested|qualifiers|path|duplicate/.test(body.error));
}
{ // same-path hedge: both sides of R32 match 1 in the R16 set
  const picks = fullBracketPicks();
  const [a, b] = entrantsOf(16);
  // R16-16 already holds a (RU D); repoint R16-15 at b (RU G, the other side of M88).
  // M87/M88 winners feed no QF pick in this fixture, so nesting stays intact.
  picks.find((p) => p.key === "R16-15").team_id = b;
  const { status, body } = await callSave(makeStore(), picks);
  check("both sides of one tie → 400", status === 400 && /same bracket path/.test(body.error));
}
{ // R16 pick outside the 32 qualifiers
  const picks = fullBracketPicks();
  picks.find((p) => p.key === "R16-16").team_id = idOf("AT3");  // 4th of group A never qualifies
  const { status, body } = await callSave(makeStore(), picks);
  check("non-qualifier in R16 → 400", status === 400 && /32 qualifiers/.test(body.error));
}
{ // bad team code in group order
  const picks = structPicks({ "group_order|B": "AT0,BT1,BT2" });
  const { status, body } = await callSave(makeStore(), picks);
  check("wrong-group code → 400", status === 400 && /not in group B/.test(body.error));
}
{ // malformed thirds
  const { status } = await callSave(makeStore(), structPicks({ thirds_advance: "A,A,B" }));
  check("duplicate thirds letters → 400", status === 400);
  const r2 = await callSave(makeStore(), structPicks({ thirds_advance: "A,B,C,D,E,F,G,H,I" }));
  check("nine thirds → 400", r2.status === 400);
}
{ // unknown slot key
  const { status, body } = await callSave(makeStore(), [{ key: "R64-1", type: "bracket_slot", bracket_slot: "R64-1", team_id: idOf("AT0") }]);
  check("unknown slot key → 400", status === 400 && /unknown bracket slot/.test(body.error));
}
{ // partial structure (mid-edit save) passes set-level checks only
  const picks = structPicks().slice(0, 5);   // 5 of 12 group orders, no thirds
  const { status } = await callSave(makeStore(), picks);
  check("partial structure accepted", status === 200);
}
{ // legacy payload: coherent sets, no structure rows
  const a = idOf("AT0");
  const picks = [
    { key: "R16-1", type: "bracket_slot", bracket_slot: "R16-1", team_id: a },
    { key: "QF-1", type: "bracket_slot", bracket_slot: "QF-1", team_id: a },
  ];
  const { status } = await callSave(makeStore(), picks);
  check("legacy set-only payload accepted", status === 200);
}
{ // legacy payload violating nesting still rejected
  const picks = [{ key: "Champion", type: "bracket_slot", bracket_slot: "Champion", team_id: idOf("AT0") }];
  const { status, body } = await callSave(makeStore(), picks);
  check("set-level nesting enforced without structure", status === 400 && /nested/.test(body.error));
}

summary("test_api_save");
