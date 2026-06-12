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

// ---- all groups done but thirds ranking missing: rank 3 stays pending ---------
elim = T.eliminatedSet({ standings: st, matches: [] });
check("no thirds table → no third marked out", GROUPS.split("").every((g, gi) => !elim[100 + gi * 4 + 3]));

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

console.log(`test_live_alive: ${PASS}/${PASS + FAIL} checks passed`);
process.exit(FAIL ? 1 : 0);
