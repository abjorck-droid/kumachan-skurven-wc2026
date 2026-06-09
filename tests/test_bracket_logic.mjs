// Propagated-bracket pure logic + UI flow tests (stub DOM).
import { loadPage, makeTeams, makeStructure, check, summary } from "./page_harness.mjs";

const { T, els } = loadPage();
const teams = makeTeams();
const { go, thirds } = makeStructure(teams);
const id = (code) => String(teams.find((t) => t.code === code).id);

// ---- buildR32 ---------------------------------------------------------------
check("buildR32 null when groups incomplete", T.buildR32({}, thirds) === null);
check("buildR32 null when thirds short", T.buildR32(go, ["A", "B"]) === null);
const ms = T.buildR32(go, thirds);
check("buildR32 yields 16 matches", ms && ms.length === 16);
const entrants = ms.flat().map((s) => s.id);
check("32 unique entrants", new Set(entrants).size === 32);
check("match 1 is winner A v third A (sorted letters)", ms[0][0].id === id("AT0") && ms[0][1].id === id("AT2"));
check("match 9 is winner I v runner-up A", ms[8][0].id === id("IT0") && ms[8][1].id === id("AT1"));
check("match 13 pairs runners-up E and F", ms[12][0].id === id("ET1") && ms[12][1].id === id("FT1"));
check("source labels carried", ms[0][0].src === "A1" && ms[0][1].src === "A3" && ms[8][1].src === "A2");

// ---- chainIdx ---------------------------------------------------------------
check("chainIdx identity at R32→R16", T.chainIdx(5, 0) === 5);
check("chainIdx halves per round", T.chainIdx(5, 1) === 3 && T.chainIdx(16, 4) === 1);

// ---- pruneAssign ------------------------------------------------------------
// helper: winner-of-match-k entrant (home side)
const W = (k) => ms[k - 1][0].id;
{ // pick survives, token rides
  const out = T.pruneAssign({ "R16-3": { team_id: W(3), token: "Triple", note: "hi" } }, go, thirds);
  check("pick kept in place", out["R16-3"] && out["R16-3"].team_id === W(3));
  check("token and note ride", out["R16-3"].token === "Triple" && out["R16-3"].note === "hi");
}
{ // position move: same team saved under a stale slot key gets reassigned by identity
  const out = T.pruneAssign({ "R16-9": { team_id: W(3), token: "Double" } }, go, thirds);
  check("team moves to its real slot", out["R16-3"] && out["R16-3"].team_id === W(3) && !out["R16-9"]);
  check("token follows the team", out["R16-3"].token === "Double");
}
{ // drop-out: a non-entrant disappears, upstream picks of it too
  const ghost = String(teams.find((t) => t.code === "AT3").id); // 4th of group A — never advances
  const out = T.pruneAssign({ "R16-1": { team_id: ghost }, "QF-1": { team_id: ghost } }, go, thirds);
  check("dropped team cleared everywhere", !out["R16-1"] && !out["QF-1"]);
}
{ // collision: two teams now in the same R32 match both claiming R16 → both void
  const a = ms[0][0].id, b = ms[0][1].id;
  const out = T.pruneAssign({ "R16-1": { team_id: a }, "R16-2": { team_id: b } }, go, thirds);
  check("colliding picks both voided", !out["R16-1"] && !out["R16-2"]);
}
{ // nesting cascade: QF pick valid only if team kept in R16
  const a = W(1);
  const out1 = T.pruneAssign({ "R16-1": { team_id: a }, "QF-1": { team_id: a } }, go, thirds);
  check("nested pick survives", out1["QF-1"] && out1["QF-1"].team_id === a);
  const out2 = T.pruneAssign({ "QF-1": { team_id: a } }, go, thirds);
  check("orphan QF pick (team not in R16) cleared", !out2["QF-1"]);
}
{ // full chain to champion
  const a = W(1);
  const vals = { "R16-1": { team_id: a }, "QF-1": { team_id: a }, "SF-1": { team_id: a },
    "F-1": { team_id: a }, "Champion": { team_id: a, token: "AllIn" } };
  const out = T.pruneAssign(vals, go, thirds);
  check("champion chain intact", out["Champion"] && out["Champion"].team_id === a && out["Champion"].token === "AllIn");
}

