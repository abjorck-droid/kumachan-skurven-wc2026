// "Still alive" elimination logic on the live board (site/live.html PURE block).
// Conservative by design: a team is marked out only when it is mathematically certain.
// Node 18+, stdlib only.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "site", "live.html"), "utf8");
const m = /\/\* =+ PURE-START[\s\S]*?=+ \*\/([\s\S]*?)\/\* =+ PURE-END/.exec(html);
if (!m) { console.error("✗ could not extract PURE block from live.html"); process.exit(1); }
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(m[1], sandbox, { filename: "live.html#pure" });
const T = sandbox;

let PASS = 0, FAIL = 0;
function check(label, cond) {
  if (cond) { PASS++; console.log("  ✓ " + label); }
  else { FAIL++; console.log("  ✗ " + label); }
}

// ---- fixtures ----------------------------------------------------------------
const GROUPS = "ABCDEFGHIJKL";
function groupRows(playedByRank) {           // playedByRank: games played per rank 1..4
  const rows = [];
  GROUPS.split("").forEach((g, gi) => {
    for (let r = 1; r <= 4; r++)
      rows.push({ group: g, rank: r, team_id: 100 + gi * 4 + r, played: playedByRank[r - 1] });
  });
  return rows;
}
function thirdsRows() {                       // third-placed team of group gi has id 100+gi*4+3
  return GROUPS.split("").map((g, gi) => ({ group: "3rd", rank: gi + 1, team_id: 100 + gi * 4 + 3 }));
}

// ---- group stage, mid-play: nobody is out -------------------------------------
let elim = T.eliminatedSet({ standings: groupRows([1, 1, 1, 1]), matches: [] });
check("matchday 1: nobody eliminated", Object.keys(elim).length === 0);

elim = T.eliminatedSet({ standings: groupRows([2, 2, 2, 2]), matches: [] });
check("matchday 2: nobody eliminated", Object.keys(elim).length === 0);

// ---- one group finishes early: its rank-4 is out, rank-3 still pending --------
let st = groupRows([1, 1, 1, 1]);
st.forEach(s => { if (s.group === "A") s.played = 3; });
elim = T.eliminatedSet({ standings: st, matches: [] });
check("finished group: rank 4 out", elim[104] === true);
check("finished group: rank 3 waits for thirds", !elim[103]);
check("finished group: top 2 alive", !elim[101] && !elim[102]);
check("unfinished groups untouched", Object.keys(elim).length === 1);

// ---- all groups done, thirds ranking present ----------------------------------
st = groupRows([3, 3, 3, 3]);
elim = T.eliminatedSet({ standings: st.concat(thirdsRows()), matches: [] });
check("all 12 rank-4 teams out", GROUPS.split("").every((g, gi) => elim[100 + gi * 4 + 4]));
check("best 8 thirds alive", !elim[103] && !elim[131]);          // thirds ranks 1 and 8
check("thirds ranked 9-12 out", elim[135] && elim[139] && elim[143] && elim[147]);
check("group winners and runners-up alive", !elim[101] && !elim[102] && !elim[145] && !elim[146]);

// ---- all groups done, no thirds table AND no ranking data: stay conservative ---
// groupRows() carries no points, so the bottom-4 can't be ranked → mark none out.
elim = T.eliminatedSet({ standings: st, matches: [] });
check("no thirds table & no ranking data → no third marked out", GROUPS.split("").every((g, gi) => !elim[100 + gi * 4 + 3]));

// ---- all groups done, no thirds table, but group tables carry ranking data ----
// API-Football has no best-thirds table, so eliminatedSet derives it from the 12
// group tables (points, then goal diff, then goals for) and cuts the bottom four.
let st3 = groupRows([3, 3, 3, 3]);
st3.forEach(s => { if (s.rank === 3) { const gi = GROUPS.indexOf(s.group); s.points = 12 - gi; s.gd = 0; s.gf = 0; } });
elim = T.eliminatedSet({ standings: st3, matches: [] });
check("derived thirds: bottom 4 (groups I–L) out", elim[135] && elim[139] && elim[143] && elim[147]);
check("derived thirds: best 8 (groups A–H) alive", "ABCDEFGH".split("").every((g, i) => !elim[100 + i * 4 + 3]));
check("derived thirds: all 12 rank-4 still out", GROUPS.split("").every((g, gi) => elim[100 + gi * 4 + 4]));
check("derived thirds: exactly 16 out (12 fourths + 4 thirds)", Object.keys(elim).length === 16);

