#!/usr/bin/env python3
"""
resolve_sidegames.py — auto-fill SideGames.resolved_value from data already in Airtable.

Airtable-only (no API-Football key needed): everything derives from Matches.events_json
(stored by the poller), match scores/status, Teams.group, and Footballers names.

What it resolves, and when:
  First Red Card         — earliest red-card event (straight red or second yellow), once its
                           match is Finished AND every match kicking off at/before it is
                           Finished (VAR-safe; handles simultaneous kickoffs).
  First Own Goal         — same finality rule; first event with detail "Own Goal".
  Top Scorer Group A–L   — once all of that group's fixtures are Finished. Goals only —
                           own goals and missed penalties excluded. Ties → joint winners.
  Golden Boot            — once the Final is Finished. Most goals across the tournament;
                           tie-break: most assists (from goal events); still tied → joint.
                           (FIFA-style, per pool decision 2026-06-06.)
  Total Tournament Goals — once the Final is Finished AND every fixture is Finished.
                           Sum of full-time scores (extra time included, shootout kicks not).

NOT resolved here:
  Golden Glove — manual by pool decision (needs lineups; partly judged). Type it in Airtable.
  Dark Horse   — the scoring engine computes its ladder directly from the bracket.

Joint winners are written as "Name | Name"; the scoring engine treats each side of the
pipe as a winning answer. Player names are canonicalized through the Footballers table
(matched by API player id) so they string-match what the pick dropdowns saved.

Write-once: rows that already have a resolved_value are never overwritten (protects manual
entries like Golden Glove). Use --force to recompute.

    python3 scripts/resolve_sidegames.py --dry-run --verbose

Runs in GitHub Actions between the poller and the scoring engine, or locally. Stdlib only.
"""
import argparse, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.2
GROUPS = list("ABCDEFGHIJKL")
MATCHES_PER_GROUP = 6                      # 4 teams, round robin

# round-string → tier mapping lives in the scoring engine (incl. ROUND_TIER_OVERRIDES);
# import it so knockout round names only ever need fixing in one file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring_engine import round_tier      # noqa: E402

# ---- pure helpers (unit-tested, no I/O) -------------------------------------

def parse_events(match_rows):
    """match_rows: [{fixture_id, kickoff, status, events_json}] -> flat event list.
    Each event: {fixture_id, kickoff, status, elapsed, extra, type, detail, comments,
                 player_id, player_name, assist_id, assist_name, team_id}."""
    out = []
    for m in match_rows:
        raw = m.get("events_json")
        if not raw:
            continue
        try:
            events = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for ev in events or []:
            t = ev.get("time") or {}
            pl = ev.get("player") or {}
            asst = ev.get("assist") or {}
            tm = ev.get("team") or {}
            out.append({
                "fixture_id": m.get("fixture_id"), "kickoff": m.get("kickoff") or "",
                "status": m.get("status"),
                "elapsed": t.get("elapsed") or 0, "extra": t.get("extra") or 0,
                "type": ev.get("type") or "", "detail": ev.get("detail") or "",
                "comments": ev.get("comments") or "",
                "player_id": pl.get("id"), "player_name": pl.get("name"),
                "assist_id": asst.get("id"), "assist_name": asst.get("name"),
                "team_id": tm.get("id"),
            })
    return out


def event_order_key(ev):
    """Approximate real-time order across simultaneous kickoffs: kickoff, then match clock."""
    return (ev["kickoff"], ev["elapsed"] + ev["extra"] / 100.0)


def is_red_card(ev):
    return ev["type"].lower() == "card" and "red" in ev["detail"].lower()


def is_own_goal(ev):
    return ev["type"].lower() == "goal" and "own" in ev["detail"].lower()


def is_counting_goal(ev):
    """A goal credited to the scorer: not an own goal, miss, or shootout kick."""
    if ev["type"].lower() != "goal":
        return False
    d = ev["detail"].lower()
    if "own" in d or "missed" in d:
        return False
    if "shootout" in (ev["comments"] or "").lower():
        return False
    return True


