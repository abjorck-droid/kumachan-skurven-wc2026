#!/usr/bin/env python3
"""
pickentry_server.py — local pick-entry server for the World Cup 2026 bracket pool.

Keeps the Airtable PAT server-side (it never reaches the browser) and proxies reads/writes.
Run it on your Mac, then open the printed URL. You and Cal each pick a player at the top.

    cd ~/Desktop/WorldCup2026
    python3 scripts/pickentry_server.py            # serves http://127.0.0.1:8787
    python3 scripts/pickentry_server.py --port 9000

Requires the Airtable base to exist (run scripts/create_base.py first) and
AIRTABLE_PAT / AIRTABLE_BASE_ID in .env.local. Stdlib only.

Predictions are keyed on a deterministic `label` ("<Player>|<pick-key>") and written with
Airtable upsert, so saving repeatedly just updates — no duplicates. Player-name side games
use free text (predicted_text) until the Footballers table is populated.
"""
import argparse, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "index.html"
REST = "https://api.airtable.com/v0"
START_TOKENS = {"Double": 4, "Triple": 2, "AllIn": 1}
# Per-match bonus-bet menu (mirrors the Pages Function; all binary Yes/No).
BONUS_TYPES = ["BTTS", "Over 2.5 goals", "Penalty in match", "Red card in match",
               "Both teams score 2+", "Goal in first 15 min"]

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

PAT, BASE = (None, None)  # set in main()

# ---- airtable --------------------------------------------------------------
def at(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{REST}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {PAT}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.2 * (attempt + 1)); continue
            raise RuntimeError(f"Airtable HTTP {e.code} {method} {path}: {e.read().decode()[:240]}")
    raise RuntimeError(f"Airtable retries exhausted: {method} {path}")

def at_list(table, fields=None):
    out, offset, q = [], None, {"pageSize": 100}
    if fields:
        q["fields[]"] = fields
    while True:
        qq = dict(q)
        if offset:
            qq["offset"] = offset
        res = at("GET", f"{BASE}/{urllib.parse.quote(table)}?" + urllib.parse.urlencode(qq, doseq=True))
        out.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset:
            return out

def at_upsert(table, records, merge_on):
    n = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        at("PATCH", f"{BASE}/{urllib.parse.quote(table)}", {
            "performUpsert": {"fieldsToMergeOn": merge_on},
            "records": [{"fields": r} for r in batch], "typecast": True})
        time.sleep(0.2); n += len(batch)
    return n

# ---- pure transform (unit-tested) ------------------------------------------
def prediction_fields(player, pick, team_map, player_rec, sidegame_map, footballer_map=None, match_map=None):
    """Build one Predictions record's fields from a client pick dict."""
    footballer_map = footballer_map or {}
    match_map = match_map or {}
    rec = {"label": f"{player}|{pick['key']}", "pool_player": [player_rec],
           "prediction_type": pick["type"]}
    if pick.get("bracket_slot"):
        rec["bracket_slot"] = pick["bracket_slot"]
    if pick.get("side_game") and pick["side_game"] in sidegame_map:
        rec["side_game"] = [sidegame_map[pick["side_game"]]]
    if pick.get("team_id") is not None and int(pick["team_id"]) in team_map:
        rec["predicted_team"] = [team_map[int(pick["team_id"])]]
    # group-match picks: outcome (Home/Draw/Away) + optional exact score, linked to the match
    if pick.get("match_id") is not None and int(pick["match_id"]) in match_map:
        rec["match"] = [match_map[int(pick["match_id"])]]
    if pick.get("outcome"):
        rec["predicted_outcome"] = pick["outcome"]
    if pick.get("score_home") is not None and pick["score_home"] != "":
        rec["predicted_score_home"] = pick["score_home"]
    if pick.get("score_away") is not None and pick["score_away"] != "":
        rec["predicted_score_away"] = pick["score_away"]
    # player picks: prefer a real Footballers link; fall back to free text if squads
    # aren't imported yet (or the chosen id isn't in the table).
    pid = pick.get("player_id")
    if pid not in (None, "") and str(pid).isdigit() and int(pid) in footballer_map:
        rec["predicted_player"] = [footballer_map[int(pid)]]
    elif pick.get("player_text"):
        rec["predicted_text"] = pick["player_text"]
    if pick.get("scalar") is not None and pick["scalar"] != "":
        rec["predicted_scalar"] = pick["scalar"]
    # per-match bonus bets (binary)
    if pick.get("bet_type"):
        rec["bonus_bet_type"] = pick["bet_type"]
    if pick.get("bet_value"):
        rec["bonus_bet_value"] = pick["bet_value"]
    if pick.get("token"):
        rec["confidence_token"] = pick["token"]
    if pick.get("pundit_note"):
        rec["pundit_note"] = pick["pundit_note"]
    return rec

