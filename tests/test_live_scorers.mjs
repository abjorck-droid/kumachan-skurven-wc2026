// Top Scorers tab rendering (site/live.html scorersTab), extracted with stub globals.
// Covers: 0-goal filtering, goals→assists→name ordering, competition ranking with
// shared places, team flag/code lookup, and the empty-state notice. Node 18+, stdlib.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "site", "live.html"), "utf8");

function grab(name) {
  const mm = html.match(new RegExp("function " + name + "\\(([^)]*)\\)\\{[\\s\\S]*?\\n\\}"));
  if (!mm) throw new Error("could not extract " + name);
  return mm[0];
}

let PASS = 0, FAIL = 0;
function check(label, cond) {
  if (cond) { PASS++; console.log("  ✓ " + label); }
  else { FAIL++; console.log("  ✗ " + label); }
}

const ctx = {
  esc: s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  IDX: { teamById: { 1: { code: "MEX", flag: "🇲🇽" }, 2: { code: "CRO", flag: "🇭🇷" } } },
  D: { scorers: [
    { name: "Alpha",   team_id: 1, goals: 3, assists: 1 },
    { name: "Charlie", team_id: 1, goals: 2, assists: 0 },   // fewer assists than Bravo
    { name: "Bravo",   team_id: 2, goals: 2, assists: 2 },   // ties Charlie on goals
    { name: "Delta",   team_id: 2, goals: 1, assists: 5 },
    { name: "Zulu",    team_id: 1, goals: 0, assists: 9 },   // no goals → excluded
  ] },
};
vm.createContext(ctx);
vm.runInContext(grab("scorersTab"), ctx, { filename: "live.html#scorers" });
const out = vm.runInContext("scorersTab()", ctx);

check("0-goal player excluded", !out.includes("Zulu"));
check("scorers with goals shown", out.includes("Alpha") && out.includes("Bravo") && out.includes("Delta"));

// ordering: goals desc, then assists desc (Bravo before Charlie), then name
const iA = out.indexOf("Alpha"), iB = out.indexOf("Bravo"), iC = out.indexOf("Charlie"), iD = out.indexOf("Delta");
check("top scorer first", iA < iB);
check("assist tiebreak orders Bravo above Charlie", iB < iC);
check("fewer goals ranked lower", iC < iD);

// competition ranking: 1, 2, 2, 4 (tie shares place, next place skips)
check("rank 1 for the leader", out.includes('<td>1</td><td class="tm">Alpha</td>'));
check("tied players both rank 2", out.includes('<td>2</td><td class="tm">Bravo</td>') &&
                                   out.includes('<td>2</td><td class="tm">Charlie</td>'));
check("place skips after a tie (Delta = 4)", out.includes('<td>4</td><td class="tm">Delta</td>'));

// team rendering via IDX + goals emphasised in the points column
check("team flag + code rendered", out.includes("🇲🇽") && out.includes("MEX"));
check("goals in the emphasised column", out.includes('<td class="ptscol">3</td>'));

// empty state
ctx.D = { scorers: [] };
check("no goals yet → notice", vm.runInContext("scorersTab()", ctx).includes("No goals yet"));
ctx.D = { };
check("missing scorers key tolerated", vm.runInContext("scorersTab()", ctx).includes("No goals yet"));

console.log(`test_live_scorers: ${PASS}/${PASS + FAIL} checks passed`);
process.exit(FAIL ? 1 : 0);