def first_final_event(candidates, match_rows):
    """Earliest candidate that is FINAL: its match is Finished, and every match with
    kickoff <= its kickoff is Finished (an earlier/concurrent live match could still
    produce an earlier event; VAR can rescind events in live matches)."""
    if not candidates:
        return None
    first = sorted(candidates, key=event_order_key)[0]
    if first["status"] != "Finished":
        return None
    for m in match_rows:
        ko = m.get("kickoff") or ""
        if ko and ko <= first["kickoff"] and m.get("status") not in ("Finished", "Postponed"):
            return None
    return first


def goal_tallies(events, fixture_ids=None):
    """-> (goals{pid}, assists{pid}, names{pid}) from counting goals, optionally
    restricted to a set of fixtures. Assists credited from the goal's assist field."""
    goals, assists, names = {}, {}, {}
    for ev in events:
        if not is_counting_goal(ev):
            continue
        if fixture_ids is not None and ev["fixture_id"] not in fixture_ids:
            continue
        pid = ev["player_id"]
        if pid is not None:
            goals[pid] = goals.get(pid, 0) + 1
            names.setdefault(pid, ev["player_name"])
        aid = ev["assist_id"]
        if aid is not None:
            assists[aid] = assists.get(aid, 0) + 1
            names.setdefault(aid, ev["assist_name"])
    return goals, assists, names


def top_by_goals(goals, assists, fifa_tiebreak):
    """-> list of winning player ids. fifa_tiebreak: goals, then assists, then joint;
    otherwise plain joint on goals."""
    if not goals:
        return []
    best = max(goals.values())
    leaders = [p for p, g in goals.items() if g == best]
    if fifa_tiebreak and len(leaders) > 1:
        best_a = max(assists.get(p, 0) for p in leaders)
        leaders = [p for p in leaders if assists.get(p, 0) == best_a]
    return leaders


def joint_value(pids, canonical_names, event_names):
    """Render winners: canonical Footballers name (matches pick dropdowns), else
    the event feed's name. Joint winners joined with ' | ' (sorted, stable)."""
    names = [canonical_names.get(p) or event_names.get(p) or f"player {p}" for p in pids]
    return " | ".join(sorted(set(names)))


def group_fixture_ids(match_rows, group, team_group):
    """Fixture ids of a group's group-stage matches; team_group: team_id -> letter."""
    out = set()
    for m in match_rows:
        if round_tier(m.get("round")) != "group":
            continue
        g = team_group.get(m.get("home_id")) or team_group.get(m.get("away_id"))
        if g == group:
            out.add(m.get("fixture_id"))
    return out


def group_complete(match_rows, fixture_ids):
    """All of the group's known fixtures Finished — and the full slate is present."""
    if len(fixture_ids) < MATCHES_PER_GROUP:
        return False
    return all(m.get("status") == "Finished"
               for m in match_rows if m.get("fixture_id") in fixture_ids)


def final_is_done(match_rows):
    return any(round_tier(m.get("round")) == "Final" and m.get("status") == "Finished"
               for m in match_rows)


def total_goals(match_rows):
    """Sum of full-time scores once every fixture is Finished (or Postponed); else None."""
    tot = 0
    for m in match_rows:
        if m.get("status") == "Postponed":
            continue
        if m.get("status") != "Finished":
            return None
        hs, as_ = m.get("home_score"), m.get("away_score")
        if hs is None or as_ is None:
            return None
        tot += hs + as_
    return tot