def token_counts(picks):
    used = {"Double": 0, "Triple": 0, "AllIn": 0}
    for p in picks:
        t = p.get("token")
        if t in used:
            used[t] += 1
    return used

# ---- request handling ------------------------------------------------------
def get_player(name):
    for rec in at_list("PoolPlayers"):
        if rec.get("fields", {}).get("name") == name:
            return rec
    return None

def bootstrap(player):
    team_recs = at_list("Teams", fields=["team_id", "code", "name", "group", "fifa_ranking"])
    rec2tid = {r["id"]: r["fields"].get("team_id") for r in team_recs}
    team_by_rec = {r["id"]: {"code": r["fields"].get("code"), "group": r["fields"].get("group"),
                             "name": r["fields"].get("name"), "team_id": r["fields"].get("team_id")}
                   for r in team_recs}
    teams = [{"id": r["fields"].get("team_id"), "code": r["fields"].get("code"),
              "name": r["fields"].get("name"), "group": r["fields"].get("group"),
              "fifa_ranking": r["fields"].get("fifa_ranking")}
             for r in team_recs if r["fields"].get("team_id") is not None]
    teams.sort(key=lambda t: (t.get("group") or "Z", t.get("name") or ""))
    side = [{"name": r["fields"].get("name"), "base_points": r["fields"].get("base_points"),
             "resolution_type": r["fields"].get("resolution_type")}
            for r in at_list("SideGames", fields=["name", "base_points", "resolution_type"])]
    # Footballers (empty until import_squads.py runs → UI falls back to free text).
    footballers, rec2pid = [], {}
    try:
        for r in at_list("Footballers", fields=["player_id", "name", "position", "shirt_number", "team"]):
            f = r.get("fields", {})
            pid = f.get("player_id")
            if pid is None:
                continue
            rec2pid[r["id"]] = pid
            link = f.get("team") or []
            tinfo = team_by_rec.get(link[0], {}) if link else {}
            footballers.append({"player_id": pid, "name": f.get("name"), "position": f.get("position"),
                                "shirt_number": f.get("shirt_number"),
                                "team_code": tinfo.get("code"), "group": tinfo.get("group")})
        footballers.sort(key=lambda x: ((x.get("group") or "Z"), (x.get("team_code") or ""), (x.get("name") or "")))
    except Exception:
        footballers, rec2pid = [], {}
    # All fixtures (empty until load_fixtures.py runs). The match-picks tab filters to group
    # rounds in the UI; bonus bets can attach to ANY not-yet-started match, knockouts included.
    matches, mrec2fid = [], {}
    try:
        for r in at_list("Matches", fields=["fixture_id", "label", "round", "home_team", "away_team", "kickoff_utc", "status"]):
            f = r.get("fields", {})
            fid = f.get("fixture_id")
            if fid is None:
                continue
            mrec2fid[r["id"]] = fid
            h = f.get("home_team") or []
            a = f.get("away_team") or []
            hi = team_by_rec.get(h[0]) if h else {}
            ai = team_by_rec.get(a[0]) if a else {}
            matches.append({"fixture_id": fid, "round": f.get("round") or "", "kickoff": f.get("kickoff_utc"),
                            "status": f.get("status") or "Scheduled",
                            "group": (hi or {}).get("group") or (ai or {}).get("group"),
                            "home_id": (hi or {}).get("team_id"), "home_code": (hi or {}).get("code"),
                            "home_name": (hi or {}).get("name"), "away_id": (ai or {}).get("team_id"),
                            "away_code": (ai or {}).get("code"), "away_name": (ai or {}).get("name")})
        matches.sort(key=lambda m: ((m.get("group") or "Z"), (m.get("kickoff") or "")))
    except Exception:
        matches, mrec2fid = [], {}
    prow = get_player(player)
    pf = (prow or {}).get("fields", {})
    existing = []
    locked = False
    for r in at_list("Predictions"):
        f = r.get("fields", {})
        lbl = f.get("label", "")
        if lbl.startswith(player + "|"):
            link = f.get("predicted_team") or []
            plink = f.get("predicted_player") or []
            existing.append({"key": lbl.split("|", 1)[1], "type": f.get("prediction_type"),
                             "bracket_slot": f.get("bracket_slot"),
                             "team_id": rec2tid.get(link[0]) if link else None,
                             "player_id": rec2pid.get(plink[0]) if plink else None,
                             "player_text": f.get("predicted_text"), "scalar": f.get("predicted_scalar"),
                             "outcome": f.get("predicted_outcome"),
                             "score_home": f.get("predicted_score_home"), "score_away": f.get("predicted_score_away"),
                             "bet_type": f.get("bonus_bet_type"), "bet_value": f.get("bonus_bet_value"),
                             "token": f.get("confidence_token"), "note": f.get("pundit_note")})
            if f.get("locked_at"):
                locked = True
    return {"player": player, "players": ["Andreas", "Cal"], "teams": teams, "sideGames": side,
            "footballers": footballers, "matches": matches,
            "tokensStart": START_TOKENS, "locked": locked, "existing": existing,
            "tokensRemaining": {"Double": pf.get("tokens_remaining_double", 4),
                                "Triple": pf.get("tokens_remaining_triple", 2),
                                "AllIn": pf.get("tokens_remaining_allin", 1)}}

