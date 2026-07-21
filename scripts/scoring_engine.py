#!/usr/bin/env python3
"""
scoring_engine.py — recompute the World Cup 2026 pool scores from Airtable.

Reads Matches + Predictions + SideGames + Mulligans, computes points for every
prediction, and writes back `points_awarded`, `beat_rival_bonus`, `resolved`, then
rolls each player's `total_score` in PoolPlayers. Idempotent — safe to run after
every poll (locally or in CI). Stdlib only.

    cd ~/Desktop/WorldCup2026
    python3 scripts/scoring_engine.py --dry-run     # compute + print, write nothing
    python3 scripts/scoring_engine.py               # write back
    python3 scripts/scoring_engine.py --verbose     # per-prediction breakdown

WHAT IT SCORES TODAY (everything derivable from data we have):
  • match_outcome  — group + knockout, round-tiered, +exact-score bonus, Beat-Cal +3
  • bracket_slot   — R16/QF/SF/Finalist/Champion, resolved from teams-reached-each-round
  • dark_horse     — escalating ladder, live until the Final decides it
  • side_game      — compared against SideGames.resolved_value (incl. total-goals
                     "closest without going over"); base points read from the table
  • confidence tokens (soft downside) and the mulligan 50% factor

PENDING (no data yet, engine stays correct and inert until it arrives):
  • knockout MATCH picks — no entry UI; only group matches are entered
  • auto-filling SideGames.resolved_value (Golden Boot etc.) — a separate follow-on;
    until a value is filled, that side game stays unresolved (0 pts)
  • exact knockout round-name strings — fill ROUND_TIER_OVERRIDES once they publish
"""
import argparse, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.2

# ---- scoring config (edit here; mirrors 03_Scoring_spec_v1.0.md) ------------
MATCH_PTS = {
    "group":      {"outcome": 5,  "exact": 10},
    "R32":        {"outcome": 10, "exact": 15},
    "R16":        {"outcome": 15, "exact": 15},
    "QF":         {"outcome": 20, "exact": 20},
    "SF":         {"outcome": 30, "exact": 25},
    "Final":      {"outcome": 50, "exact": 30},
    "ThirdPlace": {"outcome": 20, "exact": 15},
}
BRACKET_PTS = {"R16": 5, "QF": 10, "SF": 20, "Finalist": 40, "Champion": 150}  # Champion 150 (locked 2026-06-06)
DARK_HORSE = {"R16": 25, "QF": 75, "SF": 200, "Final": 500, "Champion": 1000}
# Per-match bonus bets (spec §bonus bets; binary, "No" on Over 2.5 = Under 2.5).
# Co-participation rule: a match's bonus bets only score if BOTH players attached
# at least one bonus bet (of any type) to that match.
BONUS_PTS = {"BTTS": 10, "Over 2.5 goals": 10, "Penalty in match": 15,
             "Red card in match": 20, "Both teams score 2+": 15, "Goal in first 15 min": 15}
BEAT_RIVAL = 3
TOKEN_MULT = {"Double": 2, "Triple": 3, "AllIn": 5}
MULLIGAN_FACTOR = 0.5

EXPECTED_IN_TIER = {"R16": 16, "QF": 8, "SF": 4, "Finalist": 2}   # for "tier complete" tests
BRACKET_TO_MATCHTIER = {"R16": "R16", "QF": "QF", "SF": "SF", "Finalist": "Final"}

# A knockout WIN means the team reached the next round's tier. Bracket/dark-horse
# scoring keys off teams_in_match_tier[<reached tier>]; without propagating winners
# forward, an R32 result credits NOTHING until the API later publishes the R16
# fixture containing that team — so a correct R32-winner pick (and a mulligan onto
# an R32 winner) would score 0 for days. Maps a finished match's tier -> the tier
# its winner has thereby reached. (Final winner is the Champion, handled separately.)
NEXT_REACHED = {"R32": "R16", "R16": "QF", "QF": "SF", "SF": "Final"}

# Knockout round-name strings aren't in the API feed yet. Fill exact strings here
# once they publish, e.g. {"Round of 32": "R32", "8th Finals": "R16"}.
ROUND_TIER_OVERRIDES = {}

