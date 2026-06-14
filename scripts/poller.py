#!/usr/bin/env python3
"""
poller.py — World Cup 2026 live data poller.

Two modes:
  scoreboard   (default) — upsert today's fixtures into Matches (scores, status, round,
                team links, winner), fetch events_json for live/finished matches, log to PollLog.
  leaderboards — upsert group Standings from the API.

Runs in GitHub Actions (reads keys from env / repo secrets) or locally (falls back to ../.env.local).
Keyed writes use Airtable's native upsert (fieldsToMergeOn), so it is safe to run every 15 minutes.

    python3 scripts/poller.py --mode scoreboard
    python3 scripts/poller.py --mode scoreboard --date 2026-06-11 --dry-run
    python3 scripts/poller.py --mode leaderboards

Stdlib only. Schema per 02_Airtable_schema.md (events stored as JSON in Matches).
"""
import argparse, json, os, re, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://v3.football.api-sports.io"
REST = "https://api.airtable.com/v0"
LEAGUE, SEASON = 1, 2026
TOURN_START, TOURN_END = dt.date(2026, 6, 11), dt.date(2026, 7, 19)
WRITE_PAUSE = 0.22

# API-Football status.short -> our Matches.status single-select
LIVE_CODES = {"1H", "HT", "2H", "ET", "BT", "P", "INT", "LIVE"}
DONE_CODES = {"FT", "AET", "PEN"}
PEND_CODES = {"NS", "TBD"}
METHOD = {"FT": "Regulation", "AET": "Extra Time", "PEN": "Penalties"}

def status_of(short):
    if short in DONE_CODES: return "Finished"
    if short in LIVE_CODES: return "Live"
    if short in PEND_CODES: return "Scheduled"
    return "Postponed"

def should_fetch_events(short, prev_status, has_events):
    """Whether to (re)fetch a fixture's events this poll.

    Always while Live (keeps the feed current). For a finished match, fetch when
    we have nothing stored yet, OR when the prior poll still had it Live — that
    Live→Finished transition is the one poll that captures goals scored in the
    final minutes after the last Live snapshot (cadence is 15 min, so a late goal
    would otherwise never be backfilled and would undercount Top Scorer / Golden
    Boot). Once stored against a Finished status, we stop (no wasted calls)."""
    if short in LIVE_CODES:
        return True
    if short in DONE_CODES:
        return (not has_events) or (prev_status != "Finished")
    return False

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
        q["fields[]"] = fields  # urlencode with doseq
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
    """Airtable native upsert in batches of 10."""
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

def at_delete(base, table, pat, rec_ids, dry=False):
    """Delete records by id in batches of 10."""
    n = 0
    for i in range(0, len(rec_ids), 10):
        batch = rec_ids[i:i + 10]
        if dry:
            n += len(batch); continue
        q = urllib.parse.urlencode([("records[]", rid) for rid in batch])
        at_request("DELETE", f"{base}/{urllib.parse.quote(table)}?{q}", pat)
        time.sleep(WRITE_PAUSE)
        n += len(batch)
    return n

def at_create(base, table, pat, fields, dry=False):
    if dry:
        return
    at_request("POST", f"{base}/{urllib.parse.quote(table)}", pat, {"records": [{"fields": fields}], "typecast": True})
    time.sleep(WRITE_PAUSE)

# ---- transforms (pure — unit-tested) ---------------------------------------
def to_match_fields(fx, team_map, now_iso):
    """Map one API-Football fixture object to a Matches record's fields dict."""
    f = fx["fixture"]; tms = fx["teams"]; goals = fx.get("goals", {})
    short = (f.get("status") or {}).get("short", "NS")
    home, away = tms["home"], tms["away"]
    venue = (f.get("venue") or {})
    rec = {
        "fixture_id": f["id"],
        "label": f"{home.get('name','?')} v {away.get('name','?')}",
        "kickoff_utc": f.get("date"),
        "round": (fx.get("league") or {}).get("round"),
        "status": status_of(short),
        "last_polled_at": now_iso,
    }
    vname = venue.get("name")
    if vname:
        rec["venue"] = vname + (f", {venue.get('city')}" if venue.get("city") else "")
    if goals.get("home") is not None:
        rec["home_score"] = goals["home"]
    if goals.get("away") is not None:
        rec["away_score"] = goals["away"]
    # team links (only if we know the Airtable record id)
    if home.get("id") in team_map:
        rec["home_team"] = [team_map[home["id"]]]
    if away.get("id") in team_map:
        rec["away_team"] = [team_map[away["id"]]]
    # winner link + method (knockouts always have a winner; group draws don't)
    if short in DONE_CODES:
        rec["winner_method"] = METHOD.get(short, "Regulation")
        win_id = home["id"] if home.get("winner") else away["id"] if away.get("winner") else None
        if win_id in team_map:
            rec["winner"] = [team_map[win_id]]
    return {k: v for k, v in rec.items() if v is not None}