# ---- official FIFA 2026 bracket data ---------------------------------------------
# Annex C of the FIFA 2026 regulations: third-place allocation, one row per combination of 8 advancing third-place groups (495 rows). Value = the third assigned to the winners of groups A,B,D,E,G,I,K,L in that column order. Row order: lexicographic by the EXCLUDED four groups (row 1 = thirds EFGHIJKL ... row 495 = ABCDEFGH).
# Canonical copy: data/thirds_alloc_2026.json (also embedded in site/index.html and
# functions/api/[[route]].js - keep in sync).
_WC26_BLOB = (
    "EJIFHGLKHGIDJFLKEJIDHGLKEJIDHFLKEGIDJFLKEGJDHFLKEGIDHFLKEGJDHFLIEGJDHFIKHGICJFLKEJICHGLK"
    "EJICHFLKEGICJFLKEGJCHFLKEGICHFLKEGJCHFLIEGJCHFIKHGICJDLKCJIDHFLKCGIDJFLKCGJDHFLKCGIDHFLK"
    "CGJDHFLICGJDHFIKEJICHDLKEGICJDLKEGJCHDLKEGICHDLKEGJCHDLIEGJCHDIKCJEDIFLKCJEDHFLKCEIDHFLK"
    "CJEDHFLICJEDHFIKCGEDJFLKCGEDIFLKCGEDJFLICGEDJFIKCGEDHFLKCGJDHFLECGJDHFEKCGEDHFLICGEDHFIK"
    "CGJDHFEIHJBFIGLKEJIBHGLKEJBFIHLKEJBFIGLKEJBFHGLKEGBFIHLKEJBFHGLIEJBFHGIKHJBDIGLKHJBDIFLK"
    "IGBDJFLKHGBDJFLKHGBDIFLKHGBDJFLIHGBDJFIKEJBDIHLKEJBDIGLKEJBDHGLKEGBDIHLKEJBDHGLIEJBDHGIK"
    "EJBDIFLKEJBDHFLKEIBDHFLKEJBDHFLIEJBDHFIKEGBDJFLKEGBDIFLKEGBDJFLIEGBDJFIKEGBDHFLKHGBDJFLE"
    "HGBDJFEKEGBDHFLIEGBDHFIKHGBDJFEIHJBCIGLKHJBCIFLKIGBCJFLKHGBCJFLKHGBCIFLKHGBCJFLIHGBCJFIK"
    "EJBCIHLKEJBCIGLKEJBCHGLKEGBCIHLKEJBCHGLIEJBCHGIKEJBCIFLKEJBCHFLKEIBCHFLKEJBCHFLIEJBCHFIK"
    "EGBCJFLKEGBCIFLKEGBCJFLIEGBCJFIKEGBCHFLKHGBCJFLEHGBCJFEKEGBCHFLIEGBCHFIKHGBCJFEIHJBCIDLK"
    "IGBCJDLKHGBCJDLKHGBCIDLKHGBCJDLIHGBCJDIKCJBDIFLKCJBDHFLKCIBDHFLKCJBDHFLICJBDHFIKCGBDJFLK"
    "CGBDIFLKCGBDJFLICGBDJFIKCGBDHFLKCGBDHFLJHGBCJFDKCGBDHFLICGBDHFIKHGBCJFDIEJBCIDLKEJBCHDLK"
    "EIBCHDLKEJBCHDLIEJBCHDIKEGBCJDLKEGBCIDLKEGBCJDLIEGBCJDIKEGBCHDLKHGBCJDLEHGBCJDEKEGBCHDLI"
    "EGBCHDIKHGBCJDEICJBDEFLKCEBDIFLKCJBDEFLICJBDEFIKCEBDHFLKCJBDHFLECJBDHFEKCEBDHFLICEBDHFIK"
    "CJBDHFEICGBDEFLKCGBDJFLECGBDJFEKCGBDEFLICGBDEFIKCGBDJFEICGBDHFLECGBDHFEKHGBCJFDECGBDHFEI"
    "HJIFAGLKEJIAHGLKEJIFAHLKEJIFAGLKEGJFAHLKEGIFAHLKEGJFAHLIEGJFAHIKHJIDAGLKHJIDAFLKIGJDAFLK"
    "HGJDAFLKHGIDAFLKHGJDAFLIHGJDAFIKEJIDAHLKEJIDAGLKEGJDAHLKEGIDAHLKEGJDAHLIEGJDAHIKEJIDAFLK"
    "HJEDAFLKHEIDAFLKHJEDAFLIHJEDAFIKEGJDAFLKEGIDAFLKEGJDAFLIEGJDAFIKHGEDAFLKHGJDAFLEHGJDAFEK"
    "HGEDAFLIHGEDAFIKHGJDAFEIHJICAGLKHJICAFLKIGJCAFLKHGJCAFLKHGICAFLKHGJCAFLIHGJCAFIKEJICAHLK"
    "EJICAGLKEGJCAHLKEGICAHLKEGJCAHLIEGJCAHIKEJICAFLKHJECAFLKHEICAFLKHJECAFLIHJECAFIKEGJCAFLK"
    "EGICAFLKEGJCAFLIEGJCAFIKHGECAFLKHGJCAFLEHGJCAFEKHGECAFLIHGECAFIKHGJCAFEIHJICADLKIGJCADLK"
    "HGJCADLKHGICADLKHGJCADLIHGJCADIKCJIDAFLKHJFCADLKHFICADLKHJFCADLIHJFCADIKCGJDAFLKCGIDAFLK"
    "CGJDAFLICGJDAFIKHGFCADLKCGJDAFLHHGJCAFDKHGFCADLIHGFCADIKHGJCAFDIEJICADLKHJECADLKHEICADLK"
    "HJECADLIHJECADIKEGJCADLKEGICADLKEGJCADLIEGJCADIKHGECADLKHGJCADLEHGJCADEKHGECADLIHGECADIK"
    "HGJCADEICJEDAFLKCEIDAFLKCJEDAFLICJEDAFIKHEFCADLKHJFCADLEHJECAFDKHEFCADLIHEFCADIKHJECAFDI"
    "CGEDAFLKCGJDAFLECGJDAFEKCGEDAFLICGEDAFIKCGJDAFEIHGFCADLEHGECAFDKHGJCAFDEHGECAFDIHJBAIGLK"
    "HJBAIFLKIJBFAGLKHJBFAGLKHGBAIFLKHJBFAGLIHJBFAGIKEJBAIHLKEJBAIGLKEJBAHGLKEGBAIHLKEJBAHGLI"
    "EJBAHGIKEJBAIFLKEJBFAHLKEIBFAHLKEJBFAHLIEJBFAHIKEJBFAGLKEGBAIFLKEJBFAGLIEJBFAGIKEGBFAHLK"
    "HJBFAGLEHJBFAGEKEGBFAHLIEGBFAHIKHJBFAGEIIJBDAHLKIJBDAGLKHJBDAGLKIGBDAHLKHJBDAGLIHJBDAGIK"
    "IJBDAFLKHJBDAFLKHIBDAFLKHJBDAFLIHJBDAFIKFJBDAGLKIGBDAFLKFJBDAGLIFJBDAGIKHGBDAFLKHGBDAFLJ"
    "HGBDAFJKHGBDAFLIHGBDAFIKHGBDAFIJEJBAIDLKEJBDAHLKEIBDAHLKEJBDAHLIEJBDAHIKEJBDAGLKEGBAIDLK"
    "EJBDAGLIEJBDAGIKEGBDAHLKHJBDAGLEHJBDAGEKEGBDAHLIEGBDAHIKHJBDAGEIEJBDAFLKEIBDAFLKEJBDAFLI"
    "EJBDAFIKHEBDAFLKHJBDAFLEHJBDAFEKHEBDAFLIHEBDAFIKHJBDAFEIEGBDAFLKEGBDAFLJEGBDAFJKEGBDAFLI"
    "EGBDAFIKEGBDAFIJHGBDAFLEHGBDAFEKHGBDAFEJHGBDAFEIIJBCAHLKIJBCAGLKHJBCAGLKIGBCAHLKHJBCAGLI"
    "HJBCAGIKIJBCAFLKHJBCAFLKHIBCAFLKHJBCAFLIHJBCAFIKCJBFAGLKIGBCAFLKCJBFAGLICJBFAGIKHGBCAFLK"
    "HGBCAFLJHGBCAFJKHGBCAFLIHGBCAFIKHGBCAFIJEJBAICLKEJBCAHLKEIBCAHLKEJBCAHLIEJBCAHIKEJBCAGLK"
    "EGBAICLKEJBCAGLIEJBCAGIKEGBCAHLKHJBCAGLEHJBCAGEKEGBCAHLIEGBCAHIKHJBCAGEIEJBCAFLKEIBCAFLK"
    "EJBCAFLIEJBCAFIKHEBCAFLKHJBCAFLEHJBCAFEKHEBCAFLIHEBCAFIKHJBCAFEIEGBCAFLKEGBCAFLJEGBCAFJK"
    "EGBCAFLIEGBCAFIKEGBCAFIJHGBCAFLEHGBCAFEKHGBCAFEJHGBCAFEIIJBCADLKHJBCADLKHIBCADLKHJBCADLI"
    "HJBCADIKCJBDAGLKIGBCADLKCJBDAGLICJBDAGIKHGBCADLKHGBCADLJHGBCADJKHGBCADLIHGBCADIKHGBCADIJ"
    "CJBDAFLKCIBDAFLKCJBDAFLICJBDAFIKHFBCADLKCJBDAFLHHJBCAFDKHFBCADLIHFBCADIKHJBCAFDICGBDAFLK"
    "CGBDAFLJCGBDAFJKCGBDAFLICGBDAFIKCGBDAFIJCGBDAFLHHGBCAFDKHGBCAFDJHGBCAFDIEJBCADLKEIBCADLK"
    "EJBCADLIEJBCADIKHEBCADLKHJBCADLEHJBCADEKHEBCADLIHEBCADIKHJBCADEIEGBCADLKEGBCADLJEGBCADJK"
    "EGBCADLIEGBCADIKEGBCADIJHGBCADLEHGBCADEKHGBCADEJHGBCADEICEBDAFLKCJBDAFLECJBDAFEKCEBDAFLI"
    "CEBDAFIKCJBDAFEIHFBCADLEHEBCAFDKHJBCAFDEHEBCAFDICGBDAFLECGBDAFEKCGBDAFEJCGBDAFEIHGBCAFDE"
)

