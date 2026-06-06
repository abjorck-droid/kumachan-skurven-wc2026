#!/usr/bin/env python3
"""
load_fixtures.py — one-time load of the full WC2026 schedule into the Matches table.

The poller only writes fixtures during the tournament window (and only for "today"),
so before kickoff the Matches table is empty. The pick-entry UI needs the 72 group
fixtures to exist so you and Cal can pick them. This pulls the whole season schedule
(/fixtures?league=1&season=2026) once and upserts on fixture_id.

    cd ~/Desktop/WorldCup2026
    python3 scripts/load_fixtures.py --dry-run    # report counts, write nothing
    python3 scripts/load_fixtures.py              # write for real

Re-runnable (upsert), so running it again later just refreshes kickoff times / venues /
round labels and fills in knockout fixtures once their pairings publish. Stdlib only;
reuses the poller's tested transforms (to_match_fields, build_team_map, Airtable client).
"""
import argparse, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poller as P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    keys = P.load_keys()
    base, pat, key = keys["AIRTABLE_BASE_ID"], keys["AIRTABLE_PAT"], keys["API_FOOTBALL_KEY"]

    print(f"load_fixtures{'  · DRY RUN' if args.dry_run else ''}")
    team_map = P.build_team_map(base, pat)
    print(f"· team map: {len(team_map)} teams")

    body, remaining = P.api_get("fixtures", key, league=P.LEAGUE, season=P.SEASON)
    fixtures = body.get("response", [])
    if body.get("errors") and (body["errors"] if isinstance(body["errors"], list) else list(body["errors"].values())):
        print(f"  ⚠ API errors: {body['errors']}")
    print(f"· {len(fixtures)} fixtures returned")
    if not fixtures:
        sys.exit("✗ no fixtures returned — the season schedule may not be published yet.")

    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    records = [P.to_match_fields(fx, team_map, now_iso) for fx in fixtures]

    # Report group vs knockout split + how many have both teams assigned.
    group_n = sum(1 for r in records if str(r.get("round", "")).lower().startswith("group"))
    linked = sum(1 for r in records if r.get("home_team") and r.get("away_team"))
    print(f"· group-stage fixtures: {group_n} · knockout/other: {len(records) - group_n}")
    print(f"· fixtures with both teams assigned: {linked} (knockouts stay unassigned until pairings publish)")

    n = P.at_upsert(base, "Matches", pat, records, ["fixture_id"], dry=args.dry_run) if records else 0
    print("—" * 40)
    print(f"· upserted {n} Matches{' (dry)' if args.dry_run else ''}")
    print(f"· done. api calls: 1, rate-limit remaining: {remaining}")


if __name__ == "__main__":
    main()