def norm_group(gname):
    """Normalize API-Football's standings group naming to a stable key.

    The feed renamed its tables when play started ("Group A" pre-tournament →
    "Group Stage - A" on matchday 1), which orphaned every label-keyed row and
    duplicated the tables on the live board (seen 2026-06-12). Reduce any
    variant ending in the group letter to "A".."L", map the third-place
    ranking to "3rd" (it drives R32 qualification), and return None for
    anything else (aggregate tables we don't track).
    """
    g = (gname or "").strip()
    if "third" in g.lower():
        return "3rd"
    m = re.search(r"\b([A-L])$", g)
    return m.group(1) if m else None

def to_standing_fields(row, group_key, team_map):
    """group_key is the normalized key from norm_group() — never the raw API string,
    so the upsert label survives any future API renaming."""
    tid = row["team"]["id"]
    rec = {
        "label": f"{group_key}:{tid}",
        "group": group_key,
        "rank": row.get("rank"),
        "played": (row.get("all") or {}).get("played"),
        "win": (row.get("all") or {}).get("win"),
        "draw": (row.get("all") or {}).get("draw"),
        "loss": (row.get("all") or {}).get("lose"),
        "goals_for": ((row.get("all") or {}).get("goals") or {}).get("for"),
        "goals_against": ((row.get("all") or {}).get("goals") or {}).get("against"),
        "goal_diff": row.get("goalsDiff"),
        "points": row.get("points"),
        "form": row.get("form"),
    }
    if tid in team_map:
        rec["team"] = [team_map[tid]]
    return {k: v for k, v in rec.items() if v is not None}

def poll_dates(utc_today, target_date=None):
    """UTC dates to query in one scoreboard run.

    The API buckets each fixture under its kickoff's UTC date, and a single-date
    query drops a match the instant the UTC day rolls over — so a game still in
    progress at 00:00 UTC freezes at its last-seen Live minute and never records
    full time (seen 2026-06-13: BRA v MAR, 22:00 UTC kickoff, stuck at 81'). The
    automated run therefore polls yesterday AND today; re-touching yesterday's
    now-final fixtures is harmless (idempotent upsert keyed on fixture_id, events
    already stored). An explicit --date polls only that one day, for backfills.
    """
    if target_date:
        return [target_date]
    return [utc_today - dt.timedelta(days=1), utc_today]

# ---- shared ----------------------------------------------------------------
def build_team_map(base, pat):
    """team_id (API-Football) -> Airtable record id, from the seeded Teams table."""
    m = {}
    for rec in at_list(base, "Teams", pat, fields=["team_id"]):
        tid = rec.get("fields", {}).get("team_id")
        if tid is not None:
            m[int(tid)] = rec["id"]
    return m

def write_poll_log(base, pat, workflow, calls, remaining, touched, errors, dry):
    fields = {
        "run_label": f"{workflow} {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "run_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "workflow": workflow,
        "calls_made": calls,
        "fixtures_touched": touched,
    }
    if remaining is not None:
        try: fields["rate_limit_remaining"] = int(remaining)
        except (TypeError, ValueError): pass
    if errors:
        fields["errors"] = errors[:9000]
    at_create(base, "PollLog", pat, fields, dry=dry)