def compute_resolutions(match_rows, events, team_group, canonical_names):
    """-> {side_game_name: resolved_value} for everything resolvable right now."""
    out = {}
    fdone = final_is_done(match_rows)

    red = first_final_event([e for e in events if is_red_card(e)], match_rows)
    if red and (red["player_id"] is not None or red["player_name"]):
        out["First Red Card"] = (canonical_names.get(red["player_id"])
                                 or red["player_name"] or f"player {red['player_id']}")
    og = first_final_event([e for e in events if is_own_goal(e)], match_rows)
    if og and (og["player_id"] is not None or og["player_name"]):
        out["First Own Goal"] = (canonical_names.get(og["player_id"])
                                 or og["player_name"] or f"player {og['player_id']}")

    for g in GROUPS:
        fids = group_fixture_ids(match_rows, g, team_group)
        if not group_complete(match_rows, fids):
            continue
        goals, assists, names = goal_tallies(events, fids)
        winners = top_by_goals(goals, assists, fifa_tiebreak=False)   # joint on ties
        if winners:
            out[f"Top Scorer Group {g}"] = joint_value(winners, canonical_names, names)

    if fdone:
        goals, assists, names = goal_tallies(events)                  # whole tournament
        winners = top_by_goals(goals, assists, fifa_tiebreak=True)    # goals → assists → joint
        if winners:
            out["Golden Boot"] = joint_value(winners, canonical_names, names)
        tg = total_goals(match_rows)
        if tg is not None:
            out["Total Tournament Goals"] = str(tg)

    return out

# ---- credentials + Airtable client (same pattern as poller/engine) ----------

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
        sys.exit("✗ AIRTABLE_PAT / AIRTABLE_BASE_ID missing from env / .env.local")
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

# ---- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="recompute rows that already have a resolved_value (normally write-once)")
    args = ap.parse_args()
    pat, base = load_keys()
    print(f"resolve_sidegames{'  · DRY RUN' if args.dry_run else ''}")

    teams = at_list(base, "Teams", pat, fields=["team_id", "group"])
    team_group = {}
    for r in teams:
        f = r.get("fields", {})
        if f.get("team_id") is not None and f.get("group"):
            team_group[f["team_id"]] = f["group"]

    rec2tid = {r["id"]: r.get("fields", {}).get("team_id") for r in teams}
    match_rows = []
    for r in at_list(base, "Matches", pat,
                     fields=["fixture_id", "round", "status", "kickoff_utc",
                             "home_team", "away_team", "home_score", "away_score", "events_json"]):
        f = r.get("fields", {})
        if f.get("fixture_id") is None:
            continue
        h = (f.get("home_team") or [None])[0]
        a = (f.get("away_team") or [None])[0]
        match_rows.append({
            "fixture_id": f["fixture_id"], "round": f.get("round"), "status": f.get("status"),
            "kickoff": f.get("kickoff_utc"), "home_id": rec2tid.get(h), "away_id": rec2tid.get(a),
            "home_score": f.get("home_score"), "away_score": f.get("away_score"),
            "events_json": f.get("events_json"),
        })

    canonical_names = {}
    for r in at_list(base, "Footballers", pat, fields=["player_id", "name"]):
        f = r.get("fields", {})
        if f.get("player_id") is not None and f.get("name"):
            canonical_names[f["player_id"]] = f["name"]

    events = parse_events(match_rows)
    proposals = compute_resolutions(match_rows, events, team_group, canonical_names)

    sgs = at_list(base, "SideGames", pat, fields=["name", "resolved_value"])
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    updates, skipped = [], []
    for r in sgs:
        f = r.get("fields", {})
        name = f.get("name")
        if name not in proposals:
            continue
        existing = (f.get("resolved_value") or "").strip()
        if existing and not args.force:
            if existing != proposals[name]:
                skipped.append(f"{name}: keeping '{existing}' (computed '{proposals[name]}'; --force to overwrite)")
            continue
        if existing == proposals[name]:
            continue
        updates.append({"id": r["id"], "fields": {"resolved_value": proposals[name], "resolved_at": now}})
        if args.verbose or args.dry_run:
            print(f"  · resolve {name!r} → {proposals[name]!r}")

    if args.verbose:
        unresolved = [r.get("fields", {}).get("name") for r in sgs
                      if not (r.get("fields", {}).get("resolved_value") or "").strip()
                      and r.get("fields", {}).get("name") not in proposals]
        for name in unresolved:
            print(f"  · pending  {name}")
    for s in skipped:
        print(f"  ⚠ {s}")

    n = at_update(base, "SideGames", pat, updates, dry=args.dry_run)
    print(f"· {n} side game(s) resolved{' (dry)' if args.dry_run else ''} · "
          f"{len(proposals)} computable · events seen: {len(events)}")


if __name__ == "__main__":
    main()
