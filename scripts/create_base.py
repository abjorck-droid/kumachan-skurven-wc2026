#!/usr/bin/env python3
"""
create_base.py — build the World Cup 2026 Airtable base from scratch.

Run this ON YOUR MAC (needs internet + AIRTABLE_PAT / AIRTABLE_BASE_ID in ../.env.local).
Talks ONLY to Airtable — does NOT need API-Football, so it can run before the Pro upgrade.

    cd ~/Desktop/WorldCup2026
    python3 scripts/create_base.py --dry-run     # preview, no changes
    python3 scripts/create_base.py               # create tables + seed reference rows
    python3 scripts/create_base.py --no-seed     # tables only, no seed records

Safe to re-run: it skips tables/fields/rows that already exist (idempotent).
Stdlib only — no pip installs. Schema follows 02_Airtable_schema.md
(events stored as JSON in Matches; a lightweight Standings table is included).
"""
import argparse, json, sys, time, uuid, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = "https://api.airtable.com/v0/meta/bases"
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.22  # stay under Airtable's 5 req/sec/base

# ---- env -------------------------------------------------------------------
def load_env():
    p = ROOT / ".env.local"
    if not p.exists():
        sys.exit(f"✗ {p} not found.")
    env = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    pat, base = env.get("AIRTABLE_PAT"), env.get("AIRTABLE_BASE_ID")
    if not pat or not base:
        sys.exit("✗ AIRTABLE_PAT and/or AIRTABLE_BASE_ID missing from .env.local")
    return pat, base