// tie-break: equal points → lower goal diff is eliminated
let st4 = groupRows([3, 3, 3, 3]);
st4.forEach(s => { if (s.rank === 3) { const gi = GROUPS.indexOf(s.group); s.points = 3; s.gd = 12 - gi; s.gf = 0; } });
elim = T.eliminatedSet({ standings: st4, matches: [] });
check("derived thirds tie-break uses goal diff", elim[135] && elim[139] && elim[143] && elim[147] && !elim[103]);

// ---- knockouts -----------------------------------------------------------------
const ko = (round, home, away, winner, status) =>
  ({ round, home_id: home, away_id: away, winner_id: winner ?? null, status: status || "Finished" });

elim = T.eliminatedSet({ standings: [], matches: [ko("Round of 32", 101, 134, 101)] });
check("KO loser out", elim[134] === true);
check("KO winner alive", !elim[101]);

elim = T.eliminatedSet({ standings: [], matches: [ko("Round of 32", 101, 134, null, "Live")] });
check("live KO match: nobody out yet", Object.keys(elim).length === 0);

elim = T.eliminatedSet({ standings: [], matches: [ko("Group Stage - 1", 101, 102, 101)] });
check("group match loser NOT out", Object.keys(elim).length === 0);

elim = T.eliminatedSet({ standings: [], matches: [ko("Semi-finals", 101, 105, 101), ko("Semi-finals", 110, 120, 110), ko("Third place play-off", 105, 120, 105)] });
check("3rd-place playoff adds nothing new", elim[105] && elim[120] && !elim[101] && !elim[110] && Object.keys(elim).length === 2);

// penalties: winner_id set, scores level — loser must still be out
elim = T.eliminatedSet({ standings: [], matches: [{ round: "Final", home_id: 101, away_id: 110, winner_id: 110, status: "Finished", winner_method: "Penalties", home_score: 1, away_score: 1 }] });
check("penalty-shootout loser out", elim[101] === true && !elim[110]);

// ---- deadPickCount -------------------------------------------------------------
const picksD = {
  Andreas: [
    { type: "bracket_slot", bracket_slot: "SF-1", team_id: 1 },            // dead (open, team out)
    { type: "bracket_slot", bracket_slot: "QF-1", team_id: 1, resolved: true, points: 0 }, // resolved → not counted
    { type: "bracket_slot", bracket_slot: "SF-2", team_id: 5 },            // alive
    { type: "dark_horse", team_id: 9 },                                    // dead
    { type: "match_outcome", match_id: 7, team_id: 1 },                    // wrong type → not counted
  ],
  Cal: [{ type: "bracket_slot", bracket_slot: "Champion", team_id: 1 }],   // dead
};
check("deadPickCount counts open bracket+DH picks on out teams",
  T.deadPickCount({ picks: picksD }, { 1: true, 9: true }) === 3);
check("deadPickCount zero when nobody out", T.deadPickCount({ picks: picksD }, {}) === 0);

// ---- tree-view rendering (bkChip / bkChampion, extracted with stub globals) -----
function grab(name) {
  const mm = html.match(new RegExp("function " + name + "\\(([^)]*)\\)\\{[\\s\\S]*?\\n\\}"));
  if (!mm) throw new Error("could not extract " + name);
  return mm[0];
}
const tree = {
  esc: s => String(s == null ? "" : s), tokenName: t => t,
  P1: () => ({ name: "Andreas" }), P2: () => ({ name: "Cal" }),
  BRK_MODE: "H",
  BR_SRC: { 101: ["W97", "W98"] },
  NEXT_TIER: { r32: "R16", r16: "QF", qf: "SF", sf: "Finalist", f: "Champion" },
  numRound: () => "sf",
  KOIDX: { 101: { status: "Finished", winner_id: 5, home_id: 5, away_id: 1 } },
  LSETS: { Andreas: { Finalist: { 1: { team_id: 1 } } }, Cal: {} },     // Andreas picked the loser to advance
  IDX: { teamById: { 5: { code: "ESP", kit: "#a00" }, 1: { code: "MEX", kit: "#0a5" } },
         picksBy: { Andreas: { Champion: { team_id: 1 } }, Cal: { Champion: { team_id: 5 } } },
         elim: { 1: true } },
};
vm.createContext(tree);
vm.runInContext(grab("bkChip") + "\n" + grab("bkChampion"), tree, { filename: "live.html#tree" });