// ---- UI flow through __T ------------------------------------------------------
T.set({ DATA: { teams }, VALUES: {}, BR: { go: {}, thirds: [] }, META: {}, LOCKED: false });
"ABCDEFGHIJKL".split("").forEach((g) => { T.get().BR.go[g] = go[g].slice(); });
T.get().BR.thirds = thirds.slice();
T.propagateBR();
{
  const V = T.get().VALUES;
  check("struct rows written on propagate", V["group_order|A"] && V["group_order|A"].player_text === "AT0,AT1,AT2");
  check("thirds row written sorted", V["thirds_advance"].player_text === "A,B,C,D,E,F,G,H");
}
// simulate advancing a team via the click handler
T.onBracketAct({ dataset: { act: "adv", target: "R16-1", team: W(1) } });
check("adv click stores slot", T.get().VALUES["R16-1"].team_id === W(1));
T.onBracketAct({ dataset: { act: "adv", target: "R16-1", team: W(1) } });
check("second click deselects", !T.get().VALUES["R16-1"]);
// reorder group A (swap 1st/2nd) and confirm surgical cascade
T.onBracketAct({ dataset: { act: "adv", target: "R16-1", team: id("AT0") } });
T.onBracketAct({ dataset: { act: "adv", target: "QF-1", team: id("AT0") } });
T.set({ BR: { go: { ...go, A: [id("AT1"), id("AT0"), id("AT2")] }, thirds: thirds.slice() } });
T.propagateBR();
{
  const V = T.get().VALUES;
  // AT0 is now runner-up A → enters R32 match 9 (v winner I) → slot R16-9, QF-5
  check("position change keeps the pick, reassigned", V["R16-9"] && V["R16-9"].team_id === id("AT0") && !V["R16-1"]);
  check("upstream pick follows too", V["QF-5"] && V["QF-5"].team_id === id("AT0") && !V["QF-1"]);
  check("struct row reflects new order", V["group_order|A"].player_text === "AT1,AT0,AT2");
}
// rank tap mechanics
T.set({ BR: { go: { A: [] }, thirds: [] }, VALUES: {} });
T.onBracketAct({ dataset: { act: "rank", group: "A", team: id("AT2") } });
T.onBracketAct({ dataset: { act: "rank", group: "A", team: id("AT0") } });
T.onBracketAct({ dataset: { act: "rank", group: "A", team: id("AT1") } });
check("taps rank in order", T.get().BR.go.A.join() === [id("AT2"), id("AT0"), id("AT1")].join());
T.onBracketAct({ dataset: { act: "rank", group: "A", team: id("AT0") } });
check("tapping a ranked team truncates from there", T.get().BR.go.A.join() === id("AT2"));
// thirds cap
T.set({ BR: { go, thirds: "ABCDEFGH".split("") } });
T.onBracketAct({ dataset: { act: "third", letter: "I" } });
check("ninth third refused", T.get().BR.thirds.length === 8 && !T.get().BR.thirds.includes("I"));
check("refusal flashes a warning", els["#status"].textContent.includes("Eight thirds max"));

// ---- load round-trip + legacy wipe -------------------------------------------
{
  const champ = W(1);
  T.set({ DATA: { teams }, BR: { go: {}, thirds: [] }, VALUES: {
    "group_order|A": { player_text: "AT0,AT1,AT2" },
    "thirds_advance": { player_text: "A,B,C,D,E,F,G,H" },
    "R16-1": { team_id: champ, token: "Double" },
  } });
  "BCDEFGHIJKL".split("").forEach((g) => { T.get().VALUES["group_order|" + g] = { player_text: `${g}T0,${g}T1,${g}T2` }; });
  T.loadStructFromValues();
  check("round-trip restores group orders", T.get().BR.go.A.join() === go.A.join() && T.get().BR.go.L.join() === go.L.join());
  check("round-trip restores thirds", T.get().BR.thirds.join() === "ABCDEFGH".split("").join());
  check("slot pick survives load with token", T.get().VALUES["R16-1"].team_id === champ && T.get().VALUES["R16-1"].token === "Double");
}
{ // legacy free-form picks without structure → clean slate
  T.set({ DATA: { teams }, BR: { go: {}, thirds: [] }, VALUES: {
    "Champion": { team_id: id("AT0"), token: "AllIn" }, "R16-4": { team_id: id("BT0") },
  } });
  T.loadStructFromValues();
  check("legacy slots wiped when no structure", !T.get().VALUES["Champion"] && !T.get().VALUES["R16-4"]);
}

// ---- render + collect ----------------------------------------------------------
T.set({ DATA: { teams }, BR: { go, thirds: thirds.slice() }, VALUES: {}, META: {} });
T.propagateBR();
T.onBracketAct({ dataset: { act: "adv", target: "R16-1", team: W(1) } });
{
  const html = T.renderKOContent();
  check("render shows group cards", html.includes("Group finishes") && html.includes("Group L"));
  check("render shows thirds pool", html.includes("Best thirds") && html.includes("data-act=\"third\""));
  check("render shows bracket rounds", html.includes("Round of 32") && html.includes("Final"));
  check("chosen chip marked", html.includes("bchip on") || /class="bchip on"/.test(html));
  check("ghost feeders labeled", html.includes("M1 winner") || html.includes("R32 M1 winner"));
  const picks = T.collectPicks();
  const struct = picks.filter((p) => p.type === "bracket_struct");
  const slots = picks.filter((p) => p.type === "bracket_slot");
  check("collect emits 13 struct rows", struct.length === 13);
  check("collect emits chosen slot", slots.length === 1 && slots[0].key === "R16-1" && String(slots[0].team_id) === W(1));
  check("struct rows carry text payloads", struct.every((p) => p.player_text && p.bracket_slot));
}
{ // gate when incomplete
  T.set({ BR: { go: { A: go.A }, thirds: [] }, VALUES: {}, META: {} });
  const html = T.renderKOContent();
  check("bracket gated while incomplete", html.includes("1/12 groups ordered"));
}

summary("test_bracket_logic");