def _wc26_alloc():
    from itertools import combinations
    out, letters = {}, "ABCDEFGHIJKL"
    for r, ex in enumerate(combinations(letters, 4)):
        out["".join(g for g in letters if g not in ex)] = _WC26_BLOB[r * 8:(r + 1) * 8]
    return out

WC26_ALLOC = _wc26_alloc()
# Match-feed parents per round: WC26_PARENT[1][r32 match 1-16] = R16 match 1-8
# (FIFA 89-96), [2] R16->QF (97-100), [3] QF->SF (101-102), [4] SF->Final.
WC26_PARENT = [None,
               [0, 2, 1, 2, 3, 1, 3, 4, 4, 6, 6, 5, 5, 8, 7, 8, 7],
               [0, 1, 1, 3, 3, 2, 2, 4, 4],
               [0, 1, 1, 2, 2],
               [0, 1, 1]]

def bracket_guard(picks, teams_by_code):
    """Propagated-bracket validation (mirrors the Pages Function bracketGuard).

    Set-level rules always apply: no duplicate team in a round, rounds nest
    (Champion ⊆ Finalists ⊆ SF ⊆ QF ⊆ R16), size caps. When the generating
    structure is complete (12 group orders + 8 thirds) the official FIFA R32
    (matches 73-88 + Annex C thirds allocation) is rebuilt and picks outside it
    — or two picks on the same bracket path — are rejected. Partial/absent
    structure → set-level checks only.
    """
    import re as _re
    def tier(k):
        if k == "Champion": return "C"
        if _re.match(r"^F-\d+$", k or ""): return "F"
        if _re.match(r"^SF-\d+$", k or ""): return "SF"
        if _re.match(r"^QF-\d+$", k or ""): return "QF"
        if _re.match(r"^R16-\d+$", k or ""): return "R16"
        return None
    order = ["R16", "QF", "SF", "F", "C"]
    mx = {"R16": 16, "QF": 8, "SF": 4, "F": 2, "C": 1}
    name = {"R16": "Round-of-16", "QF": "quarter-final", "SF": "semi-final", "F": "finalist", "C": "champion"}
    sets = {t: set() for t in order}
    go, thirds = {}, None
    for p in picks or []:
        if not p:
            continue
        k = p.get("bracket_slot") or p.get("key")
        if p.get("type") == "bracket_slot":
            t = tier(k)
            if not t:
                raise RuntimeError(f"unknown bracket slot '{k}'")
            if p.get("team_id") in (None, ""):
                continue
            tid = str(int(p["team_id"]))
            if tid in sets[t]:
                raise RuntimeError(f"duplicate team in your {name[t]} round")
            sets[t].add(tid)
        elif p.get("type") == "bracket_struct":
            m = _re.match(r"^group_order\|([A-L])$", k or "")
            if m:
                codes = [c.strip() for c in str(p.get("player_text") or "").split(",") if c.strip()]
                if len(codes) != 3 or len(set(codes)) != 3:
                    raise RuntimeError(f"group_order|{m.group(1)} needs exactly 3 distinct team codes")
                for c in codes:
                    t = teams_by_code.get(c)
                    if not t:
                        raise RuntimeError(f"unknown team code '{c}' in group_order|{m.group(1)}")
                    if t["group"] != m.group(1):
                        raise RuntimeError(f"{c} is not in group {m.group(1)}")
                go[m.group(1)] = [str(teams_by_code[c]["team_id"]) for c in codes]
            elif k == "thirds_advance":
                ls = [s.strip() for s in str(p.get("player_text") or "").split(",") if s.strip()]
                if len(ls) > 8 or len(set(ls)) != len(ls) or any(not _re.match(r"^[A-L]$", l) for l in ls):
                    raise RuntimeError("thirds_advance must be up to 8 distinct group letters A–L")
                thirds = ls
            else:
                raise RuntimeError(f"unknown bracket_struct key '{k}'")
    for t in order:
        if len(sets[t]) > mx[t]:
            raise RuntimeError(f"too many {name[t]} picks ({len(sets[t])}/{mx[t]})")
    for i in range(len(order) - 1, 0, -1):
        for tid in sets[order[i]]:
            if tid not in sets[order[i - 1]]:
                raise RuntimeError(f"bracket not nested: a {name[order[i]]} pick is missing from your {name[order[i - 1]]} round")
    complete = all(g in go for g in "ABCDEFGHIJKL") and thirds is not None and len(thirds) == 8
    if not complete:
        return
    # official FIFA 2026 R32 (matches 73-88) + Annex C third-place allocation
    # (mirrors site/index.html buildR32; canonical table: data/thirds_alloc_2026.json)
    al = WC26_ALLOC.get("".join(sorted(thirds)))
    if not al:
        raise RuntimeError("thirds_advance is not a valid 8-group combination")
    tof = dict(zip("ABDEGIKL", al))
    W = lambda l: go[l][0]
    RU = lambda l: go[l][1]
    TH = lambda l: go[tof[l]][2]
    ms = [
        [RU("A"), RU("B")], [W("E"), TH("E")], [W("F"), RU("C")], [W("C"), RU("F")],
        [W("I"), TH("I")], [RU("E"), RU("I")], [W("A"), TH("A")], [W("L"), TH("L")],
        [W("D"), TH("D")], [W("G"), TH("G")], [RU("K"), RU("L")], [W("H"), RU("J")],
        [W("B"), TH("B")], [W("J"), RU("H")], [W("K"), TH("K")], [RU("D"), RU("G")],
    ]
    m32 = {}
    for i, pair in enumerate(ms):
        for tid in pair:
            m32[tid] = i + 1
    for tid in sets["R16"]:
        if tid not in m32:
            raise RuntimeError("an R16 pick is not among your 32 qualifiers")
    for ti, t in enumerate(order):
        seen = set()
        for tid in sets[t]:
            idx = m32[tid]
            for i in range(1, ti + 1):
                idx = WC26_PARENT[i][idx]
            if idx in seen:
                raise RuntimeError(f"two {name[t]} picks sit on the same bracket path — only one side of a tie can advance")
            seen.add(idx)