const chip = vm.runInContext("bkChip(101)", tree);
const slots = chip.split("bk-slot").slice(1);            // [winner slot, loser slot]
check("tree chip: winner slot has ✓, no strike", slots[0].includes("✓") && !slots[0].includes("lost"));
check("tree chip: loser slot struck", /^[^>]*lost/.test(slots[1]));
check("tree chip: dead pick gets ✕", slots[1].includes("✕") && !slots[0].includes("✕"));
const champ = vm.runInContext("bkChampion()", tree);
check("champion box: dead pick marked", champ.includes("✕ out") && /tm dead/.test(champ));
check("champion box: live pick clean", champ.split('rw c')[1].indexOf("✕") === -1);

const tree2 = Object.assign({}, tree, { KOIDX: { 101: { status: "Live", winner_id: null, home_id: 5, away_id: 1 } } });
vm.createContext(tree2);
vm.runInContext(grab("bkChip"), tree2, { filename: "live.html#tree2" });
check("tree chip: live match — no strike, no ✕", !vm.runInContext("bkChip(101)", tree2).includes("lost"));
check("tree chip: non-mulligan pick has no ↺", !vm.runInContext("bkChip(101)", tree2).includes("↺"));

// bracket chip flags a slot reached via a mulligan replacement
const tree3 = Object.assign({}, tree, {
  KOIDX: { 101: { status: "Scheduled", winner_id: null, home_id: 5, away_id: 1 } },
  LSETS: { Andreas: { Finalist: { 1: { team_id: 1, mulliganed: true } } }, Cal: {} },
});
vm.createContext(tree3);
vm.runInContext(grab("bkChip"), tree3, { filename: "live.html#tree3" });
check("tree chip: mulligan replacement slot shows ↺", vm.runInContext("bkChip(101)", tree3).includes("↺"));

// ---- resolveMulligans: sibling "<slot>|mull" overrides the original locked pick ----
// A mulligan replacement is written as a sibling row; slot-keyed renderers must show
// the replacement, not the original, or the swap is invisible (the live-board bug).
const dhList = [
  { key: "darkhorse", type: "dark_horse", team_id: 777 },            // original (Türkiye)
  { key: "darkhorse|mull", type: "dark_horse", team_id: 5 },         // replacement
  { key: "R16-1", type: "bracket_slot", bracket_slot: "R16-1", team_id: 99 },
  { key: "R16-1|mull", type: "bracket_slot", bracket_slot: "R16-1", team_id: 5529 },
  { key: "QF-2", type: "bracket_slot", bracket_slot: "QF-2", team_id: 31 },   // untouched
];
const rm = T.resolveMulligans(dhList);
const byKey = Object.fromEntries(rm.map(p => [p.key, p]));
check("resolveMulligans: dark horse shows replacement team", byKey["darkhorse"].team_id === 5);
check("resolveMulligans: dark horse flagged + remembers original", byKey["darkhorse"].mulliganed === true && byKey["darkhorse"].was_team_id === 777);
check("resolveMulligans: bracket slot shows replacement team", byKey["R16-1"].team_id === 5529 && byKey["R16-1"].bracket_slot === "R16-1");
check("resolveMulligans: untouched pick passes through", byKey["QF-2"].team_id === 31 && !byKey["QF-2"].mulliganed);
check("resolveMulligans: no '|mull' keys leak through", rm.every(p => !/\|mull$/.test(p.key)));
check("resolveMulligans: pick count collapses siblings (5→3)", rm.length === 3);
check("resolveMulligans: empty + null tolerated", T.resolveMulligans([]).length === 0 && T.resolveMulligans(null).length === 0);

