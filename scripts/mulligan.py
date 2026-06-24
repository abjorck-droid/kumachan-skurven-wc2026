#!/usr/bin/env python3
"""
mulligan.py — drive a single mulligan from the terminal (dry-run by default).

Reuses pickentry_server.save_mulligan against the live Airtable base, so the rules,
50% scoring, Dark-Horse eligibility, write order, and one-per-player budget are IDENTICAL
to the web entry path — this is just a keyboard front-end to the same function.

    cd ~/Desktop/WorldCup2026

    # 1) see a player's mulligan-eligible picks and their current teams:
    python3 scripts/mulligan.py --player Cal --list

    # 2) PREVIEW a swap (writes nothing) — --team accepts a code (NOR/USA) or a numeric id:
    python3 scripts/mulligan.py --player Cal --target darkhorse --team USA

    # 3) COMMIT it (writes; spends the mulligan). --commit is required to write:
    python3 scripts/mulligan.py --player Cal --target darkhorse --team USA --commit

The server guard only allows a COMMIT during the window (June 26–28, pending FIFA's R32
schedule). To preview a plan BEFORE the window, add e.g. --as-of 2026-06-27 (preview only —
it just feeds a simulated clock to the window check; it cannot be combined with --commit).
Requires .env.local with AIRTABLE_PAT / AIRTABLE_BASE_ID. Stdlib only.
"""
import argparse, datetime as dt, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickentry_server as ps


def resolve_team(token):
    """Accept a numeric team_id or a team code (case-insensitive) → team_id (int)."""
    s = str(token).strip()
    if s.isdigit():
        return int(s)
    code = s.upper()
    for r in ps.at_list("Teams", fields=["team_id", "code"]):
        f = r["fields"]
        if (f.get("code") or "").upper() == code and f.get("team_id") is not None:
            return int(f["team_id"])
    raise SystemExit(f"✗ no team matches '{token}' — use a code like NOR/USA or a numeric team_id")


def list_eligible(player):
    """The player's current mulligan-eligible picks (bracket slots + Dark Horse), each with
    its current team code. Excludes |mull replacement rows. Mirrors what the guard accepts."""
    rec2team = {}
    for r in ps.at_list("Teams", fields=["team_id", "code", "fifa_ranking"]):
        f = r["fields"]
        if f.get("team_id") is not None:
            rec2team[r["id"]] = {"team_id": int(f["team_id"]), "code": f.get("code"),
                                 "rank": f.get("fifa_ranking")}
    rows = []
    for r in ps.at_list("Predictions"):
        f = r.get("fields", {})
        lbl = f.get("label", "")
        if not lbl.startswith(player + "|"):
            continue
        key = lbl.split("|", 1)[1]
        if "|mull" in key or f.get("prediction_type") not in ("bracket_slot", "dark_horse"):
            continue
        link = f.get("predicted_team") or []
        t = rec2team.get(link[0]) if link else None
        rows.append({"key": key, "type": f.get("prediction_type"),
                     "code": (t or {}).get("code"), "team_id": (t or {}).get("team_id")})
    rows.sort(key=lambda x: (x["type"] != "dark_horse", x["key"]))   # Dark Horse first
    return rows


def show(res):
    if res.get("dryRun"):
        bp = res["wouldWrite"]["budget_patch"]
        print("DRY RUN — nothing written.\n")
        print(f"  re-pick      : {res['mulliganed']}  →  {res.get('replacement_code') or res['replacement_team']}")
        if res.get("token"):
            print(f"  token        : {res['token']} (on the replacement)")
        print(f"  replacement  : new row '{res['new_label']}'  — both old & new score at 50%")
        print(f"  budget       : mulligans_remaining → {bp['mulligans_remaining']}")
        print("\nRe-run with --commit to apply.")
    else:
        print("COMMITTED ✓\n")
        print(f"  re-picked    : {res['mulliganed']}  →  {res.get('replacement_code') or res['replacement_team']}")
        print(f"  new row      : {res['new_label']}  (both old & new score at 50%)")
        print(f"  mulligans_remaining → {res['mulligans_remaining']}")


def main():
    ap = argparse.ArgumentParser(description="Drive one mulligan (dry-run by default).")
    ap.add_argument("--player", required=True, help="PoolPlayers name, e.g. Cal or Andreas")
    ap.add_argument("--target", help="pick key to re-pick: darkhorse | Champion | F-1 | SF-2 | R16-3 ...")
    ap.add_argument("--team", help="replacement team: code (NOR/USA) or numeric team_id")
    ap.add_argument("--token", choices=["Double", "Triple", "AllIn"], help="optional token on the replacement")
    ap.add_argument("--note", default="", help="optional note stored on the Mulligans row")
    ap.add_argument("--list", action="store_true", help="list the player's eligible picks and exit")
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry-run preview)")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD", help="preview as if it were this date (dry-run only)")
    ap.add_argument("--yes", action="store_true", help="skip the commit confirmation prompt")
    args = ap.parse_args()

    ps.PAT, ps.BASE = ps.load_keys()   # populate the module globals at() relies on

    if args.list:
        rows = list_eligible(args.player)
        if not rows:
            print(f"{args.player}: no mulligan-eligible picks found (lock a bracket + Dark Horse first).")
            return
        print(f"{args.player}'s mulligan-eligible picks  (--target  →  current team):\n")
        for r in rows:
            tag = "Dark Horse" if r["type"] == "dark_horse" else r["key"]
            print(f"  --target {r['key']:<12}  {tag:<12}  now: {r['code'] or '—'}")
        print("\nPreview a swap:  --target <key> --team <CODE|id>   (add --commit to write)")
        return

    if not args.target or not args.team:
        raise SystemExit("✗ --target and --team are required (or use --list to see your options)")

    now = None
    if args.as_of:
        if args.commit:
            raise SystemExit("✗ --as-of is a preview aid and cannot be combined with --commit")
        now = dt.datetime.fromisoformat(args.as_of)

    team_id = resolve_team(args.team)
    replacement = {"team_id": team_id}
    if args.token:
        replacement["token"] = args.token

    if args.commit and not args.yes:
        ans = input(f"Use {args.player}'s ONE mulligan: {args.target} → {args.team}? "
                    f"Both score at 50%, visible to opponent, irreversible. [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            raise SystemExit("aborted — nothing written.")

    try:
        res = ps.save_mulligan(args.player, args.target, replacement,
                               note=args.note, now=now, dry_run=not args.commit)
    except RuntimeError as e:
        msg = str(e)
        if "window is not open" in msg and not args.as_of:
            msg += "  (tip: preview before the window with --as-of 2026-06-27)"
        raise SystemExit(f"✗ {msg}")
    show(res)


if __name__ == "__main__":
    main()
