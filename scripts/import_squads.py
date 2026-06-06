#!/usr/bin/env python3
"""
import_squads.py — populate the Footballers table from API-Football squads.

Runs ON YOUR MAC (needs internet + ../.env.local) or in CI (env vars). For every
team in the seeded Teams table it calls /players/squads?team={id}, maps each player
to a Footballers record, and upserts on player_id (idempotent — safe to re-run as
squads firm up before kickoff).

    cd ~/Desktop/WorldCup2026
    python3 scripts/import_squads.py --dry-run     # show counts, write nothing
    python3 scripts/import_squads.py               # write for real
    python3 scripts/import_squads.py --team 26     # one team only (testing)

Stdlib only. Schema per 02_Airtable_schema.md (Footballers: player_id, name,
team→Teams, position G/D/M/F, shirt_number).

NOTE: FIFA squads publish ~1 week before kickoff. If a team returns 0 players, its
squad isn't in the feed yet — just re-run this closer to June 11. Upsert means the
re-run only adds/updates; nothing is duplicated.
"""
import argparse, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://v3.football.api-sports.io"
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.22
READ_PAUSE = 0.12  # polite gap between squad calls

# API-Football squad position label -> our Footballers.position single-select
POSITION_MAP = {"Goalkeeper": "G", "Defender": "D", "Midfielder": "M", "Attacker": "F"}

def map_position(label):
    """API squad position word -> single-letter code. Unknown/None -> None."""
    if not label:
        return None
    return POSITION_MAP.get(label.strip().title(), None)

# ---- credentials (env first for CI, then .env.local) -----------------------
def load_keys():
    keys = {k: os.environ.get(k) for k in ("API_FOOTBALL_KEY", "AIRTABLE_PAT", "AIRTABLE_BASE_ID")}
    p = ROOT / ".env.local"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if not keys.get(k.strip()):
                    keys[k.strip()] = v.strip()
    missing = [k for k, v in keys.items() if not v]
    if missing:
        sys.exit(f"✗ missing credentials: {', '.join(missing)}")
    return keys

# ---- http ------------------------------------------------------------------
def api_get(path, key, **params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode())
                rem = r.headers.get("x-ratelimit-requests-remaining")
                return body, rem
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1)); continue
            raise RuntimeError(f"API-Football HTTP {e.code} on /{path}: {e.read().decode()[:200]}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2); continue
            raise RuntimeError(f"API-Football network error on /{path}: {e.reason}")
    raise RuntimeError(f"API-Football retries exhausted: /{path}")

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
        path = f"{base}/{urllib.parse.quote(table)}?" + urllib.parse.urlencode(qq, doseq=True)
        res = at_request("GET", path, pat)
        out.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset:
            return out

def at_upsert(base, table, pat, records, merge_on, dry=False):
    n = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        if dry:
            n += len(batch); continue
        at_request("PATCH", f"{base}/{urllib.parse.quote(table)}", pat, {
            "performUpsert": {"fieldsToMergeOn": merge_on},
            "records": [{"fields": r} for r in batch],
            "typecast": True})
        time.sleep(WRITE_PAUSE)
        n += len(batch)
    return n

# ---- pure transform (unit-tested) ------------------------------------------
def squad_player_to_fields(p, team_rec_id):
    """Map one API-Football squad player object to a Footballers record's fields."""
    rec = {
        "player_id": p.get("id"),
        "name": p.get("name"),
        "team": [team_rec_id],
        "position": map_position(p.get("position")),
        "shirt_number": p.get("number"),
    }
    return {k: v for k, v in rec.items() if v is not None}

# ---- shared ----------------------------------------------------------------
def build_team_index(base, pat):
    """team_id (API-Football) -> {rec: airtable id, name: str}, from the seeded Teams table."""
    idx = {}
    for rec in at_list(base, "Teams", pat, fields=["team_id", "name", "code"]):
        f = rec.get("fields", {})
        tid = f.get("team_id")
        if tid is not None:
            idx[int(tid)] = {"rec": rec["id"], "name": f.get("name") or f.get("code") or str(tid)}
    return idx

# ---- main ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch + report, write nothing")
    ap.add_argument("--team", type=int, help="import a single API-Football team id (testing)")
    args = ap.parse_args()
    keys = load_keys()
    base, pat, key = keys["AIRTABLE_BASE_ID"], keys["AIRTABLE_PAT"], keys["API_FOOTBALL_KEY"]

    print(f"import_squads{'  · DRY RUN' if args.dry_run else ''}")
    team_idx = build_team_index(base, pat)
    print(f"· team index: {len(team_idx)} teams")
    if not team_idx:
        sys.exit("✗ Teams table is empty — run scripts/create_base.py first.")

    targets = [args.team] if args.team else sorted(team_idx.keys())
    calls = 0; remaining = None
    total_players = 0
    empty_teams = []
    all_records = []

    for tid in targets:
        info = team_idx.get(tid)
        if not info:
            print(f"  ⚠ team id {tid} not in Teams table — skipping"); continue
        body, remaining = api_get("players/squads", key, team=tid); calls += 1
        resp = body.get("response", [])
        players = resp[0].get("players", []) if resp else []
        if body.get("errors") and (body["errors"] if isinstance(body["errors"], list) else list(body["errors"].values())):
            print(f"  ⚠ {info['name']}: API errors {body['errors']}")
        recs = [squad_player_to_fields(p, info["rec"]) for p in players if p.get("id")]
        all_records.extend(recs)
        total_players += len(recs)
        if not recs:
            empty_teams.append(info["name"])
            print(f"  · {info['name']:<22} 0 players  (squad not published yet)")
        else:
            print(f"  · {info['name']:<22} {len(recs)} players")
        time.sleep(READ_PAUSE)

    written = at_upsert(base, "Footballers", pat, all_records, ["player_id"], dry=args.dry_run) if all_records else 0
    print("—" * 40)
    print(f"· upserted {written} footballers{' (dry)' if args.dry_run else ''} across {len(targets)} teams")
    if empty_teams:
        print(f"· {len(empty_teams)} team(s) had no squad yet: {', '.join(empty_teams[:8])}"
              + (" …" if len(empty_teams) > 8 else ""))
        print("  → re-run this closer to kickoff to fill them in (upsert = no duplicates).")
    print(f"· done. api calls: {calls}, rate-limit remaining: {remaining}")

if __name__ == "__main__":
    main()
