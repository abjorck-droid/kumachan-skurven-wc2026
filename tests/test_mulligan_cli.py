#!/usr/bin/env python3
"""mulligan.py CLI helpers — team resolution + eligible-pick listing (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pickentry_server as ps
import mulligan as cli

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

# ---- stub Airtable ----------------------------------------------------------
TEAMS = [
    {"id": "recT900", "fields": {"team_id": 900, "code": "NOR", "fifa_ranking": 40}},
    {"id": "recT910", "fields": {"team_id": 910, "code": "USA", "fifa_ranking": 17}},
    {"id": "recT100", "fields": {"team_id": 100, "code": "BRA", "fifa_ranking": 1}},
]
PREDS = [
    {"id": "recDH", "fields": {"label": "Cal|darkhorse", "prediction_type": "dark_horse",
                               "predicted_team": ["recT900"]}},
    {"id": "recCh", "fields": {"label": "Cal|Champion", "prediction_type": "bracket_slot",
                               "predicted_team": ["recT100"]}},
    {"id": "recMull", "fields": {"label": "Cal|darkhorse|mull", "prediction_type": "dark_horse",
                                 "predicted_team": ["recT910"]}},   # prior replacement — must be excluded
    {"id": "recBoot", "fields": {"label": "Cal|side|Golden Boot", "prediction_type": "side_game"}},
    {"id": "recAnd", "fields": {"label": "Andreas|darkhorse", "prediction_type": "dark_horse",
                                "predicted_team": ["recT900"]}},   # other player — excluded
]
def _at_list(table, fields=None):
    return TEAMS if table == "Teams" else (PREDS if table == "Predictions" else [])
ps.at_list = _at_list

# ---- resolve_team -----------------------------------------------------------
check("code → team_id (case-insensitive)", cli.resolve_team("usa") == 910)
check("numeric id passes through", cli.resolve_team("900") == 900)
try:
    cli.resolve_team("ZZZ"); check("unknown code raises", False)
except SystemExit:
    check("unknown code raises", True)

# ---- list_eligible ----------------------------------------------------------
rows = cli.list_eligible("Cal")
keys = [r["key"] for r in rows]
check("lists darkhorse + Champion only", set(keys) == {"darkhorse", "Champion"})
check("Dark Horse sorts first", keys[0] == "darkhorse")
check("excludes |mull replacement rows", "darkhorse|mull" not in keys)
check("excludes side games", "side|Golden Boot" not in keys)
check("excludes the other player's picks", all(not k.startswith("Andreas") for k in keys))
check("resolves current team codes", next(r for r in rows if r["key"] == "darkhorse")["code"] == "NOR")

print(f"\ntest_mulligan_cli: {PASS}/{PASS+FAIL} checks passed")
sys.exit(1 if FAIL else 0)