def save(player, picks):
    prow = get_player(player)
    if not prow:
        raise RuntimeError(f"player '{player}' not found in PoolPlayers (run create_base.py seed)")
    player_rec = prow["id"]
    team_map, teams_by_code = {}, {}
    for r in at_list("Teams", fields=["team_id", "code", "group"]):
        f = r["fields"]
        if f.get("team_id") is None:
            continue
        team_map[int(f["team_id"])] = r["id"]
        if f.get("code"):
            teams_by_code[f["code"]] = {"team_id": f["team_id"], "group": f.get("group")}
    bracket_guard(picks, teams_by_code)   # rejects before anything is written
    sg_map = {r["fields"].get("name"): r["id"] for r in at_list("SideGames", fields=["name"])}
    foot_map = {int(r["fields"]["player_id"]): r["id"]
                for r in at_list("Footballers", fields=["player_id"]) if r["fields"].get("player_id") is not None}
    match_map = {int(r["fields"]["fixture_id"]): r["id"]
                 for r in at_list("Matches", fields=["fixture_id"]) if r["fields"].get("fixture_id") is not None}
    records = [prediction_fields(player, p, team_map, player_rec, sg_map, foot_map, match_map) for p in picks if p.get("key")]
    n = at_upsert("Predictions", records, ["label"]) if records else 0
    # bracket rows are full-replace: the tree regenerates the complete set every save,
    # so the player's bracket rows absent from this payload were cleared client-side
    bracket_types = {"bracket_slot", "bracket_struct"}
    keep = {f"{player}|{p['key']}" for p in picks if p.get("key") and p.get("type") in bracket_types}
    all_preds = at_list("Predictions", fields=["label", "prediction_type", "confidence_token"])
    doomed = [r["id"] for r in all_preds
              if r.get("fields", {}).get("label", "").startswith(player + "|")
              and r["fields"].get("prediction_type") in bracket_types
              and r["fields"].get("label") not in keep]
    deleted = at_delete("Predictions", doomed) if doomed else 0
    used = token_counts(picks)
    # bonus bets live outside this payload (saved via /api/savebonus) but share the budget
    for r in all_preds:
        f = r.get("fields", {})
        if (f.get("label", "").startswith(player + "|") and f.get("prediction_type") == "bonus_bet"
                and f.get("confidence_token") in used):
            used[f["confidence_token"]] += 1
    at("PATCH", f"{BASE}/PoolPlayers", {"records": [{"id": player_rec, "fields": {
        "tokens_remaining_double": START_TOKENS["Double"] - used["Double"],
        "tokens_remaining_triple": START_TOKENS["Triple"] - used["Triple"],
        "tokens_remaining_allin": START_TOKENS["AllIn"] - used["AllIn"]}}]})
    return {"saved": n, "deleted": deleted, "tokensUsed": used}