# ---- modes -----------------------------------------------------------------
def run_scoreboard(keys, target_date, dry, force):
    base, pat, key = keys["AIRTABLE_BASE_ID"], keys["AIRTABLE_PAT"], keys["API_FOOTBALL_KEY"]
    utc_today = dt.datetime.utcnow().date()
    today = target_date or utc_today
    if not force and not (TOURN_START - dt.timedelta(days=3) <= today <= TOURN_END + dt.timedelta(days=2)):
        print(f"· {today} is outside the tournament window — skipping (use --force to override)."); return
    calls = 0; errors = []
    remaining = None
    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    team_map = build_team_map(base, pat)
    print(f"· team map: {len(team_map)} teams")

    # Poll yesterday+today (UTC) on the automated run so a match still live at the
    # UTC date rollover still gets its final status — see poll_dates() for the why.
    by_fid = {}
    for d in poll_dates(utc_today, target_date):
        fx_body, remaining = api_get("fixtures", key, league=LEAGUE, season=SEASON, date=d.isoformat())
        calls += 1
        day_fx = fx_body.get("response", [])
        print(f"· {d}: {len(day_fx)} fixtures")
        if fx_body.get("errors"):
            errors.append(f"fixtures errors ({d}): {fx_body['errors']}")
        for fx in day_fx:                  # date buckets are disjoint; dedupe defensively
            by_fid[fx["fixture"]["id"]] = fx
    fixtures = list(by_fid.values())

    # Prior state per fixture — read BEFORE the upsert flips statuses to "Finished",
    # so should_fetch_events() can see the Live→Finished transition and grab the
    # final-minutes events. (status, whether events_json is already stored.)
    prev_status, have_events = {}, set()
    if not dry:
        for rec in at_list(base, "Matches", pat, fields=["fixture_id", "status", "events_json"]):
            fl = rec.get("fields", {})
            fid = fl.get("fixture_id")
            prev_status[fid] = fl.get("status")
            if fl.get("events_json"):
                have_events.add(fid)

    records = [to_match_fields(fx, team_map, now_iso) for fx in fixtures]
    touched = at_upsert(base, "Matches", pat, records, ["fixture_id"], dry=dry) if records else 0
    print(f"· upserted {touched} Matches{' (dry)' if dry else ''}")

    # Live minute → Matches.elapsed, as a SEPARATE tolerant upsert so a missing field
    # (must be added in the Airtable UI: Number field named "elapsed") can never break
    # the main score write.
    el_records = [{"fixture_id": fx["fixture"]["id"],
                   "elapsed": (fx["fixture"].get("status") or {}).get("elapsed")}
                  for fx in fixtures
                  if (fx["fixture"].get("status") or {}).get("elapsed") is not None]
    if el_records:
        try:
            at_upsert(base, "Matches", pat, el_records, ["fixture_id"], dry=dry)
            print(f"· live minute written for {len(el_records)} fixture(s)")
        except RuntimeError as e:
            if "UNKNOWN_FIELD" in str(e).upper() or "elapsed" in str(e):
                print("  ⚠ Matches.elapsed missing — add a Number field named 'elapsed' in "
                      "Airtable to get live minutes on match cards (scores unaffected)")
            else:
                errors.append(str(e))

    ev_records = []
    for fx in fixtures:
        fid = fx["fixture"]["id"]
        short = (fx["fixture"].get("status") or {}).get("short", "NS")
        if should_fetch_events(short, prev_status.get(fid), fid in have_events):
            try:
                ev_body, remaining = api_get("fixtures/events", key, fixture=fid); calls += 1
                ev_records.append({"fixture_id": fid, "events_json": json.dumps(ev_body.get("response", []))})
            except RuntimeError as e:
                errors.append(str(e))
    if ev_records:
        at_upsert(base, "Matches", pat, ev_records, ["fixture_id"], dry=dry)
    print(f"· events fetched for {len(ev_records)} fixtures")

    write_poll_log(base, pat, "scoreboard-poll", calls, remaining, touched, " | ".join(errors), dry)
    print(f"· done. api calls: {calls}, rate-limit remaining: {remaining}")

def run_leaderboards(keys, dry, force):
    base, pat, key = keys["AIRTABLE_BASE_ID"], keys["AIRTABLE_PAT"], keys["API_FOOTBALL_KEY"]
    today = dt.datetime.utcnow().date()
    if not force and not (TOURN_START - dt.timedelta(days=3) <= today <= TOURN_END + dt.timedelta(days=2)):
        print(f"· {today} outside tournament window — skipping (use --force)."); return
    calls = 0; errors = []
    team_map = build_team_map(base, pat)
    body, remaining = api_get("standings", key, league=LEAGUE, season=SEASON); calls += 1
    resp = body.get("response", [])
    groups = (resp[0]["league"]["standings"] if resp else [])
    records = []; skipped = set()
    for table in groups:                       # each group is a list of rows
        for row in table:
            g = norm_group(row.get("group"))
            if g is None:                      # aggregate tables we don't track
                skipped.add(row.get("group") or "?"); continue
            records.append(to_standing_fields(row, g, team_map))
    if skipped:
        print(f"· skipped API tables: {sorted(skipped)}")
    touched = at_upsert(base, "Standings", pat, records, ["label"], dry=dry) if records else 0
    print(f"· upserted {touched} Standings rows{' (dry)' if dry else ''}")
    # Self-heal: prune rows whose label the API no longer publishes (e.g. after the
    # group-name rename above). Guarded so an empty API response never wipes the table.
    if records:
        keep = {r["label"] for r in records}
        stale = [rec["id"] for rec in at_list(base, "Standings", pat, fields=["label"])
                 if (rec.get("fields", {}).get("label") or "") not in keep]
        if stale:
            pruned = at_delete(base, "Standings", pat, stale, dry=dry)
            print(f"· pruned {pruned} stale Standings rows{' (dry)' if dry else ''}")
    write_poll_log(base, pat, "leaderboards-poll", calls, remaining, touched, " | ".join(errors), dry)
    print(f"· done. api calls: {calls}, rate-limit remaining: {remaining}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["scoreboard", "leaderboards"], default="scoreboard")
    ap.add_argument("--date", help="override date YYYY-MM-DD (scoreboard only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore the tournament-window guard")
    args = ap.parse_args()
    keys = load_keys()
    target = dt.date.fromisoformat(args.date) if args.date else None
    print(f"poller · mode={args.mode}{' · DRY RUN' if args.dry_run else ''}")
    if args.mode == "scoreboard":
        run_scoreboard(keys, target, args.dry_run, args.force)
    else:
        run_leaderboards(keys, args.dry_run, args.force)

if __name__ == "__main__":
    main()
