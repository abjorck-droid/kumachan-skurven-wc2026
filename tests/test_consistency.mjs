// Group-pick consistency warnings (advisory): match-outcome picks vs called
// group finishing order. Warn only on mathematical impossibility (points min/max);
// equal points = tiebreaker territory = silent. Added 2026-06-10.
import { loadPage, makeTeams, check, summary } from "./page_harness.mjs";

const { T } = loadPage();
const teams = makeTeams();
const id = (code) => String(teams.find((t) => t.code === code).id);

// Six group-A fixtures: every pairing among AT0..AT3.
const PAIRS = [[0,1],[0,2],[0,3],[1,2],[1,3],[2,3]];
function makeGroupAMatches() {
  return PAIRS.map(([h,a],i)=>({
    fixture_id: 9000+i, round: "Group Stage", group: "A",
    home_id: 100+h, home_code: "AT"+h, away_id: 100+a, away_code: "AT"+a,
  }));
}
// outcomes: map "h-a" -> "Home"|"Draw"|"Away"; omitted = unpicked
function setState(outcomes, order) {
  const VALUES = {};
  Object.entries(outcomes).forEach(([k,oc])=>{
    const [h,a]=k.split("-").map(Number);
    const i=PAIRS.findIndex(p=>p[0]===h&&p[1]===a);
    VALUES["match|"+(9000+i)]={outcome:oc};
  });
  const BR={go:{A:(order||[]).map(c=>id(c))},thirds:[]};
  T.set({ DATA:{teams, matches:makeGroupAMatches()}, VALUES, BR, META:{} });
}

// ---- points ranges ----------------------------------------------------------
setState({ "0-1":"Home", "0-2":"Home", "0-3":"Home", "1-2":"Draw" }, []);
{
  const pts=T.groupPointsRange("A");
  check("all-picked team exact (AT0: 9,9)", pts[id("AT0")].min===9 && pts[id("AT0")].max===9);
  check("partial team ranged (AT1: 1,4)", pts[id("AT1")].min===1 && pts[id("AT1")].max===4);
  check("unpicked counts 0–3 each (AT3 has two blank: 0,6)", pts[id("AT3")].min===0 && pts[id("AT3")].max===6);
}

// ---- no warning cases -------------------------------------------------------
setState({ "0-1":"Home" }, []);                            // order not called yet
check("silent when standings not fully called", T.groupConsistencyWarning("A")===null);

setState({}, ["AT0","AT1","AT2"]);                         // no match picks at all
check("silent with no match picks", T.groupConsistencyWarning("A")===null);

setState({ "0-1":"Home","0-2":"Home","0-3":"Home","1-2":"Home","1-3":"Home","2-3":"Home" },
         ["AT0","AT1","AT2"]);                             // 9/6/3/0 in called order
check("silent when picks support the order", T.groupConsistencyWarning("A")===null);

setState({ "0-1":"Draw","0-2":"Draw","0-3":"Draw","1-2":"Draw","1-3":"Draw","2-3":"Draw" },
         ["AT3","AT2","AT1"]);                             // all level on 3 pts
check("silent on equal points (tiebreaker territory)", T.groupConsistencyWarning("A")===null);

// ---- warning cases ----------------------------------------------------------
// The Norway case: AT2 wins all three but is placed 3rd. 9 pts can't finish 3rd.
setState({ "0-2":"Away","1-2":"Away","2-3":"Home" }, ["AT0","AT1","AT2"]);
{
  const w=T.groupConsistencyWarning("A");
  check("warns: 9-pt team placed 3rd", !!w);
  check("warning names the guaranteed team", w && w.includes("AT2"));
}

// Implicit 4th: AT3 wins everything but isn't in the top three at all.
setState({ "0-3":"Away","1-3":"Away","2-3":"Away" }, ["AT0","AT1","AT2"]);
check("warns when implicit 4th is guaranteed top", !!T.groupConsistencyWarning("A"));

// Partial picks can still be impossible: AT2 guaranteed 9, AT0 capped at 6 — even 2nd is too low.
setState({ "0-2":"Away","1-2":"Away","2-3":"Home" }, ["AT0","AT2","AT1"]);
check("warns on partial picks when 2nd place is already impossible", !!T.groupConsistencyWarning("A"));

// Same picks with AT2 first: nothing impossible remains.
setState({ "0-2":"Away","1-2":"Away","2-3":"Home" }, ["AT2","AT0","AT1"]);
check("silent when order respects partial guarantee", T.groupConsistencyWarning("A")===null);

// But a blank match keeps hope alive: AT2 has 6 guaranteed, AT0 could still reach 6.
setState({ "1-2":"Away","2-3":"Home" }, ["AT0","AT2","AT1"]);
check("silent while a blank pick could rescue the order", T.groupConsistencyWarning("A")===null);

summary("test_consistency");
