#!/usr/bin/env python3
"""poller standings transforms — group normalization + label stability (no network).

Regression for 2026-06-12: API-Football renamed standings groups when play
started ("Group A" → "Group Stage - A"), orphaning every label-keyed row and
duplicating all tables on the live board.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import poller as po

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

# ---- norm_group --------------------------------------------------------------
check("pre-tournament naming", po.norm_group("Group A") == "A")
check("matchday naming", po.norm_group("Group Stage - A") == "A")
check("matchday naming (actual 2026-06-12 feed)", po.norm_group("Group Stage - Group A") == "A")
check("last group letter", po.norm_group("Group Stage - L") == "L")
check("thirds ranking → 3rd", po.norm_group("Ranking of third-placed teams") == "3rd")
check("aggregate table skipped", po.norm_group("Group Stage") is None)
check("empty/None skipped", po.norm_group(None) is None and po.norm_group("") is None)
check("letter must be its own token", po.norm_group("USA") is None)
check("letters beyond L skipped", po.norm_group("Group M") is None)
check("whitespace tolerated", po.norm_group("  Group Stage - C  ") == "C")

# ---- to_standing_fields ------------------------------------------------------
ROW = {"team": {"id": 25}, "rank": 1, "goalsDiff": 2, "points": 3, "form": "W",
       "all": {"played": 1, "win": 1, "draw": 0, "lose": 0,
               "goals": {"for": 3, "against": 1}}}
TEAM_MAP = {25: "recTEAM25"}

f = po.to_standing_fields(ROW, "A", TEAM_MAP)
check("label is normalized-key:team_id", f["label"] == "A:25")
check("group field is the normalized key", f["group"] == "A")
check("team link resolved", f["team"] == ["recTEAM25"])
check("stats mapped", f["played"] == 1 and f["win"] == 1 and f["goal_diff"] == 2 and f["points"] == 3)

# label must be identical whichever API naming era produced the row
fa = po.to_standing_fields(ROW, po.norm_group("Group A"), TEAM_MAP)
fb = po.to_standing_fields(ROW, po.norm_group("Group Stage - A"), TEAM_MAP)
check("label stable across API renames", fa["label"] == fb["label"] == "A:25")

f3 = po.to_standing_fields(ROW, po.norm_group("Ranking of third-placed teams"), TEAM_MAP)
check("thirds label keyed on 3rd", f3["label"] == "3rd:25" and f3["group"] == "3rd")

f_unmapped = po.to_standing_fields(ROW, "A", {})
check("unknown team omits link", "team" not in f_unmapped)

print(f"test_poller_standings: {PASS}/{PASS+FAIL} checks passed")
sys.exit(1 if FAIL else 0)