# ---- pure helpers (unit-tested) --------------------------------------------
def round_tier(r):
    """Map a Matches.round string to a scoring tier key, or None."""
    if not r:
        return None
    if r in ROUND_TIER_OVERRIDES:
        return ROUND_TIER_OVERRIDES[r]
    rl = str(r).lower()
    if rl.startswith("group"):
        return "group"
    if "semi" in rl:
        return "SF"
    if "quarter" in rl:
        return "QF"
    if "3rd" in rl or "third" in rl:
        return "ThirdPlace"
    if "round of 32" in rl or "1/16" in rl:
        return "R32"
    if "round of 16" in rl or "1/8" in rl or "8th" in rl:
        return "R16"
    if "final" in rl:           # checked last — 'semi/quarter/third' already handled
        return "Final"
    return None

def actual_outcome(hs, as_):
    if hs is None or as_ is None:
        return None
    if hs > as_:
        return "Home"
    if hs < as_:
        return "Away"
    return "Draw"

def bracket_tier(slot_key):
    if not slot_key:
        return None
    if slot_key == "Champion":
        return "Champion"
    if slot_key.startswith("R16"):
        return "R16"
    if slot_key.startswith("QF"):
        return "QF"
    if slot_key.startswith("SF"):
        return "SF"
    if slot_key.startswith("F-"):
        return "Finalist"
    return None

def team_reached(team_id, btier, teams_in_match_tier, champion_id):
    if btier == "Champion":
        return champion_id is not None and team_id == champion_id
    mt = BRACKET_TO_MATCHTIER.get(btier)
    return team_id in teams_in_match_tier.get(mt, set())

def reached_via_winners(finished_ko):
    """Propagate knockout winners one round forward. `finished_ko` is an iterable of
    (tier, winner_id) for FINISHED matches; returns {reached_tier: set(team_id)}. A team
    that wins a round has REACHED the next round's tier (R32 win -> R16, R16 -> QF, ...).
    This is what makes an R32 result actually score a bracket/dark-horse pick instead of
    waiting for the API to publish the next-round fixture. (Final winner = Champion,
    handled separately.) Pure and order-independent."""
    out = {}
    for tier, w in finished_ko:
        nxt = NEXT_REACHED.get(tier)
        if nxt and w is not None:
            out.setdefault(nxt, set()).add(w)
    return out

def tier_complete(btier, teams_in_match_tier, final_done):
    if btier == "Champion":
        return final_done
    mt = BRACKET_TO_MATCHTIER.get(btier)
    return len(teams_in_match_tier.get(mt, set())) >= EXPECTED_IN_TIER.get(btier, 999)

def dark_horse_payout(team_id, teams_in_match_tier, champion_id):
    """Highest tier reached (non-cumulative)."""
    pay = 0
    if team_id in teams_in_match_tier.get("R16", set()):
        pay = DARK_HORSE["R16"]
    if team_id in teams_in_match_tier.get("QF", set()):
        pay = DARK_HORSE["QF"]
    if team_id in teams_in_match_tier.get("SF", set()):
        pay = DARK_HORSE["SF"]
    if team_id in teams_in_match_tier.get("Final", set()):
        pay = DARK_HORSE["Final"]
    if champion_id is not None and team_id == champion_id:
        pay = DARK_HORSE["Champion"]
    return pay

def score_match_pick(pred_outcome, pred_sh, pred_sa, hs, as_, tier):
    """Base points for a match_outcome prediction against a finished match. Returns (pts, correct)."""
    cfg = MATCH_PTS.get(tier) or MATCH_PTS["group"]
    ao = actual_outcome(hs, as_)
    if ao is None:
        return 0, None
    correct = (pred_outcome == ao)
    if not correct:
        return 0, False
    pts = cfg["outcome"]
    if pred_sh is not None and pred_sa is not None and pred_sh == hs and pred_sa == as_:
        pts += cfg["exact"]
    return pts, True

def total_goals_winners(guesses, actual):
    """guesses: {player: int}. Closest WITHOUT going over. Returns set of winning players."""
    eligible = {p: g for p, g in guesses.items() if g is not None and g <= actual}
    if not eligible:
        return set()
    best = max(eligible.values())
    return {p for p, g in eligible.items() if g == best}

