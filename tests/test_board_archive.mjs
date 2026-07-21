// Post-tournament Scoreboard archive + pundit-note visibility (2026-07-21 work).
// Renders site/live.html's boardTab against the REAL season export shaped exactly like
// /api/public (including the new "scored pot rows count as resolved" unseal rule) and
// checks: every scorecard surfaces, sections come newest-first, and every match-linked
// pundit note in the base is visible on the board. Node 18+, stdlib only.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const EXP = join(ROOT, "data", "season_export");
const load = (t) => JSON.parse(readFileSync(join(EXP, t + ".json"), "utf8"));

// ---- shape the export like functions/api/[[route]].js publicPayload ----------
function apiShape() {
  const teamsRaw = load("Teams"), matchesRaw = load("Matches"),
        predsRaw = load("Predictions"), poolRaw = load("PoolPlayers"),
        footRaw = load("Footballers"), sgRaw = load("SideGames");
  const teamByRec = {}, teams = [];
  for (const r of teamsRaw) {
    const f = r.fields || {};
    if (f.team_id == null) continue;
    teamByRec[r.id] = { team_id: f.team_id, code: f.code, name: f.name, group: f.group };
    teams.push({ id: f.team_id, code: f.code, name: f.name, group: f.group,
      kit: f.kit_color || null, flag: f.flag || null });
  }
  const matchByRec = {}, matches = [];
  for (const r of matchesRaw) {
    const f = r.fields || {};
    if (f.fixture_id == null) continue;
    matchByRec[r.id] = f.fixture_id;
    const hi = teamByRec[(f.home_team || [])[0]] || {}, ai = teamByRec[(f.away_team || [])[0]] || {};
    matches.push({ fixture_id: f.fixture_id, round: f.round, group: hi.group || ai.group,
      kickoff: f.kickoff_utc, status: f.status, venue: f.venue || null,
      home_id: hi.team_id ?? null, away_id: ai.team_id ?? null,
      home_code: hi.code || null, away_code: ai.code || null,
      home_name: hi.name || null, away_name: ai.name || null,
      home_score: f.home_score ?? null, away_score: f.away_score ?? null,
      winner_method: f.winner_method || null, elapsed: f.elapsed ?? null });
  }
  matches.sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || ""));
  const footName = {};
  for (const r of footRaw) footName[r.id] = (r.fields || {}).name;
  const sgByRec = {};
  const sideGames = sgRaw.map((r) => {
    sgByRec[r.id] = (r.fields || {}).name;
    const f = r.fields || {};
    return { name: f.name, base_points: f.base_points, resolved_value: f.resolved_value || null };
  });
  const playerNames = poolRaw.map((r) => (r.fields || {}).name).filter(Boolean);
  const picks = {};
  for (const n of playerNames) picks[n] = [];
  for (const r of predsRaw) {
    const f = r.fields || {};
    const lbl = f.label || "";
    const owner = playerNames.find((n) => lbl.startsWith(n + "|"));
    if (!owner) continue;
    const p = {
      key: lbl.split("|").slice(1).join("|"),
      type: f.prediction_type,
      bracket_slot: f.bracket_slot || null,
      side_game: (f.side_game || []).length ? (sgByRec[f.side_game[0]] || null) : null,
      match_id: (f.match || []).length ? (matchByRec[f.match[0]] ?? null) : null,
      team_id: (f.predicted_team || []).length ? (teamByRec[f.predicted_team[0]] || {}).team_id ?? null : null,
      player_name: (f.predicted_player || []).length ? (footName[f.predicted_player[0]] || null) : null,
      text: f.predicted_text || null,
      outcome: f.predicted_outcome || null,
      score_home: f.predicted_score_home ?? null,
      score_away: f.predicted_score_away ?? null,
      bet_type: f.bonus_bet_type || null,
      bet_value: f.bonus_bet_value || null,
      token: f.confidence_token || null,
      pot: f.pot || null,
      pot_points: f.pot_points ?? null,
      points: f.points_awarded ?? null,
      rival_bonus: f.beat_rival_bonus ?? null,
      resolved: !!f.resolved,
      has_note: !!f.pundit_note,
    };
    // the rule under test — mirrors functions/api/[[route]].js
    const unsealed = f.resolved || (f.pot === "stoppage" && f.pot_points != null);
    if (unsealed && f.pundit_note) p.note = f.pundit_note;
    picks[owner].push(p);
  }
  const players = poolRaw.map((r) => {
    const f = r.fields || {};
    return { name: f.name, total_score: f.total_score ?? 0, stoppage_pot: f.stoppage_pot ?? 0,
      stoppage_token: f.stoppage_token_remaining ?? null,
      tokens: {}, locked: true, locked_at: "2026-06-10T00:00:00Z" };
  });
  return { players, teams, matches, standings: [], sideGames, scorers: [], picks,
    _predsRaw: predsRaw, _matchByRec: matchByRec };
}