// the replacement, not the original, drives bracket-advance highlighting (ladderSets)
const ls = T.ladderSets({ picks: { Andreas: dhList } });
check("ladderSets: replacement team in tier set", !!(ls.Andreas.R16 && ls.Andreas.R16[5529]));
check("ladderSets: original team NOT in tier set", !(ls.Andreas.R16 && ls.Andreas.R16[99]));

// ---- softColor: -soft fills must FOLLOW the runtime player colors ------------
// Regression 2026-07-05: --p1/--p2 came from PoolPlayers but --p1-soft/--p2-soft
// stayed hard-coded blue/orange → with Cal as players[0], every bracket-tree cell
// had the correct edge bar and FLIPPED shading.
check("softColor: 6-digit hex → rgba", T.softColor("#219ebc", 0.16) === "rgba(33, 158, 188, 0.16)");
check("softColor: Cal's orange", T.softColor("#fb8500", 0.15) === "rgba(251, 133, 0, 0.15)");
check("softColor: 3-digit hex expands", T.softColor("#abc", 0.2) === "rgba(170, 187, 204, 0.2)");
check("softColor: missing '#' tolerated", T.softColor("219ebc", 0.16) === "rgba(33, 158, 188, 0.16)");
check("softColor: garbage → null (CSS defaults keep working)", T.softColor("periwinkle", 0.16) === null);
check("softColor: null/empty → null", T.softColor(null, 0.16) === null && T.softColor("", 0.16) === null);
// wiring: the runtime setter exists, and no hard-coded both-gradient remains in CSS
check("softColor: --p1-soft set from player color at runtime", /setProperty\("--p1-soft"/.test(html));
check("softColor: .pboth gradient uses the CSS vars", /\.bk-slot\.pboth\{background:linear-gradient\(90deg,var\(--p1-soft\),var\(--p2-soft\)\)/.test(html));
check("softColor: .ttag.both gradient uses the CSS vars", /\.ttag\.both\{background:linear-gradient\(90deg, ?var\(--p1-soft\), ?var\(--p2-soft\)\)/.test(html));

// ---- v1.2 stoppage pot (docs 08/09): ring-fenced display --------------------
// Pot rows (type "stoppage_bet") must never join category totals; the header shows
// each player's pot; the two pot fixtures get their own strip with NO voiding
// (co-participation is waived for the pot) and labels for outcome/exact/Duel/wild.
{
  check("pot: fixture list is the 3rd place + Final pair",
        Array.isArray(T.STOPPAGE_FIXTURES) && T.STOPPAGE_FIXTURES.join(",") === "1591865,1591866" &&
        T.isStoppageFixture(1591866) && T.isStoppageFixture("1591865") && !T.isStoppageFixture(100));
  const picks = [
    { key: "stoppage|1591866|outcome", type: "stoppage_bet", match_id: 1591866, team_id: 9 },
    { key: "stoppage|1591866|exact", type: "stoppage_bet", match_id: 1591866, score_home: 2, score_away: 1 },
    { key: "stoppage|duel", type: "stoppage_bet", match_id: 1591865, text: "Mbappé" },
    { key: "bonus|1591866|3", type: "stoppage_bet", match_id: 1591866, bet_type: "Hat-trick in match", bet_value: "Yes" },
    { key: "bonus|100|1", type: "bonus_bet", match_id: 100, bet_type: "BTTS", bet_value: "Yes" },
  ];
  const tb = { 9: { code: "ESP" } };
  check("pot: stopPicksFor filters by type+fixture (Duel rides the 3rd-place anchor)",
        T.stopPicksFor(picks, 1591866).length === 3 && T.stopPicksFor(picks, 1591865).length === 1);
  check("pot: bonusPicksFor ignores stoppage rows", T.bonusPicksFor(picks, 1591866).length === 0);
  check("pot: outcome label resolves the team code", T.stoppageLabel(picks[0], tb) === "Winner ESP");
  check("pot: exact label", T.stoppageLabel(picks[1], tb) === "Exact 2–1");
  check("pot: Duel label", T.stoppageLabel(picks[2], tb) === "Duel Mbappé");
  check("pot: yes-only wild bet renders without the redundant value",
        T.stoppageLabel(picks[3], tb) === "Hat-trick" &&
        T.bonusLabel({ bet_type: "Decided on penalties", bet_value: "Yes" }) === "Pens");
  check("pot: two-sided wild bet keeps its value suffix",
        T.bonusLabel({ bet_type: "VAR overturn", bet_value: "No" }) === "VAR No" &&
        T.bonusLabel({ bet_type: "Extra time played", bet_value: "Yes" }) === "ET Yes");
  check("pot: classic short labels intact", T.bonusLabel({ bet_type: "VAR overturn", bet_value: "No" }) === "VAR No" &&
        T.bonusLabel({ bet_type: "BTTS", bet_value: "Yes" }) === "BTTS Yes");
  check("pot: header renders stoppage_pot + ×2-in-hand tag",
        /stoppage_pot!=null\?'<div class="meta pot">Stoppage pot '/.test(html) &&
        /stoppage_token===1\?' · ×2 in hand'/.test(html));
  check("pot: header pot line is accent-coded in CSS", /\.h2h \.meta\.pot\{color:var\(--accent\)\}/.test(html));
  check("pot: bonusStrip routes pot fixtures to stoppageStrip",
        /if\(isStoppageFixture\(m\.fixture_id\)\) return stoppageStrip\(m, startedM, fin\);/.test(html));
  check("pot: stoppageStrip never voids (no co-participation)", !/voided|one-sided/.test(
        (/function stoppageStrip\([\s\S]*?\n\}/.exec(html) || [""])[0]));
  check("pot: stoppageStrip marks use pot_points, not points",
        /pot_points>0 \? ' <span class="hitm">/.test(html));
  check("pot: category totals still ignore stoppage rows (ring-fence)",
        !/p\.type==="stoppage_bet"[^\n]*c\.(match|bracket|side|dark|bonus)/.test(html));
  // 07-18 regressions: the Duel's picks are stoppage_bet rows — the Side Bets tab must
  // match them by side_game name and score the chip from pot_points; pundit notes must
  // render in both strips (they never did in the classic bonus strip).
  check("pot: side-bets tab matches stoppage_bet picks by side_game name",
        /q\.type==="side_game"\|\|q\.type==="stoppage_bet"\)&&q\.side_game===sg\.name/.test(html));
  check("pot: side-bets chip scores pot rows from pot_points",
        /var val=\(p\.pot==="stoppage"\)\?p\.pot_points:p\.points;/.test(html));
  check("pot: stoppage strip renders pundit note-lines",
        /stoppageStrip[\s\S]*?note-line[\s\S]*?function bonusStrip/.test(html));
  check("pot: classic bonus strip renders pundit note-lines too",
        /function bonusStrip\([\s\S]*?note-line/.test(html));
}

// ---- bracket-tree Fit view: min-width must cover the columns' summed width ----
// Regression 2026-07-05: columns totalled 1460px but min-width said 1380px, so
// offsetWidth under-reported the content, Fit scaled by the wrong ratio, and the
// right Round-of-32 column was clipped (fit mode hides overflow-x).
{
  const colW   = parseInt((/\.bk-col\{[^}]*flex:0 0 (\d+)px/.exec(html) || [])[1], 10);
  const finalW = parseInt((/\.bk-col\.final-col\{[^}]*flex:0 0 (\d+)px/.exec(html) || [])[1], 10);
  const minW   = parseInt((/\.bk-bracket\{[^}]*min-width:(\d+)px/.exec(html) || [])[1], 10);
  const sideCols = (html.match(/side:"[LR]",head:/g) || []).length;   // BR_COLS entries
  check("tree CSS: column widths parsed", !isNaN(colW) && !isNaN(finalW) && !isNaN(minW));
  check("tree CSS: 8 side columns + 1 final column", sideCols === 8);
  check("tree CSS: min-width covers summed column width (" + (sideCols * colW + finalW) + "px)",
        minW >= sideCols * colW + finalW);
  check("tree JS: Fit measures scrollWidth as an overflow net", /Math\.max\(bracket\.scrollWidth,bracket\.offsetWidth\)/.test(html));
}

console.log(`test_live_alive: ${PASS}/${PASS + FAIL} checks passed`);
process.exit(FAIL ? 1 : 0);
