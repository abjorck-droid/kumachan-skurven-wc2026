#!/usr/bin/env python3
"""pickentry_server bracket_guard + save full-replace parity tests (no network)."""
import sys
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
        fn()
        check(label, False)
    except RuntimeError as e:
        check(label, frag in str(e))

# ---- fixtures (mirror the JS harness) ----------------------------------------
GROUPS = "ABCDEFGHIJKL"
TEAMS = []
for gi, g in enumerate(GROUPS):
    for i in range(4):
        TEAMS.append({"team_id": 100 + gi * 4 + i, "code": f"{g}T{i}", "group": g})
BY_CODE = {t["code"]: {"team_id": t["team_id"], "group": t["group"]} for t in TEAMS}
GO = {g: [str(BY_CODE[f"{g}T{i}"]["team_id"]) for i in range(3)] for g in GROUPS}

def struct_picks(**over):
    ps_ = [{"key": f"group_order|{g}", "type": "bracket_struct", "bracket_slot": f"group_order|{g}",
            "player_text": over.get(f"group_order_{g}", f"{g}T0,{g}T1,{g}T2")} for g in GROUPS]
    ps_.append({"key": "thirds_advance", "type": "bracket_struct", "bracket_slot": "thirds_advance",
                "player_text": over.get("thirds", "A,B,C,D,E,F,G,H")})
    return ps_

def entrants_of(k):
    ts = sorted("ABCDEFGH")
    if k <= 8: return [GO["ABCDEFGH"[k - 1]][0], GO[ts[k - 1]][2]]
    if k <= 12: return [GO["IJKL"[k - 9]][0], GO["ABCD"[k - 9]][1]]
    pairs = [("E", "F"), ("G", "H"), ("I", "J"), ("K", "L")]
    a, b = pairs[k - 13]
    return [GO[a][1], GO[b][1]]

def full_picks():
    picks = struct_picks()
    r16 = [entrants_of(k)[0] for k in range(1, 17)]
    for i, t in enumerate(r16):
        picks.append({"key": f"R16-{i+1}", "type": "bracket_slot", "bracket_slot": f"R16-{i+1}", "team_id": t})
    qf = r16[::2]; sf = qf[::2]; fi = sf[::2]
    for i, t in enumerate(qf): picks.append({"key": f"QF-{i+1}", "type": "bracket_slot", "bracket_slot": f"QF-{i+1}", "team_id": t})
    for i, t in enumerate(sf): picks.append({"key": f"SF-{i+1}", "type": "bracket_slot", "bracket_slot": f"SF-{i+1}", "team_id": t})
    for i, t in enumerate(fi): picks.append({"key": f"F-{i+1}", "type": "bracket_slot", "bracket_slot": f"F-{i+1}", "team_id": t})
    picks.append({"key": "Champion", "type": "bracket_slot", "bracket_slot": "Champion", "team_id": fi[0], "token": "AllIn"})
    return picks

# ---- bracket_guard -------------------------------------------------------------
ps.bracket_guard(full_picks(), BY_CODE); check("valid full payload passes", True)
ps.bracket_guard([], BY_CODE); check("empty payload passes", True)
ps.bracket_guard(struct_picks()[:4], BY_CODE); check("partial structure passes", True)

bad = full_picks(); bad[14]["team_id"] = bad[13]["team_id"]  # two R16 rows same team
raises("duplicate in round rejected", lambda: ps.bracket_guard(bad, BY_CODE), "duplicate")

bad = [{"key": "Champion", "type": "bracket_slot", "bracket_slot": "Champion", "team_id": GO["A"][0]}]
raises("non-nested champion rejected", lambda: ps.bracket_guard(bad, BY_CODE), "nested")

bad = full_picks()
a, b = entrants_of(1)
nxt = [p for p in bad if p["key"] == "R16-2"][0]; nxt["team_id"] = b
raises("same-path hedge rejected", lambda: ps.bracket_guard(bad, BY_CODE), "same bracket path")

bad = full_picks()
[p for p in bad if p["key"] == "R16-16"][0]["team_id"] = str(BY_CODE["AT3"]["team_id"])
raises("non-qualifier rejected", lambda: ps.bracket_guard(bad, BY_CODE), "32 qualifiers")

raises("wrong-group code rejected",
       lambda: ps.bracket_guard(struct_picks(group_order_B="AT0,BT1,BT2"), BY_CODE), "not in group B")
raises("duplicate thirds rejected",
       lambda: ps.bracket_guard(struct_picks(thirds="A,A,B"), BY_CODE), "thirds_advance")
raises("nine thirds rejected",
       lambda: ps.bracket_guard(struct_picks(thirds="A,B,C,D,E,F,G,H,I"), BY_CODE), "thirds_advance")
raises("unknown slot key rejected",
       lambda: ps.bracket_guard([{"key": "R64-1", "type": "bracket_slot", "bracket_slot": "R64-1", "team_id": "100"}], BY_CODE),
       "unknown bracket slot")
raises("unknown struct key rejected",
       lambda: ps.bracket_guard([{"key": "group_order|Z", "type": "bracket_struct", "bracket_slot": "group_order|Z"}], BY_CODE),
       "unknown bracket_struct")

# ---- save() full-replace with stubbed Airtable -----------------------------------
class Store:
    def __init__(self):
        self.predictions = [
            {"id": "recOLD", "fields": {"label": "Andreas|R32-1", "prediction_type": "bracket_slot"}},
            {"id": "recSIDE", "fields": {"label": "Andreas|side|Golden Boot", "prediction_type": "side_game"}},
            {"id": "recCAL", "fields": {"label": "Cal|R16-1", "prediction_type": "bracket_slot"}},
        ]
        self.deleted, self.upserted, self.patched = [], [], []

S = Store()
ps.get_player = lambda name: {"id": "recPLAYER", "fields": {"name": name}}
def _at_list(table, fields=None):
    if table == "Teams":
        return [{"id": "recT%d" % t["team_id"], "fields": t} for t in TEAMS]
    if table == "Predictions":
        return S.predictions
    return []
ps.at_list = _at_list
def _at_upsert(table, records, merge_on):
    S.upserted.extend(records); return len(records)
ps.at_upsert = _at_upsert
def _at_delete(table, ids):
    S.deleted.extend(ids)
    S.predictions = [r for r in S.predictions if r["id"] not in ids]
    return len(ids)
ps.at_delete = _at_delete
ps.at = lambda method, path, body=None: S.patched.append((method, path, body))

res = ps.save("Andreas", full_picks())
check("save upserts 44 rows", res["saved"] == 44)
check("stale bracket row deleted", S.deleted == ["recOLD"])
check("side pick + opponent rows survive",
      any(r["id"] == "recSIDE" for r in S.predictions) and any(r["id"] == "recCAL" for r in S.predictions))
check("token reserves patched", S.patched and S.patched[-1][2]["records"][0]["fields"]["tokens_remaining_allin"] == 0)
check("deleted count returned", res["deleted"] == 1)

S = Store()
res = ps.save("Andreas", [])
check("empty save wipes player's bracket rows only", S.deleted == ["recOLD"] and res["saved"] == 0)

bad = full_picks(); bad[14]["team_id"] = bad[13]["team_id"]
S = Store()
try:
    ps.save("Andreas", bad); check("invalid save rejected before writes", False)
except RuntimeError:
    check("invalid save rejected before writes", not S.upserted and not S.deleted and not S.patched)

print(f"test_pickentry_guard: {PASS}/{PASS+FAIL} checks passed")
sys.exit(1 if FAIL else 0)