// ---- load the whole live.html script with a stub DOM -------------------------
function stubEl() {
  return { addEventListener() {}, style: {}, textContent: "", innerHTML: "",
    classList: { toggle() {}, add() {}, remove() {} }, dataset: {} };
}
const html = readFileSync(join(ROOT, "site", "live.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const els = {};
const document = {
  querySelector(sel) { return (els[sel] ||= stubEl()); },
  querySelectorAll() { return []; },
  getElementById(id) { return (els["#" + id] ||= stubEl()); },
  addEventListener() {},
};
const sandbox = {
  document, location: { search: "", hostname: "test.invalid" },
  URLSearchParams, setTimeout, clearTimeout, setInterval: () => 0, console,
  fetch: () => Promise.reject(new Error("no network in tests")),
  Date, JSON, Math, addEventListener() {},
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(scripts[scripts.length - 1][1], sandbox, { filename: "live.html#script" });

let PASS = 0, FAIL = 0;
function check(label, cond) {
  if (cond) { PASS++; console.log("  ✓ " + label); }
  else { FAIL++; console.log("  ✗ " + label); }
}

const D = apiShape();
sandbox.D = D;
sandbox.IDX = sandbox.indexData(D);
const board = sandbox.boardTab();

// ---- scorecards: every finished fixture surfaces on the board ----------------
const fin = D.matches.filter((m) => m.status === "Finished");
check(`tournament complete in export (${fin.length}/${D.matches.length} finished)`,
  fin.length === D.matches.length && fin.length >= 100);
const missingCards = fin.filter((m) =>
  !(board.includes(m.home_code) && board.includes(m.away_code) &&
    board.includes(String(m.venue ? m.venue.split(",")[0] : ""))) &&
  // cheap per-card fingerprint: round label + both codes in one card div
  !board.split('<div class="mcard').some((c) => c.includes(m.home_code) && c.includes(m.away_code)));
check(`all ${fin.length} scorecards present on the Scoreboard`, missingCards.length === 0);
check("archive headline present", board.includes("The full record") && board.includes("The Final"));

// section order: newest stage first
const order = ["Third place", "Semi-finals", "Quarter-finals", "Round of 16", "Round of 32",
  "Group stage · Matchday 3", "Group stage · Matchday 2", "Group stage · Matchday 1"];
const idxs = order.map((s) => board.indexOf(s));
check("sections newest-first: " + order.map((s, i) => idxs[i] >= 0 ? "✓" : s).join("").replace(/✓+/, "all found"),
  idxs.every((x) => x >= 0) && idxs.every((x, i) => i === 0 || x > idxs[i - 1]));
check("no 'Up next' / 'Latest results' remnants", !board.includes("Up next") && !board.includes("Latest results"));

// ---- pundit notes: every match-linked note in the base is on the board -------
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const matchLinked = [];
for (const r of D._predsRaw) {
  const f = r.fields || {};
  if (!f.pundit_note) continue;
  const t = f.prediction_type;
  if (t === "match_outcome" || t === "bonus_bet" || t === "stoppage_bet") {
    matchLinked.push({ label: f.label, note: f.pundit_note, type: t });
  }
}
const missingNotes = matchLinked.filter((n) => !board.includes(esc(n.note)));
check(`all ${matchLinked.length} match-linked pundit notes visible on the board`,
  missingNotes.length === 0);
for (const n of missingNotes) console.log(`      missing: ${n.label} (${n.type})`);
const potNotes = matchLinked.filter((n) => n.type === "stoppage_bet");
check(`incl. all ${potNotes.length} pot-row notes on the last two fixtures (previously sealed)`,
  potNotes.length === 17 && potNotes.every((n) => board.includes(esc(n.note))));
check("no sealed-note placeholders remain on the board", !board.includes("pundit note sealed"));

// spot checks from the wrap-up material
["COCKS AND BALLS!", "THE KING REIGNS.", "AIIIIIIIIIIIII!!!!!"].forEach((s) =>
  check(`spot check: “${s.slice(0, 20)}…” visible`, board.includes(esc(s))));

console.log(`\ntest_board_archive: ${PASS}/${PASS + FAIL} checks passed`);
if (FAIL) process.exit(1);
