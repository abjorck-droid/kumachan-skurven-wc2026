#!/usr/bin/env python3
"""
unlock_player.py — clear locked_at on one player's Predictions rows so they can
re-open pick-entry, fix something, and lock again. Pre-kickoff use only: the lock
is a reveal mechanism, the scoring gate is kickoff (Scoring spec v1.0).

Before touching anything it snapshots the player's current rows to
scripts/snapshots/<player>_<UTCstamp>.json — diff against a post-relock snapshot
to verify only the intended picks changed (the unlocked player can see the
opponent's revealed picks on the live board, so the snapshot is the honesty check).

    python3 scripts/unlock_player.py Cal --dry-run   # show what would be cleared
    python3 scripts/unlock_player.py Cal             # snapshot, then unlock

Stdlib only; AIRTABLE_PAT / AIRTABLE_BASE_ID from env or ../.env.local. Run on the Mac.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.2


def load_env():
    envfile = ROOT / ".env.local"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    pat, base = os.environ.get("AIRTABLE_PAT"), os.environ.get("AIRTABLE_BASE_ID")
    if not pat or not base:
        sys.exit("AIRTABLE_PAT / AIRTABLE_BASE_ID not set (env or .env.local)")
    return pat, base


def at_req(pat, method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {pat}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Airtable {e.code} on {method} {url}: {e.read().decode()[:300]}")


def list_predictions(pat, base):
    rows, offset = [], None
    while True:
        url = f"{REST}/{base}/Predictions?pageSize=100"
        if offset:
            url += f"&offset={offset}"
        page = at_req(pat, "GET", url)
        rows += page.get("records", [])
        offset = page.get("offset")
        if not offset:
            return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("player", help="PoolPlayers name, e.g. Cal")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    pat, base = load_env()

    prefix = args.player + "|"
    mine = [r for r in list_predictions(pat, base)
            if (r.get("fields", {}).get("label") or "").startswith(prefix)]
    locked = [r for r in mine if r["fields"].get("locked_at")]
    print(f"{args.player}: {len(mine)} prediction rows, {len(locked)} locked")
    if not locked:
        print("Nothing to unlock.")
        return

    snapdir = ROOT / "scripts" / "snapshots"
    snapdir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = snapdir / f"{args.player}_{stamp}.json"
    snap.write_text(json.dumps(mine, indent=2, sort_keys=True))
    print(f"Snapshot: {snap.relative_to(ROOT)}")

    if args.dry_run:
        for r in locked[:10]:
            print("  would clear:", r["fields"]["label"])
        if len(locked) > 10:
            print(f"  ... and {len(locked) - 10} more")
        return

    ids = [r["id"] for r in locked]
    for i in range(0, len(ids), 10):
        at_req(pat, "PATCH", f"{REST}/{base}/Predictions", {
            "records": [{"id": rid, "fields": {"locked_at": None}} for rid in ids[i:i + 10]]})
        time.sleep(WRITE_PAUSE)
    print(f"Cleared locked_at on {len(ids)} rows. "
          f"{args.player} should hard-refresh pick-entry, add the missing picks, save, and LOCK again.")


if __name__ == "__main__":
    main()
