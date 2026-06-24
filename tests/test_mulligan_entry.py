#!/usr/bin/env python3
"""pickentry_server mulligan_guard + save_mulligan tests (no network).

Covers the v1.1 mulligan entry path: window/budget gating, Dark Horse eligibility
(11 June 2026 edition — USA legal, Uruguay not), no-op + wrong-type rejection, token
budget, bracket re-validation via the reused bracket_guard, and a stubbed save_mulligan
that must create a SIBLING replacement row, log a Mulligans link, spend the mulligan,
and write nothing when validation fails.
"""
import sys, datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pickentry_server as ps

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

def raises(label, fn, frag):
    try:
        fn(); check(label, False)
    except RuntimeError as e:
        check(label, frag in str(e))

# ---- fixtures ----------------------------------------------------------------
OPEN = dt.datetime(2026, 6, 27, 12, 0)     # inside MULLIGAN_WINDOW (26–28)
CLOSED = dt.datetime(2026, 6, 20, 12, 0)   # before it

# Teams with rankings: NOR original DH (rank 40), USA eligible (17), URU ineligible (16),
# plus a few bracket teams. teams_by_id / teams_by_code as the guard expects.
TEAMS = {
    900: {"team_id": 900, "code": "NOR", "group": "F", "fifa_ranking": 40},
    910: {"team_id": 910, "code": "USA", "group": "D", "fifa_ranking": 17},
    920: {"team_id": 920, "code": "URU", "group": "E", "fifa_ranking": 16},
    100: {"team_id": 100, "code": "AT0", "group": "A", "fifa_ranking": 3},
    101: {"team_id": 101, "code": "AT1", "group": "A", "fifa_ranking": 22},
    102: {"team_id": 102, "code": "BT0", "group": "B", "fifa_ranking": 9},
}
BY_ID = TEAMS
BY_CODE = {t["code"]: t for t in TEAMS.values()}

DH = {"key": "darkhorse", "type": "dark_horse", "side_game": "Dark Horse", "team_id": 900}

def dh_guard(repl, picks=None, mull=1, toks=None, now=OPEN):
    return ps.mulligan_guard("darkhorse", repl, picks or [DH], BY_CODE, BY_ID, mull, toks, now=now)

# ---- mulligan_guard: window + budget ----------------------------------------
raises("closed window rejected", lambda: dh_guard({"team_id": 910}, now=CLOSED), "window is not open")
raises("spent mulligan rejected", lambda: dh_guard({"team_id": 910}, mull=0), "already used")

# ---- mulligan_guard: Dark Horse eligibility ---------------------------------
dh_guard({"team_id": 910}); check("USA (rank 17) is a legal Dark Horse replacement", True)
raises("Uruguay (rank 16) rejected", lambda: dh_guard({"team_id": 920}), "not Dark-Horse-eligible")
raises("no-op re-pick (same team) rejected", lambda: dh_guard({"team_id": 900}), "identical")
raises("replacement without a team rejected", lambda: dh_guard({"team_id": None}), "needs a team")

# ---- mulligan_guard: target validity ----------------------------------------
SIDE = {"key": "side|Golden Boot", "type": "side_game", "team_id": None}
raises("non-eligible target type rejected",
       lambda: ps.mulligan_guard("side|Golden Boot", {"team_id": 910}, [SIDE], BY_CODE, BY_ID, 1, now=OPEN),
       "not a mulligan-eligible pick")
raises("unknown target key rejected",
       lambda: ps.mulligan_guard("R16-9", {"team_id": 910}, [DH], BY_CODE, BY_ID, 1, now=OPEN),
       "not found")

# ---- mulligan_guard: token budget on the replacement ------------------------
dh_guard({"team_id": 910, "token": "Double"}, toks={"Double": 1}); check("token available passes", True)
raises("token exhausted rejected",
       lambda: dh_guard({"team_id": 910, "token": "AllIn"}, toks={"AllIn": 0}), "no AllIn tokens remaining")

# ---- mulligan_guard: bracket-slot swap re-validates via bracket_guard --------
# Minimal bracket set (set-level dedupe fires without full structure).
BRK = [{"key": "R16-1", "type": "bracket_slot", "bracket_slot": "R16-1", "team_id": 100},
       {"key": "R16-2", "type": "bracket_slot", "bracket_slot": "R16-2", "team_id": 101}]
ps.mulligan_guard("R16-2", {"team_id": 102}, BRK, BY_CODE, BY_ID, 1, now=OPEN)
check("valid bracket-slot swap passes", True)
raises("bracket swap creating a duplicate rejected",
       lambda: ps.mulligan_guard("R16-2", {"team_id": 100}, BRK, BY_CODE, BY_ID, 1, now=OPEN), "duplicate")