def apply_token(base_pts, token):
    if base_pts > 0 and token in TOKEN_MULT:
        return base_pts * TOKEN_MULT[token]
    return base_pts

def mulligan_affected(mulls):
    """Set of Prediction record ids touched by any mulligan — both the original (now
    invalidated) and the replacement pick. Type-agnostic by construction: it reads the
    link fields without inspecting prediction_type, so it covers bracket_slot picks (v1.0)
    and the Dark Horse (v1.1) identically. `mulls` are Airtable records ({"id","fields"})."""
    affected = set()
    for m in mulls:
        f = m["fields"]
        for fld in ("original_prediction", "new_prediction"):
            for rid in (f.get(fld) or []):
                affected.add(rid)
    return affected

def finalize_points(base_pts, token, mulliganed):
    """A prediction's final base points: confidence token first, THEN the mulligan 50%
    factor if this pick was mulliganed (spec 'token first, then halve' ordering). Applies
    to any mulligan-eligible pick — bracket_slot (v1.0) and dark_horse (v1.1)."""
    pts = apply_token(base_pts, token)
    if mulliganed:
        pts = int(round(pts * MULLIGAN_FACTOR))
    return pts

def first_claim(seen, key):
    """Pool rule (erratum 2026-06-06): within a bracket round, each team counts at most
    once per player. First claim (rows processed in label order, so deterministic) scores;
    duplicates are void. Returns True on first claim, False on a duplicate."""
    if key in seen:
        return False
    seen.add(key)
    return True

def norm(s):
    return (s or "").strip().casefold()

def rv_winners(rv):
    """SideGames.resolved_value may name joint winners separated by '|'
    (written by resolve_sidegames.py on ties). -> set of normalized answers."""
    return {norm(x) for x in str(rv or "").split("|") if norm(x)}

def side_game_hit(guess, rv):
    return norm(guess) in rv_winners(rv) if guess is not None else False

def bonus_actuals(hs, as_, events):
    """Actual Yes/No outcome of every bonus-bet type for a finished match.
    events: parsed events_json list. Shootout kicks never count; a VAR-cancelled
    penalty is not an awarded penalty; a missed penalty IS one. Own goals count
    toward 'Goal in first 15 min' (a goal is a goal); score-based bets read the
    stored full-time score (extra time included)."""
    pen = red = early = False
    for ev in events or []:
        t = (ev.get("type") or "").lower()
        d = (ev.get("detail") or "").lower()
        c = (ev.get("comments") or "").lower()
        if "shootout" in c or "shootout" in d:
            continue
        if t == "card" and "red" in d:
            red = True
        if "penalty" in d and "cancel" not in d:
            pen = True
        if t == "goal" and "missed" not in d:
            if ((ev.get("time") or {}).get("elapsed") or 0) <= 15:
                early = True
    hs = hs or 0; as_ = as_ or 0
    return {"BTTS": hs > 0 and as_ > 0,
            "Over 2.5 goals": hs + as_ >= 3,
            "Penalty in match": pen,
            "Red card in match": red,
            "Both teams score 2+": hs >= 2 and as_ >= 2,
            "Goal in first 15 min": early}

def score_bonus(bet_type, bet_value, actuals):
    """-> (base_points, correct) for one bonus bet against computed actuals."""
    if bet_type not in BONUS_PTS or bet_type not in actuals:
        return 0, False
    correct = (norm(bet_value) == "yes") == bool(actuals[bet_type])
    return (BONUS_PTS[bet_type] if correct else 0), correct

# ---- credentials + Airtable client -----------------------------------------
def load_keys():
    keys = {k: os.environ.get(k) for k in ("AIRTABLE_PAT", "AIRTABLE_BASE_ID")}
    p = ROOT / ".env.local"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if not keys.get(k.strip()):
                    keys[k.strip()] = v.strip()
    if not keys["AIRTABLE_PAT"] or not keys["AIRTABLE_BASE_ID"]:
        sys.exit("✗ AIRTABLE_PAT / AIRTABLE_BASE_ID missing from .env.local")
    return keys["AIRTABLE_PAT"], keys["AIRTABLE_BASE_ID"]

