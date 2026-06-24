// Mulligan panel render smoke-test (stub DOM, no network).
import { loadPage, makeTeams, check, summary } from "./page_harness.mjs";

const { T } = loadPage();
const teams = makeTeams();                 // ranks 1..48; ET0(#116)=rank17 eligible, AT0(#100)=rank1
const DATA = { teams, mulligansRemaining: 1,
               tokensRemaining: { Double: 2, Triple: 1, AllIn: 0 } };

// Dark Horse = ET0 (eligible), Champion = AT0 — both set so both are mulligan-eligible.
const VALUES = { darkhorse: { team_id: "116" }, "Champion": { team_id: "100" } };
T.set({ DATA, VALUES, LOCKED: true });

// ---- eligibility enumeration ----
const elig = T.mulliganEligible();
check("two eligible picks (Dark Horse + Champion)", elig.length === 2);
check("Dark Horse flagged isDH", elig.some(e => e.key === "darkhorse" && e.isDH));
check("Champion flagged not-DH", elig.some(e => e.key === "Champion" && !e.isDH));

// ---- panel HTML (mulligan available) ----
const h = T.renderMulliganContent();
check("renders the target picker", h.includes('id="mull-target"'));
check("renders replacement + token selects", h.includes('id="mull-replace"') && h.includes('id="mull-token"'));
check("renders preview + confirm buttons", h.includes('id="mull-preview"') && h.includes('id="mull-confirm"'));
check("target options list both picks with current team",
      h.includes("Dark Horse — now ET0") && h.includes("Champion — now AT0"));
check("token dropdown hides the exhausted All-In (0 left)",
      h.includes("Double ×2 (2 left)") && !h.includes("All-In"));
check("explains the 50% + irreversible terms", h.includes("50%") && h.includes("can't be undone"));
check("slotLabel maps Champion + ladder keys",
      T.slotLabel("Champion") === "Champion" && T.slotLabel("R16-3") === "Round-of-16 #3");
check("window state is a valid value",
      ["before","open","after"].includes(T.mullWindowState()));

// ---- window comes from the server (bootstrap), not a UI constant ----
T.set({ DATA: { ...DATA, mulliganWindow: ["2020-01-01","2020-01-02"] }, VALUES, LOCKED: true });
check("server window honored — past window reads 'after'", T.mullWindowState() === "after");
check("mullWindow() returns the server value", T.mullWindow()[0] === "2020-01-01");
T.set({ DATA: { ...DATA, mulliganWindow: ["2099-01-01","2099-01-02"] }, VALUES, LOCKED: true });
check("server window honored — future window reads 'before'", T.mullWindowState() === "before");
check("falls back when bootstrap omits the window",
      (T.set({ DATA: { ...DATA }, VALUES, LOCKED: true }), T.mullWindow()[0] === "2026-06-24"));
T.set({ DATA, VALUES, LOCKED: true });   // restore for the used-state checks below

// ---- used state ----
T.set({ DATA: { ...DATA, mulligansRemaining: 0 },
        VALUES: { ...VALUES, "darkhorse|mull": { team_id: "116" } } });
const used = T.renderMulliganContent();
check("used state shows the 'already used' record", used.includes("has been used") &&
      used.includes("Dark Horse → ET0"));
check("used state hides the form", !used.includes('id="mull-target"'));

summary("test_mulligan_ui");