# ---- save_mulligan with stubbed Airtable ------------------------------------
class Store:
    def __init__(self):
        self.predictions = [
            {"id": "recDH", "fields": {"label": "Cal|darkhorse", "prediction_type": "dark_horse",
                                       "predicted_team": ["recT900"], "side_game": ["recSGDH"]}},
            {"id": "recBOOT", "fields": {"label": "Cal|side|Golden Boot", "prediction_type": "side_game"}},
        ]
        self.upserted, self.posted, self.patched = [], [], []

def wire(store, player_fields):
    ps.get_player = lambda name: {"id": "recCAL", "fields": player_fields}
    def _at_list(table, fields=None):
        if table == "Teams":
            return [{"id": "recT%d" % t["team_id"], "fields": t} for t in TEAMS.values()]
        if table == "Predictions":
            return store.predictions
        if table == "SideGames":
            return [{"id": "recSGDH", "fields": {"name": "Dark Horse"}}]
        if table == "Mulligans":
            return []
        return []
    ps.at_list = _at_list
    def _at_upsert(table, records, merge_on):
        store.upserted.extend(records)
        # mimic the row becoming queryable so save_mulligan can find its rec id
        for rc in records:
            store.predictions.append({"id": "recNEW", "fields": dict(rc)})
        return len(records)
    ps.at_upsert = _at_upsert
    def _at(method, path, body=None):
        (store.posted if method == "POST" else store.patched).append((method, path, body))
    ps.at = _at

PLAYER = {"name": "Cal", "mulligans_remaining": 1,
          "tokens_remaining_double": 2, "tokens_remaining_triple": 2, "tokens_remaining_allin": 1}

# rec2tid: recT900 -> 900 so the original DH team resolves
S = Store()
wire(S, PLAYER)
res = ps.save_mulligan("Cal", "darkhorse", {"team_id": 910}, note="USA looked strong", now=OPEN)
check("replacement upserted as a sibling label", any(
    r.get("label") == "Cal|darkhorse|mull" for r in S.upserted))
check("replacement keeps dark_horse type + new team", any(
    r.get("prediction_type") == "dark_horse" and r.get("predicted_team") == ["recT910"] for r in S.upserted))
check("Mulligans row links original→replacement", bool(S.posted) and
      S.posted[-1][2]["records"][0]["fields"]["original_prediction"] == ["recDH"] and
      S.posted[-1][2]["records"][0]["fields"]["new_prediction"] == ["recNEW"])
check("mulligan spent (remaining→0)", bool(S.patched) and
      S.patched[-1][2]["records"][0]["fields"]["mulligans_remaining"] == 0)
check("result reports the new label", res["new_label"] == "Cal|darkhorse|mull")

# reject-before-writes: closed window must not touch Airtable
S = Store(); wire(S, PLAYER)
try:
    ps.save_mulligan("Cal", "darkhorse", {"team_id": 910}, now=CLOSED)
    check("closed-window save rejected before writes", False)
except RuntimeError:
    check("closed-window save rejected before writes",
          not S.upserted and not S.posted and not S.patched)

# reject-before-writes: ineligible Dark Horse (Uruguay) writes nothing
S = Store(); wire(S, PLAYER)
try:
    ps.save_mulligan("Cal", "darkhorse", {"team_id": 920}, now=OPEN)
    check("ineligible-replacement save rejected before writes", False)
except RuntimeError:
    check("ineligible-replacement save rejected before writes",
          not S.upserted and not S.posted and not S.patched)

# dry_run: validates + plans, but commits NOTHING
S = Store(); wire(S, PLAYER)
res = ps.save_mulligan("Cal", "darkhorse", {"team_id": 910}, now=OPEN, dry_run=True)
check("dry_run writes nothing", not S.upserted and not S.posted and not S.patched)
check("dry_run flags itself + uncommitted", res.get("dryRun") and res.get("committed") is False)
check("dry_run leaves the mulligan unspent", res["mulligans_remaining"] == 1)
check("dry_run plan shows the replacement label + new team", bool(res.get("wouldWrite")) and
      res["wouldWrite"]["replacement"]["label"] == "Cal|darkhorse|mull" and
      res["wouldWrite"]["replacement"]["predicted_team"] == ["recT910"])
check("dry_run plan shows the budget patch (mulligan→0)",
      res["wouldWrite"]["budget_patch"]["mulligans_remaining"] == 0)
# dry_run still enforces validation (ineligible Uruguay raises, writes nothing)
S = Store(); wire(S, PLAYER)
raises("dry_run still rejects ineligible replacement",
       lambda: ps.save_mulligan("Cal", "darkhorse", {"team_id": 920}, now=OPEN, dry_run=True),
       "not Dark-Horse-eligible")
check("dry_run rejection wrote nothing", not S.upserted and not S.posted and not S.patched)

print(f"\ntest_mulligan_entry: {PASS}/{PASS+FAIL} checks passed")
sys.exit(1 if FAIL else 0)
