#!/usr/bin/env python3
"""resolve_sidegames player tallies — Footballers goals/assists fill (no network).

Covers the event-derived Top Scorers board: the counting rules (shared with the
Top Scorer / Golden Boot side games) and footballer_stat_updates(), which writes
only the Footballers rows whose stored tally changed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import resolve_sidegames as rs

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

# ---- counting rules (the board must match how side games resolve) -----------
def ev(t, detail="", comments=""):
    return {"type": t, "detail": detail, "comments": comments}

check("normal goal counts", rs.is_counting_goal(ev("Goal", "Normal Goal")) is True)
check("penalty goal counts", rs.is_counting_goal(ev("Goal", "Penalty")) is True)
check("own goal excluded", rs.is_counting_goal(ev("Goal", "Own Goal")) is False)
check("missed penalty excluded", rs.is_counting_goal(ev("Goal", "Missed Penalty")) is False)
check("shootout kick excluded", rs.is_counting_goal(ev("Goal", "Penalty", "Penalty Shootout")) is False)
check("card is not a goal", rs.is_counting_goal(ev("Card", "Red Card")) is False)

# ---- footballer_stat_updates: only changed rows, skip squad-import gaps ------
foot_rec = {
    10: {"id": "recA", "goals": 0, "assists": 0},   # newly scored → change
    11: {"id": "recB", "goals": 2, "assists": 1},   # unchanged → skip
    12: {"id": "recC", "goals": 1, "assists": 0},   # assist added → change
    13: {"id": "recD", "goals": 0, "assists": 0},   # assist-only player → change
}
goals = {10: 1, 11: 2, 12: 1, 99: 3}                # 99 not in Footballers → skip
assists = {10: 0, 11: 1, 12: 2, 13: 1}

ups = rs.footballer_stat_updates(goals, assists, foot_rec)
by_id = {u["id"]: u["fields"] for u in ups}
check("changed scorer written", by_id.get("recA") == {"goals_in_tournament": 1, "assists_in_tournament": 0})
check("unchanged row skipped", "recB" not in by_id)
check("assist added → written", by_id.get("recC") == {"goals_in_tournament": 1, "assists_in_tournament": 2})
check("assist-only player written", by_id.get("recD") == {"goals_in_tournament": 0, "assists_in_tournament": 1})
check("scorer missing from squads skipped", all(u["id"] != "rec99" for u in ups))
check("only the three changed rows written", len(ups) == 3)
check("empty tally → no writes", rs.footballer_stat_updates({}, {}, foot_rec) == [])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