def at_delete(table, ids):
    n = 0
    for i in range(0, len(ids), 10):
        qs = "&".join("records[]=" + urllib.parse.quote(rid) for rid in ids[i:i + 10])
        at("DELETE", f"{BASE}/{urllib.parse.quote(table)}?{qs}")
        time.sleep(0.2)
        n += len(ids[i:i + 10])
    return n

def save_bonus(player, picks):
    """Per-match bonus bets (mirrors the Pages Function): open after tournament lock,
    gated per match by kickoff, full-replace for not-yet-started matches, shared
    token budget enforced across ALL of the player's predictions."""
    import re as _re
    prow = get_player(player)
    if not prow:
        raise RuntimeError(f"player '{player}' not found in PoolPlayers")
    player_rec = prow["id"]
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    match_map, kickoff_of, status_of = {}, {}, {}
    for r in at_list("Matches", fields=["fixture_id", "kickoff_utc", "status"]):
        f = r.get("fields", {})
        if f.get("fixture_id") is None:
            continue
        fid = int(f["fixture_id"])
        match_map[fid] = r["id"]
        kickoff_of[fid] = f.get("kickoff_utc") or ""
        status_of[fid] = f.get("status") or "Scheduled"

    def started(fid):
        return (status_of.get(fid) and status_of[fid] != "Scheduled") or \
               (kickoff_of.get(fid) and kickoff_of[fid] <= now)

    by_slot = {}
    for p in picks or []:
        if not p or not p.get("key"):
            continue
        m = _re.match(r"^bonus\|(\d+)\|([12])$", p["key"])
        if not m:
            raise RuntimeError(f"bad bonus key '{p['key']}'")
        fid = int(m.group(1))
        if fid not in match_map:
            raise RuntimeError(f"unknown match {fid}")
        if started(fid):
            raise RuntimeError(f"match {fid} has already kicked off — bonus bets are locked")
        if p.get("bet_type") not in BONUS_TYPES:
            raise RuntimeError(f"bad bet type '{p.get('bet_type')}'")
        if p.get("bet_value") not in ("Yes", "No"):
            raise RuntimeError(f"bad bet value '{p.get('bet_value')}'")
        by_slot[p["key"]] = {"key": p["key"], "type": "bonus_bet", "match_id": fid,
                             "bet_type": p["bet_type"], "bet_value": p["bet_value"],
                             "token": p.get("token"), "pundit_note": p.get("pundit_note")}
    new_picks = list(by_slot.values())

    rec2fid = {rid: fid for fid, rid in match_map.items()}
    mine = [r for r in at_list("Predictions", fields=["label", "prediction_type", "confidence_token", "match"])
            if r.get("fields", {}).get("label", "").startswith(player + "|")]
    future_rows, locked_tokens = [], {"Double": 0, "Triple": 0, "AllIn": 0}
    for r in mine:
        f = r.get("fields", {})
        is_bonus = f.get("prediction_type") == "bonus_bet"
        fid = rec2fid.get((f.get("match") or [None])[0]) if is_bonus else None
        if is_bonus and fid is not None and not started(fid):
            future_rows.append(r)
            continue
        if f.get("confidence_token") in locked_tokens:
            locked_tokens[f["confidence_token"]] += 1

    used = dict(locked_tokens)
    for p in new_picks:
        if p.get("token") in used:
            used[p["token"]] += 1
    for t, mx in START_TOKENS.items():
        if used[t] > mx:
            raise RuntimeError(f"token budget exceeded: {used[t]}×{t} placed, {mx} available")

    keep = {f"{player}|{p['key']}" for p in new_picks}
    doomed = [r["id"] for r in future_rows if r.get("fields", {}).get("label") not in keep]
    deleted = at_delete("Predictions", doomed) if doomed else 0
    records = [prediction_fields(player, p, {}, player_rec, {}, {}, match_map) for p in new_picks]
    saved = at_upsert("Predictions", records, ["label"]) if records else 0

    at("PATCH", f"{BASE}/PoolPlayers", {"records": [{"id": player_rec, "fields": {
        "tokens_remaining_double": START_TOKENS["Double"] - used["Double"],
        "tokens_remaining_triple": START_TOKENS["Triple"] - used["Triple"],
        "tokens_remaining_allin": START_TOKENS["AllIn"] - used["AllIn"]}}]})
    return {"saved": saved, "deleted": deleted, "tokensUsed": used}

def lock(player):
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    ids = [r["id"] for r in at_list("Predictions", fields=["label"])
           if r["fields"].get("label", "").startswith(player + "|")]
    for i in range(0, len(ids), 10):
        at("PATCH", f"{BASE}/Predictions",
           {"records": [{"id": rid, "fields": {"locked_at": now}} for rid in ids[i:i + 10]]})
        time.sleep(0.2)
    return {"locked": len(ids), "at": now}

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not SITE.exists():
                return self._send(500, {"error": "site/index.html missing"})
            return self._send(200, SITE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/bootstrap":
            player = (urllib.parse.parse_qs(u.query).get("player") or ["Andreas"])[0]
            try:
                return self._send(200, bootstrap(player))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or "{}") if length else {}
        try:
            if u.path == "/api/save":
                return self._send(200, save(body["player"], body.get("picks", [])))
            if u.path == "/api/savebonus":
                return self._send(200, save_bonus(body["player"], body.get("picks", [])))
            if u.path == "/api/lock":
                return self._send(200, lock(body["player"]))
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

def main():
    global PAT, BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    PAT, BASE = load_keys()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Pick-entry server running →  http://127.0.0.1:{args.port}")
    print("Open it in your browser. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")

if __name__ == "__main__":
    main()
