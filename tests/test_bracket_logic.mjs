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
check("M73 is runner-up A v runner-up B", ms[0][0].id === id("AT1") && ms[0][1].id === id("BT1"));
check("M79 is winner A v third H (Annex C, thirds A\u2013H)", ms[6][0].id === id("AT0") && ms[6][1].id === id("HT2"));
check("M84 is winner H v runner-up J", ms[11][0].id === id("HT0") && ms[11][1].id === id("JT1"));
check("M87 is winner K v third D", ms[14][0].id === id("KT0") && ms[14][1].id === id("DT2"));
check("source labels carried", ms[0][0].src === "A2" && ms[6][1].src === "H3" && ms[11][1].src === "J2");
{ // full Annex C sweep: all 495 third-combinations build a legal R32
  let n = 0, ok = true;
  for (let a = 0; a < 9 && ok; a++) for (let b = a + 1; b < 10 && ok; b++)
    for (let c = b + 1; c < 11 && ok; c++) for (let d = c + 1; d < 12 && ok; d++) {
      const ex = [a, b, c, d].map((i) => "ABCDEFGHIJKL"[i]);
      const th = "ABCDEFGHIJKL".split("").filter((g) => !ex.includes(g));
      const m = T.buildR32(go, th); n++;
      if (!m || m.length !== 16) { ok = false; break; }
      if (!m.every((p) => p[0].src[0] !== p[1].src[0])) { ok = false; break; }  // no same-group rematch
      if (new Set(m.flat().map((s) => s.id)).size !== 32) { ok = false; break; }
    }
  check("Annex C sweep: 495 combos, 32 entrants each, never a same-group tie", ok && n === 495);
}

// ---- chainIdx ---------------------------------------------------------------
check("chainIdx identity at R32", T.chainIdx(5, 0) === 5);
check("chainIdx follows official feeds (M77\u2192M89, M73\u2192M90)", T.chainIdx(5, 1) === 1 && T.chainIdx(1, 1) === 2);
check("chainIdx QF crossover (M79/M80 side \u2192 QF M99)", T.chainIdx(7, 2) === 3 && T.chainIdx(8, 2) === 3);
check("1I and 1L sit in opposite halves (meet only in the final)", T.chainIdx(5, 3) !== T.chainIdx(8, 3) && T.chainIdx(5, 4) === T.chainIdx(8, 4));
check("chainIdx reaches the final from anywhere", T.chainIdx(16, 4) === 1);

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
  const a = W(1);   // 2A wins M73 \u2192 R16 berth slot 1; its R16 match is M90 \u2192 QF slot 2
  const out1 = T.pruneAssign({ "R16-1": { team_id: a }, "QF-2": { team_id: a } }, go, thirds);
  check("nested pick survives", out1["QF-2"] && out1["QF-2"].team_id === a);
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
T.onBracketAct({ dataset: { act: "adv", target: "R16-7", team: id("AT0") } });   // 1A wins M79
T.onBracketAct({ dataset: { act: "adv", target: "QF-4", team: id("AT0") } });    // and M92 \u2192 QF slot 4
T.set({ BR: { go: { ...go, A: [id("AT1"), id("AT0"), id("AT2")] }, thirds: thirds.slice() } });
T.propagateBR();
{
  const V = T.get().VALUES;
  // AT0 is now runner-up A \u2192 enters M73 (v runner-up B) \u2192 slot R16-1; winning M90 \u2192 QF-2
  check("position change keeps the pick, reassigned", V["R16-1"] && V["R16-1"].team_id === id("AT0") && !V["R16-7"]);
  check("upstream pick follows too", V["QF-2"] && V["QF-2"].team_id === id("AT0") && !V["QF-4"]);
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
  check("ghost feeders labeled with FIFA numbers", html.includes("M74 winner") && html.includes("M89 winner"));
  check("rows labeled with FIFA match numbers", html.includes("M79") && html.includes("Final \u00b7 M104"));
  const picks = T.collectPicks();
  const struct = picks.filter((p) => p.type === "bracket_struct");
  const slots = picks.filter((p) => p.type === "bracket_slot");
  check("collect emits 13 struct rows", struct.length === 13);
  check("collect emits chosen slot", slots.length === 1 && slots[0].key === "R16-1" && String(slots[0].team_id) === W(1));
  check("struct rows carry text payloads", struct.every((p) => p.player_text && p.bracket_slot));
}
{ // Dark Horse eligibility filter (harness ranks: AT0=#1 ... DT3=#16, ET0=#17)
  const html = T.renderKOContent();
  const dh = html.slice(html.indexOf('data-key="darkhorse"'));
  const sel = dh.slice(0, dh.indexOf("</select>"));
  check("dark horse hides top-16 teams", !sel.includes('value="' + id("AT0") + '"') && !sel.includes('value="' + id("DT3") + '"'));
  check("dark horse lists rank-17+ teams with rank shown", sel.includes('value="' + id("ET0") + '"') && sel.includes("(#17)"));
  check("side-bet team dropdowns stay unfiltered", T.teamOptions(null).includes('value="' + id("AT0") + '"'));
  T.set({ VALUES: { ...T.get().VALUES, darkhorse: { team_id: id("AT0") } } });
  const html2 = T.renderKOContent();
  const dh2 = html2.slice(html2.indexOf('data-key="darkhorse"'));
  const sel2 = dh2.slice(0, dh2.indexOf("</select>"));
  check("saved ineligible dark horse stays visible, flagged", sel2.includes('value="' + id("AT0") + '"') && sel2.includes("INELIGIBLE"));
  T.set({ VALUES: (({ darkhorse, ...rest }) => rest)(T.get().VALUES) });
}
{ // gate when incomplete
  T.set({ BR: { go: { A: go.A }, thirds: [] }, VALUES: {}, META: {} });
  const html = T.renderKOContent();
  check("bracket gated while incomplete", html.includes("1/12 groups ordered"));
}

summary("test_bracket_logic");
