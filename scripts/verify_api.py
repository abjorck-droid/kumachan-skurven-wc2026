#!/usr/bin/env python3
"""
verify_api.py — read-only API-Football spike for the World Cup 2026 bracket tool.

Run this ON YOUR MAC (it needs internet + the keys in ../.env.local).
It authenticates, confirms World Cup 2026 coverage, and resolves the open
uncertainties from 01_API_findings.md. Nothing is written to Airtable.

    cd ~/Desktop/WorldCup2026
    python3 scripts/verify_api.py

Stdlib only — no pip installs required.
"""
import json, os, sys, urllib.request, urllib.error, urllib.parse
from pathlib import Path

API_HOST = "https://v3.football.api-sports.io"
LEAGUE, SEASON = 1, 2026
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---- key loading (never printed) -------------------------------------------
def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env.local"
    if not env_path.exists():
        sys.exit(f"✗ {env_path} not found. Create it with API_FOOTBALL_KEY=...")
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    key = env.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("✗ API_FOOTBALL_KEY missing from .env.local")
    return key

# ---- HTTP ------------------------------------------------------------------
def call(path, key, **params):
    url = f"{API_HOST}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode())
            hdr = {k.lower(): v for k, v in r.headers.items()}
            return body, hdr
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ HTTP {e.code} on /{path} — {e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        sys.exit(f"✗ Network error on /{path}: {e.reason}")

def show_quota(hdr):
    day_lim = hdr.get("x-ratelimit-requests-limit", "?")
    day_rem = hdr.get("x-ratelimit-requests-remaining", "?")
    min_lim = hdr.get("x-ratelimit-limit", "?")
    print(f"    [quota] day: {day_rem}/{day_lim} remaining · per-min cap: {min_lim}")

def api_errors(body):
    errs = body.get("errors")
    if errs and (errs if isinstance(errs, list) else list(errs.values())):
        print(f"    ⚠ API reported errors: {errs}")
        return True
    return False

# ---- main ------------------------------------------------------------------
def main():
    key = load_env()
    DATA_DIR.mkdir(exist_ok=True)
    print("World Cup 2026 — API-Football verification\n" + "=" * 48)

    # 1. STATUS (does not count against daily quota)
    print("\n1) AUTH / ACCOUNT  ……………………………………………")
    body, _ = call("status", key)
    api_errors(body)
    resp = body.get("response", {})
    sub = resp.get("subscription", {})
    reqs = resp.get("requests", {})
    print(f"    ✓ key authenticates")
    print(f"    plan: {sub.get('plan','?')} · active: {sub.get('active','?')} · ends: {sub.get('end','?')}")
    print(f"    requests today: {reqs.get('current','?')}/{reqs.get('limit_day','?')}")

    # 2. LEAGUE / SEASON coverage
    print("\n2) WORLD CUP 2026 COVERAGE  ………………………………")
    body, hdr = call("leagues", key, id=LEAGUE, season=SEASON)
    show_quota(hdr)
    if body.get("response"):
        lg = body["response"][0]
        season = next((s for s in lg["league"].get("seasons", lg.get("seasons", []))
                       if s.get("year") == SEASON), None) if isinstance(lg, dict) else None
        cov = (season or {}).get("coverage", {})
        print(f"    ✓ {lg['league']['name']} — season {SEASON} present")
        print(f"    coverage: fixtures.events={cov.get('fixtures',{}).get('events')} "
              f"players={cov.get('players')} odds={cov.get('odds')} standings={cov.get('standings')}")
    else:
        print("    ⚠ season 2026 not returned — squads/fixtures may not be loaded yet")

    # 3. ROUND NAMES  (uncertainty #3 — the critical 'Round of 32' string)
    print("\n3) ROUND-NAME STRINGS  (Matches.round options)  ……")
    body, hdr = call("fixtures/rounds", key, league=LEAGUE, season=SEASON)
    show_quota(hdr)
    rounds = body.get("response", [])
    if rounds:
        for r in rounds:
            print(f"      • {r}")
        (DATA_DIR / "round_names_2026.json").write_text(json.dumps(rounds, indent=2))
        print(f"    ✓ {len(rounds)} rounds saved → data/round_names_2026.json")
        print("    → use these EXACT strings for the Matches.round single-select")
    else:
        print("    ⚠ no rounds yet (fixtures not published for the season)")

    # 4. TEAMS  (build the Teams table seed)
    print("\n4) TEAMS  ………………………………………………………………")
    body, hdr = call("teams", key, league=LEAGUE, season=SEASON)
    show_quota(hdr)
    teams = body.get("response", [])
    first_team_id = None
    if teams:
        first_team_id = teams[0]["team"]["id"]
        seed = [{"team_id": t["team"]["id"], "name": t["team"]["name"],
                 "code": t["team"].get("code")} for t in teams]
        (DATA_DIR / "teams_2026.json").write_text(json.dumps(seed, indent=2))
        print(f"    ✓ {len(teams)} teams (expect 48) saved → data/teams_2026.json")
        print(f"      sample: " + ", ".join(f"{t['code'] or '?'}={t['name']}" for t in seed[:6]))
    else:
        print("    ⚠ no teams returned yet")

    # 5. SQUAD / GK LABEL  (uncertainties #1 GK position, #4 squad timing)
    print("\n5) SQUAD + GK POSITION LABEL  ……………………………")
    if first_team_id:
        body, hdr = call("players/squads", key, team=first_team_id)
        show_quota(hdr)
        sq = body.get("response", [])
        players = sq[0].get("players", []) if sq else []
        if players:
            positions = sorted({p.get("position") for p in players if p.get("position")})
            gks = [p["name"] for p in players if p.get("position") in ("Goalkeeper", "G", "GK")]
            print(f"    ✓ squad populated ({len(players)} players for team {first_team_id})")
            print(f"      position labels seen: {positions}")
            print(f"      → Golden Glove logic keys off position == "
                  f"{'Goalkeeper' if 'Goalkeeper' in positions else positions[:1]}")
        else:
            print("    ⚠ squad not populated yet (announced ~June 4 — re-run if empty)")
    else:
        print("    – skipped (no team id)")

    # 6. ODDS COVERAGE  (uncertainty #5)
    print("\n6) PRE-MATCH ODDS COVERAGE  ……………………………")
    body, hdr = call("odds", key, league=LEAGUE, season=SEASON, page=1)
    show_quota(hdr)
    paging = body.get("paging", {})
    n = body.get("results", 0)
    print(f"    odds results: {n} (paging total pages: {paging.get('total','?')})")
    print("    ✓ odds available" if n else "    ⚠ no odds yet (typically appear closer to kickoff)")

    # Deferred: own-goal attribution (#2) needs a finished match — checked live.
    print("\n7) OWN-GOAL ATTRIBUTION  (uncertainty #2)  …………")
    print("    – deferred: requires a finished fixture. Live check path will be")
    print("      /fixtures/events → event.type=='Goal' & event.detail=='Own Goal'")

    print("\n" + "=" * 48)
    print("Done. Paste this output back to Claude to lock the schema's")
    print("round-name options and the Golden-Glove position key.")

if __name__ == "__main__":
    main()