# ---- http ------------------------------------------------------------------
def http(method, url, pat, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {pat}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            payload = e.read().decode()
            if e.code == 429:                      # rate limited — back off
                time.sleep(1.5 * (attempt + 1)); continue
            raise RuntimeError(f"HTTP {e.code} {method} {url}\n   {payload[:300]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error {method} {url}: {e.reason}")
    raise RuntimeError(f"Gave up after retries: {method} {url}")

# ---- field builders --------------------------------------------------------
def text(n):      return {"name": n, "type": "singleLineText"}
def longtext(n):  return {"name": n, "type": "multilineText"}
def num(n):       return {"name": n, "type": "number", "options": {"precision": 0}}
def email(n):     return {"name": n, "type": "email"}
def check(n):     return {"name": n, "type": "checkbox", "options": {"color": "greenBright", "icon": "check"}}
def select(n, choices): return {"name": n, "type": "singleSelect",
                                "options": {"choices": [{"name": c} for c in choices]}}
def dt(n):        return {"name": n, "type": "dateTime",
                          "options": {"dateFormat": {"name": "iso"},
                                      "timeFormat": {"name": "24hour"}, "timeZone": "utc"}}
def link(n, target): return ("LINK", n, target)   # resolved to linkedTableId in pass 2

# ---- round-name options (self-configuring) ---------------------------------
KNOCKOUT = ["Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "3rd Place Final", "Final"]
def round_choices():
    f = ROOT / "data" / "round_names_2026.json"
    rounds = []
    if f.exists():
        try:
            rounds = [str(x) for x in json.loads(f.read_text())]
            print(f"  · round options loaded from data/round_names_2026.json ({len(rounds)})")
        except Exception:
            pass
    if not rounds:
        rounds = ["Group Stage - 1", "Group Stage - 2", "Group Stage - 3"]
        print("  · data/round_names_2026.json not found — using default round names "
              "(re-run verify_api.py on Pro, then re-run this to reconcile)")
    for k in KNOCKOUT:                              # ensure knockout stages always present
        if k not in rounds:
            rounds.append(k)
    return rounds

# ---- schema ----------------------------------------------------------------
GROUPS = list("ABCDEFGHIJKL")
def schema():
    return [
        {"name": "Teams", "fields": [
            text("name"), num("team_id"), text("code"), text("flag_emoji"),
            select("group", GROUPS), num("fifa_ranking"),
            select("eliminated_at_round", ["Group", "R32", "R16", "QF", "SF", "Final"]),
            text("kit_color_primary"), text("kit_color_secondary")]},
        {"name": "Footballers", "fields": [
            text("name"), num("player_id"),
            select("position", ["Goalkeeper", "Defender", "Midfielder", "Attacker"]),
            num("shirt_number"), num("goals_in_tournament"),
            num("assists_in_tournament"), num("clean_sheets_started"),
            link("team", "Teams")]},
        {"name": "Matches", "fields": [
            text("label"), num("fixture_id"), dt("kickoff_utc"), text("venue"),
            select("round", round_choices()),
            num("home_score"), num("away_score"),
            select("status", ["Scheduled", "Live", "Finished", "Postponed"]),
            select("winner_method", ["Regulation", "Extra Time", "Penalties"]),
            longtext("events_json"), dt("last_polled_at"),
            link("home_team", "Teams"), link("away_team", "Teams"), link("winner", "Teams")]},
        {"name": "PoolPlayers", "fields": [
            text("name"), text("display_color"), text("magic_link_token"),
            num("tokens_remaining_double"), num("tokens_remaining_triple"),
            num("tokens_remaining_allin"), num("mulligans_remaining"), num("total_score")]},
        {"name": "SideGames", "fields": [
            text("name"), longtext("description"),
            select("resolution_type", ["player", "team", "scalar", "event_player"]),
            dt("lock_at_utc"), text("resolved_value"), dt("resolved_at"),
            num("base_points"), longtext("dark_horse_ladder")]},
        {"name": "Predictions", "fields": [
            text("label"),
            select("prediction_type", ["match_outcome", "match_exact_score", "bracket_slot",
                                       "side_game", "bonus_bet", "dark_horse"]),
            text("bracket_slot"),
            select("predicted_outcome", ["Home", "Draw", "Away"]),
            num("predicted_score_home"), num("predicted_score_away"),
            num("predicted_scalar"), text("predicted_text"),
            select("bonus_bet_type", ["BTTS", "Over 2.5", "Under 2.5", "Penalty in match",
                                      "Red card in match", "Both teams score 2+", "Goal in first 15 min"]),
            select("bonus_bet_value", ["Yes", "No"]),
            select("confidence_token", ["Double", "Triple", "AllIn"]),
            longtext("pundit_note"), dt("locked_at"),
            num("points_awarded"), num("beat_rival_bonus"), check("resolved"),
            link("pool_player", "PoolPlayers"), link("match", "Matches"),
            link("side_game", "SideGames"), link("predicted_team", "Teams"),
            link("predicted_player", "Footballers")]},
        {"name": "Mulligans", "fields": [
            text("label"), dt("used_at"), longtext("note"),
            link("pool_player", "PoolPlayers"),
            link("original_prediction", "Predictions"), link("new_prediction", "Predictions")]},
        {"name": "Standings", "fields": [
            text("label"), select("group", GROUPS), num("rank"),
            num("played"), num("win"), num("draw"), num("loss"),
            num("goals_for"), num("goals_against"), num("goal_diff"),
            num("points"), text("form"), dt("updated_at"),
            link("team", "Teams")]},
        {"name": "PollLog", "fields": [
            text("run_label"), dt("run_at"),
            select("workflow", ["scoreboard-poll", "leaderboards-poll", "manual"]),
            num("calls_made"), num("rate_limit_remaining"),
            num("fixtures_touched"), longtext("errors")]},
    ]

# ---- seed data -------------------------------------------------------------
def seed_pool_players():
    return [
        {"name": "Andreas", "display_color": "#4ec9b0", "magic_link_token": str(uuid.uuid4()),
         "tokens_remaining_double": 4, "tokens_remaining_triple": 2, "tokens_remaining_allin": 1,
         "mulligans_remaining": 1, "total_score": 0},
        {"name": "Cal", "display_color": "#c586c0", "magic_link_token": str(uuid.uuid4()),
         "tokens_remaining_double": 4, "tokens_remaining_triple": 2, "tokens_remaining_allin": 1,
         "mulligans_remaining": 1, "total_score": 0},
    ]

def seed_side_games():
    dh = json.dumps({"R16": 25, "QF": 75, "SF": 200, "Final": 500, "Champion": 1000})
    rows = [
        {"name": "Golden Boot", "resolution_type": "player", "base_points": 60,
         "description": "Top scorer of the tournament."},
        {"name": "Golden Glove", "resolution_type": "player", "base_points": 60,
         "description": "Most clean sheets among GKs reaching at least the QF."},
        {"name": "First Red Card", "resolution_type": "event_player", "base_points": 30,
         "description": "Name the player shown the first red card of the tournament."},
        {"name": "First Own Goal", "resolution_type": "event_player", "base_points": 40,
         "description": "Name the player who scores the first own goal."},
        {"name": "Total Tournament Goals", "resolution_type": "scalar", "base_points": 30,
         "description": "Closest without going over."},
        {"name": "Dark Horse", "resolution_type": "team", "base_points": 0,
         "description": "Team ranked outside FIFA top 16 at lock. Escalating ladder payout.",
         "dark_horse_ladder": dh},
    ]
    for g in GROUPS:
        rows.append({"name": f"Top Scorer Group {g}", "resolution_type": "player",
                     "base_points": 15, "description": f"Top scorer of Group {g}."})
    return rows

def seed_teams():
    f = ROOT / "data" / "teams_2026.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except Exception:
        return None
    return [{"name": t["name"], "team_id": t["team_id"], "code": t.get("code") or ""} for t in data]

# ---- airtable ops ----------------------------------------------------------
def get_tables(pat, base):
    res = http("GET", f"{META}/{base}/tables", pat)
    return {t["name"]: {"id": t["id"], "fields": {f["name"] for f in t["fields"]}}
            for t in res.get("tables", [])}

def existing_record_names(pat, base, table):
    names, offset = set(), None
    while True:
        url = f"{REST}/{base}/{urllib.parse.quote(table)}?pageSize=100&fields%5B%5D=name"
        if offset:
            url += f"&offset={offset}"
        res = http("GET", url, pat)
        for rec in res.get("records", []):
            n = rec.get("fields", {}).get("name")
            if n:
                names.add(n)
        offset = res.get("offset")
        if not offset:
            return names

def create_records(pat, base, table, rows, name_field="name", dry=False):
    have = set() if dry else existing_record_names(pat, base, table)
    todo = [r for r in rows if r.get(name_field) not in have]
    if not todo:
        print(f"    · {table}: all {len(rows)} rows already present")
        return 0
    made = 0
    for i in range(0, len(todo), 10):                # batch up to 10/records call
        batch = todo[i:i + 10]
        if dry:
            print(f"    + would create {len(batch)} rows in {table}")
        else:
            http("POST", f"{REST}/{base}/{urllib.parse.quote(table)}",
                 pat, {"records": [{"fields": r} for r in batch], "typecast": True})
            time.sleep(WRITE_PAUSE)
        made += len(batch)
    print(f"    + {table}: {'(dry) ' if dry else ''}created {made} rows")
    return made

# ---- main ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview without making changes")
    ap.add_argument("--no-seed", action="store_true", help="create tables only, skip seed rows")
    args = ap.parse_args()
    pat, base = load_env()
    dry = args.dry_run

    print("World Cup 2026 — Airtable base builder\n" + "=" * 46)
    print(f"base: {base}" + ("   [DRY RUN — no changes]" if dry else ""))
    SCHEMA = schema()
    tables = get_tables(pat, base)
    print(f"existing tables in base: {sorted(tables) or '(none)'}\n")

    # PASS 1 — create tables with non-link fields
    print("PASS 1 · tables + scalar/select fields")
    for t in SCHEMA:
        if t["name"] in tables:
            print(f"    · {t['name']} exists — skip")
            continue
        plain = [f for f in t["fields"] if not (isinstance(f, tuple) and f[0] == "LINK")]
        if dry:
            print(f"    + would create table {t['name']} ({len(plain)} fields)")
            tables[t["name"]] = {"id": f"DRY_{t['name']}", "fields": {f['name'] for f in plain}}
        else:
            res = http("POST", f"{META}/{base}/tables", pat,
                       {"name": t["name"], "fields": plain})
            tables[t["name"]] = {"id": res["id"], "fields": {f["name"] for f in res["fields"]}}
            print(f"    + created {t['name']} ({len(plain)} fields)")
            time.sleep(WRITE_PAUSE)

    # PASS 2 — add linked-record fields (targets now exist)
    print("\nPASS 2 · linked-record fields")
    link_count = 0
    for t in SCHEMA:
        links = [f for f in t["fields"] if isinstance(f, tuple) and f[0] == "LINK"]
        for _, fname, target in links:
            if fname in tables[t["name"]]["fields"]:
                print(f"    · {t['name']}.{fname} exists — skip")
                continue
            tgt = tables.get(target, {}).get("id")
            if not tgt:
                print(f"    ! {t['name']}.{fname}: target {target} missing — skip"); continue
            body = {"name": fname, "type": "multipleRecordLinks",
                    "options": {"linkedTableId": tgt}}
            if dry:
                print(f"    + would add link {t['name']}.{fname} → {target}")
            else:
                http("POST", f"{META}/{base}/tables/{tables[t['name']]['id']}/fields", pat, body)
                print(f"    + {t['name']}.{fname} → {target}")
                time.sleep(WRITE_PAUSE)
            link_count += 1
    if not link_count:
        print("    · all link fields already present")

    # PASS 3 — seed reference rows
    if not args.no_seed:
        print("\nPASS 3 · seed reference data")
        create_records(pat, base, "PoolPlayers", seed_pool_players(), dry=dry)
        create_records(pat, base, "SideGames", seed_side_games(), dry=dry)
        teams = seed_teams()
        if teams:
            create_records(pat, base, "Teams", teams, dry=dry)
        else:
            print("    · Teams: data/teams_2026.json not found — seed after running verify_api.py on Pro")
    else:
        print("\nPASS 3 · skipped (--no-seed)")

    print("\n" + "=" * 46)
    print(("Dry run complete — re-run without --dry-run to apply."
           if dry else "Done. Open the base in Airtable to confirm."))
    if not (ROOT / "data" / "round_names_2026.json").exists():
        print("Reminder: once on Pro, run verify_api.py then re-run this script so the")
        print("Matches.round options match the real API round strings.")

if __name__ == "__main__":
    main()
