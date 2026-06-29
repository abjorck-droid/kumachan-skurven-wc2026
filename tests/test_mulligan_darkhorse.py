#!/usr/bin/env python3
"""Mulligan × Dark Horse — the v1.1 path that lets a mulligan re-pick the Dark Horse
(no network). Guards two properties the spec change relies on:

  1. mulligan_affected() is type-agnostic — a dark_horse Prediction linked in the
     Mulligans table is picked up exactly like a bracket_slot pick. (This is what
     made "no engine change" true: Dark Horse already rides the standard path.)
  2. finalize_points() applies the 50% factor AFTER the confidence token, on a
     dark_horse ladder payout, with the engine's int(round()) rounding.

Regression intent: if someone later special-cases the mulligan loop by prediction_type
and forgets dark_horse, property 1 fails; if the token/halve order is swapped, the
All-In assertions fail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scoring_engine as se

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

# ---- fixtures ----------------------------------------------------------------
# Airtable-shaped Mulligans rows. Cal mulligans his Dark Horse: original DH pick
# rec "recDH_OLD" -> replacement dark_horse rec "recDH_NEW". (A bracket-slot
# mulligan is included too, to prove both kinds land in the same set.)
MULLS = [
    {"id": "recMull1", "fields": {
        "original_prediction": ["recDH_OLD"], "new_prediction": ["recDH_NEW"]}},
    {"id": "recMull2", "fields": {
        "original_prediction": ["recSLOT_OLD"], "new_prediction": ["recSLOT_NEW"]}},
]

# Teams-reached map for dark_horse_payout: pretend Cal's NEW Dark Horse reached the SF.
TIERS_SF = {"R16": {77}, "QF": {77}, "SF": {77}}      # team_id 77 climbed to SF
TIERS_CHAMP = {"R16": {77}, "QF": {77}, "SF": {77}, "Final": {77}}
CHAMP = 77

# ---- property 1: type-agnostic affected-set ---------------------------------
affected = se.mulligan_affected(MULLS)
check("dark_horse original pick is in mull_affected", "recDH_OLD" in affected)
check("dark_horse replacement pick is in mull_affected", "recDH_NEW" in affected)
check("bracket_slot picks still covered", {"recSLOT_OLD", "recSLOT_NEW"} <= affected)
check("exactly the four linked records, no extras", affected ==
      {"recDH_OLD", "recDH_NEW", "recSLOT_OLD", "recSLOT_NEW"})
check("empty mulligans -> empty set", se.mulligan_affected([]) == set())
check("null link field tolerated", se.mulligan_affected(
    [{"id": "x", "fields": {"original_prediction": None}}]) == set())

# ---- property 2: dark_horse payout, halved, token-first ----------------------
# Cal's replacement DH reached the SF: ladder = 200. No token. Mulligan halves it.
sf_base = se.dark_horse_payout(77, TIERS_SF, None)
check("dark_horse SF ladder = 200", sf_base == 200)
check("mulliganed SF, no token = 100", se.finalize_points(sf_base, None, True) == 100)
check("NON-mulligan control: SF full value = 200",
      se.finalize_points(sf_base, None, False) == 200)

# Champion ladder = 1000; halved = 500; with All-In, token-first => 1000*5*0.5 = 2500.
champ_base = se.dark_horse_payout(77, TIERS_CHAMP, CHAMP)
check("dark_horse Champion ladder = 1000", champ_base == 1000)
check("mulliganed Champion, no token = 500", se.finalize_points(champ_base, None, True) == 500)
check("mulliganed Champion + All-In = 2500 (token THEN halve)",
      se.finalize_points(champ_base, "AllIn", True) == 2500)
# Order is only *observable* under rounding. At base 25 + All-In:
#   token-then-halve = round(25*5*0.5) = round(62.5) = 62   (the engine's order)
#   halve-then-token = round(25*0.5)*5 = 12*5          = 60
check("token-then-halve (62) differs from halve-then-token (60) when rounding bites",
      se.finalize_points(25, "AllIn", True) == 62 and int(round(25 * 0.5)) * 5 == 60)

# ---- rounding lock: engine uses round() (banker's) on the half-value ---------
# R16 ladder = 25 -> 12.5 -> round() gives 12 (rounds to even). Pin it so a future
# switch to int()/ceil() is caught.
check("R16 ladder = 25", se.dark_horse_payout(77, {"R16": {77}}, None) == 25)
check("mulliganed R16 = 12 (round-half-to-even on 12.5)",
      se.finalize_points(25, None, True) == 12)

# ---- equivalence with the pre-refactor inline expression --------------------
# finalize_points must equal the exact code it replaced, for every token/flag combo.
for base in (0, 5, 25, 75, 200, 500, 1000):
    for tok in (None, "Double", "Triple", "AllIn"):
        for mull in (False, True):
            old = se.apply_token(base, tok)
            if mull:
                old = int(round(old * se.MULLIGAN_FACTOR))
            check(f"equiv base={base} tok={tok} mull={mull}",
                  se.finalize_points(base, tok, mull) == old)

# ---- knockout winners advance one round (R32 result must score) -------------
# A team that WINS its R32 match has reached the R16; the bracket/dark-horse scorers
# read teams_in_match_tier, so the winner must be propagated there. Regression intent:
# if winners stop advancing, an R32 result scores nothing until R16 fixtures publish.
r = se.reached_via_winners([("R32", 5529)])               # Canada wins its R32
check("R32 winner reaches R16", r == {"R16": {5529}})
check("R32 winner makes team_reached(R16) true",
      se.team_reached(5529, "R16", r, None) is True)
check("R32 winner advances the dark-horse ladder to R16=25",
      se.dark_horse_payout(5529, r, None) == 25)
chain = se.reached_via_winners([("R32", 1), ("R16", 1), ("QF", 1), ("SF", 1)])
check("winners chain R32->R16->QF->SF->Final",
      chain == {"R16": {1}, "QF": {1}, "SF": {1}, "Final": {1}})
check("a LOSER (non-winner) is never advanced",
      se.reached_via_winners([("R32", None)]) == {})
check("group results don't advance anyone",
      se.reached_via_winners([("group", 5529)]) == {})
check("Final winner is NOT auto-advanced here (Champion handled separately)",
      "Champion" not in se.reached_via_winners([("Final", 7)]))
check("multiple R32 winners accumulate in R16",
      se.reached_via_winners([("R32", 1), ("R32", 2)]) == {"R16": {1, 2}})

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