def at_request(method, path, pat, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{REST}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1)); continue
            raise RuntimeError(f"Airtable HTTP {e.code} {method} {path}: {e.read().decode()[:240]}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(1.5); continue
            raise RuntimeError(f"Airtable network error {method} {path}: {e.reason}")
    raise RuntimeError(f"Airtable retries exhausted: {method} {path}")

def at_list(base, table, pat, fields=None):
    out, offset = [], None
    q = {"pageSize": 100}
    if fields:
        q["fields[]"] = fields
    while True:
        qq = dict(q)
        if offset:
            qq["offset"] = offset
        res = at_request("GET", f"{base}/{urllib.parse.quote(table)}?" + urllib.parse.urlencode(qq, doseq=True), pat)
        out.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset:
            return out

def at_update(base, table, pat, updates, dry=False):
    n = 0
    for i in range(0, len(updates), 10):
        batch = updates[i:i + 10]
        if dry:
            n += len(batch); continue
        at_request("PATCH", f"{base}/{urllib.parse.quote(table)}", pat, {"records": batch})
        time.sleep(WRITE_PAUSE)
        n += len(batch)
    return n

# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    pat, base = load_keys()
    print(f"scoring_engine{'  · DRY RUN' if args.dry_run else ''}")

    # --- load ---
    teams = at_list(base, "Teams", pat, fields=["team_id", "name", "code"])
    rec2team = {r["id"]: r["fields"] for r in teams}                       # rec -> {team_id,name,code}
    foots = at_list(base, "Footballers", pat, fields=["player_id", "name"])
    rec2foot = {r["id"]: r["fields"].get("name") for r in foots}
    sgs = at_list(base, "SideGames", pat,
                  fields=["name", "resolution_type", "base_points", "resolved_value"])
    rec2sg = {r["id"]: r["fields"] for r in sgs}
    matches = at_list(base, "Matches", pat,
                      fields=["fixture_id", "round", "status", "home_score", "away_score",
                              "home_team", "away_team", "winner", "events_json"])
    pool = at_list(base, "PoolPlayers", pat, fields=["name"])
    rec2player = {r["id"]: r["fields"].get("name") for r in pool}
    preds = at_list(base, "Predictions", pat)
    # v1.2: stoppage-pot rows are tally-owned — pot_points and `resolved` are written by
    # scripts/setup_stoppage_pot.py --tally, never by the engine. Before 2026-07-21 the
    # blanket finalize below rewrote resolved=False on them every run (the type dispatch
    # doesn't know stoppage_bet), re-sealing their pundit notes on the live board hours
    # after the tally had unsealed them. Drop pot rows here so the engine never sees them;
    # they carry points_awarded 0 and are excluded from total_score either way.
    preds = [r for r in preds
             if r.get("fields", {}).get("pot") != "stoppage"
             and r.get("fields", {}).get("prediction_type") != "stoppage_bet"]
    preds.sort(key=lambda r: r.get("fields", {}).get("label", ""))   # deterministic dedupe order
    mulls = at_list(base, "Mulligans", pat, fields=["original_prediction", "new_prediction"])
    mull_affected = mulligan_affected(mulls)

    # --- match index + teams-reached map ---
    match_by_rec = {}
    teams_in_match_tier = {}          # tier -> set(team_id)
    champion_id = None
    final_done = False
    for r in matches:
        f = r["fields"]
        tier = round_tier(f.get("round"))
        h = [rec2team[x]["team_id"] for x in (f.get("home_team") or []) if x in rec2team]
        a = [rec2team[x]["team_id"] for x in (f.get("away_team") or []) if x in rec2team]
        try:
            events = json.loads(f.get("events_json") or "[]")
        except (ValueError, TypeError):
            events = []
        match_by_rec[r["id"]] = {
            "tier": tier, "status": f.get("status"),
            "hs": f.get("home_score"), "as": f.get("away_score"),
            "home": h[0] if h else None, "away": a[0] if a else None,
            "winner": next((rec2team[x]["team_id"] for x in (f.get("winner") or []) if x in rec2team), None),
            "events": events if isinstance(events, list) else [],
        }
        if tier:
            s = teams_in_match_tier.setdefault(tier, set())
            s.update(h); s.update(a)
        if tier == "Final" and f.get("status") == "Finished":
            final_done = True
            w = match_by_rec[r["id"]]["winner"]
            if w is not None:
                champion_id = w

    # Advance knockout winners into the tier they thereby reached, so an R32/R16/...
    # result scores its bracket + dark-horse picks immediately (see reached_via_winners).
    for rtier, ids in reached_via_winners(
            (m["tier"], m["winner"]) for m in match_by_rec.values()
            if m["status"] == "Finished").items():
        teams_in_match_tier.setdefault(rtier, set()).update(ids)

    # --- pass 1: base points + resolved per prediction ---
    base_pts = {}        # pred rec -> base points (pre-token)
    resolved = {}        # pred rec -> bool
    pred_player = {}     # pred rec -> player name
    token_of = {}        # pred rec -> token
    match_correct = {}   # (match_rec) -> {player: bool}  (for Beat-Cal)
    pred_match = {}      # pred rec -> match_rec
    total_goals_guess = {}   # player -> guessed scalar (for the cross-player resolve)
    total_goals_rows = {}    # player -> pred rec  (where to write the result)
    total_goals_sg = None    # the SideGames fields for Total Tournament Goals
    bonus_rows = []          # (pred rec, fields, player, match_rec) — scored after the loop
    bracket_seen = set()     # (player, tier, team_id) — duplicate slots in a round are void

    for r in preds:
        f = r["fields"]
        rec = r["id"]
        ptype = f.get("prediction_type")
        player = rec2player.get((f.get("pool_player") or [None])[0])
        pred_player[rec] = player
        token_of[rec] = f.get("confidence_token")
        bp, res = 0, False

        if ptype == "match_outcome":
            mlink = (f.get("match") or [None])[0]
            m = match_by_rec.get(mlink)
            pred_match[rec] = mlink
            if m and m["status"] == "Finished":
                bp, correct = score_match_pick(
                    f.get("predicted_outcome"), f.get("predicted_score_home"),
                    f.get("predicted_score_away"), m["hs"], m["as"], m["tier"])
                res = True
                if correct is not None and mlink is not None:
                    match_correct.setdefault(mlink, {})[player] = bool(correct)

        elif ptype == "bracket_slot":
            btier = bracket_tier(f.get("bracket_slot"))
            tid = next((rec2team[x]["team_id"] for x in (f.get("predicted_team") or []) if x in rec2team), None)
            if btier and tid is not None:
                if not first_claim(bracket_seen, (player, btier, tid)):
                    base_pts[rec] = 0; resolved[rec] = True   # duplicate team in round — void
                    continue
                if team_reached(tid, btier, teams_in_match_tier, champion_id):
                    bp, res = BRACKET_PTS[btier], True
                elif tier_complete(btier, teams_in_match_tier, final_done):
                    bp, res = 0, True       # tier filled, team not in it → definitively missed

        elif ptype == "dark_horse":
            tid = next((rec2team[x]["team_id"] for x in (f.get("predicted_team") or []) if x in rec2team), None)
            if tid is not None:
                bp = dark_horse_payout(tid, teams_in_match_tier, champion_id)   # live value
                res = final_done                                               # final figure at tournament end

        elif ptype == "bonus_bet":
            # needs the full per-match opt-in picture (co-participation) — defer
            mlink = (f.get("match") or [None])[0]
            bonus_rows.append((rec, f, player, mlink))
            base_pts[rec] = 0; resolved[rec] = False
            continue

        elif ptype == "side_game":
            sg = rec2sg.get((f.get("side_game") or [None])[0], {})
            rtype = sg.get("resolution_type")
            rv = sg.get("resolved_value")
            basep = sg.get("base_points") or 0
            if rtype == "scalar":      # Total Tournament Goals — resolved across both players below
                total_goals_sg = sg
                if f.get("predicted_scalar") is not None:
                    total_goals_guess[player] = f.get("predicted_scalar")
                    total_goals_rows[player] = rec
                base_pts[rec] = 0; resolved[rec] = bool(rv); continue
            if rv:                     # player / team / event_player
                res = True
                guess = None
                if f.get("predicted_player"):
                    guess = rec2foot.get(f["predicted_player"][0])
                elif f.get("predicted_team"):
                    t = rec2team.get(f["predicted_team"][0], {})
                    guess = t.get("name")
                    if norm(t.get("code")) in rv_winners(rv):
                        guess = t.get("code")
                elif f.get("predicted_text"):
                    guess = f.get("predicted_text")
                if side_game_hit(guess, rv):   # joint winners ("A | B") both pay
                    bp = basep

        base_pts[rec] = bp
        resolved[rec] = res

    # --- Total Tournament Goals: closest without going over (cross-player) ---
    if total_goals_sg and total_goals_sg.get("resolved_value"):
        try:
            actual = int(float(total_goals_sg["resolved_value"]))
            winners = total_goals_winners(total_goals_guess, actual)
            basep = total_goals_sg.get("base_points") or 0
            for player, rec in total_goals_rows.items():
                base_pts[rec] = basep if player in winners else 0
                resolved[rec] = True
        except (ValueError, TypeError):
            pass

    # --- bonus bets: co-participation, then independent scoring -----------------
    # A match's bonus bets only score if BOTH players attached at least one bet to
    # it (anti-carpet-bomb). One-sided opt-ins resolve to 0 (void) when the match
    # finishes. No Beat-Rival on bonus bets; tokens/mulligan apply in finalize.
    optin = {}                                    # match_rec -> set(players with ≥1 bet)
    for _rec, _f, player, mlink in bonus_rows:
        if mlink is not None:
            optin.setdefault(mlink, set()).add(player)
    for rec, f, player, mlink in bonus_rows:
        m = match_by_rec.get(mlink)
        if not m or m["status"] != "Finished":
            continue                              # stays unresolved until FT
        resolved[rec] = True
        if len(optin.get(mlink, set())) >= 2:
            actuals = bonus_actuals(m["hs"], m["as"], m["events"])
            bp, _ = score_bonus(f.get("bonus_bet_type"), f.get("bonus_bet_value"), actuals)
            base_pts[rec] = bp
        else:
            base_pts[rec] = 0                     # void — opponent never opted in

    # --- Beat-Cal bonus: per match, correct AND a rival is not correct → +3 ---
    beat = {}    # pred rec -> bonus
    for mrec, by_player in match_correct.items():
        for player, ok in by_player.items():
            # +3 if this player is correct AND at least one rival who also picked got it wrong
            if ok and any(not c for o, c in by_player.items() if o != player):
                # find this player's prediction row for the match
                for rec, mr in pred_match.items():
                    if mr == mrec and pred_player.get(rec) == player:
                        beat[rec] = BEAT_RIVAL

    # --- finalize: token, mulligan; build updates + totals ---
    updates = []
    totals = {}
    for r in preds:
        rec = r["id"]
        pts = finalize_points(base_pts.get(rec, 0), token_of.get(rec), rec in mull_affected)
        br = beat.get(rec, 0)
        player = pred_player.get(rec)
        totals[player] = totals.get(player, 0) + pts + br
        updates.append({"id": rec, "fields": {
            "points_awarded": pts, "beat_rival_bonus": br, "resolved": bool(resolved.get(rec, False))}})
        if args.verbose and (pts or br):
            f = r["fields"]
            print(f"  · {player:<8} {f.get('prediction_type'):<14} {f.get('label','')[:34]:<34} "
                  f"pts={pts} beat={br} {'✓' if resolved.get(rec) else '·'}")

    n = at_update(base, "Predictions", pat, updates, dry=args.dry_run)

    # --- roll up PoolPlayers.total_score ---
    pool_updates = []
    for r in pool:
        nm = r["fields"].get("name")
        pool_updates.append({"id": r["id"], "fields": {"total_score": totals.get(nm, 0)}})
    at_update(base, "PoolPlayers", pat, pool_updates, dry=args.dry_run)

    print("—" * 44)
    for nm in sorted(totals):
        print(f"  {nm:<10} {totals[nm]} pts")
    resolved_n = sum(1 for v in resolved.values() if v)
    print(f"· {n} predictions scored{' (dry)' if args.dry_run else ''} · {resolved_n} resolved · "
          f"champion={'set' if champion_id else 'TBD'}")


if __name__ == "__main__":
    main()
