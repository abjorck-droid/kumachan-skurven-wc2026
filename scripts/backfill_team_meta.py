#!/usr/bin/env python3
"""
backfill_team_meta.py — one-time fill of Teams.flag_emoji / kit_color_primary / fifa_ranking
from data/team_meta_2026.json (kit hexes, flag emoji, April-2026 FIFA ranking).

Why: the live board's kit bars fall back to grey without kit_color_primary, and Dark Horse
eligibility ("outside the FIFA top 16 at lock") wants fifa_ranking on record. The data file
notes its ranking edition — if the pool re-pins to the 10 June 2026 edition, update the file
and re-run (it's an upsert; safe to run repeatedly).

    python3 scripts/backfill_team_meta.py --dry-run     # show what would change
    python3 scripts/backfill_team_meta.py

Stdlib only; AIRTABLE_PAT / AIRTABLE_BASE_ID from env or ../.env.local. Run on the Mac.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST = "https://api.airtable.com/v0"
WRITE_PAUSE = 0.2

# ---- pure helpers (unit-tested) ---------------------------------------------

def build_updates(team_rows, meta):
    """team_rows: [{'team_id', 'code', ...existing fields}] -> (updates, missing_codes).
    An update is emitted only when something actually changes (idempotent re-runs)."""
    updates, missing = [], []
    for t in team_rows:
        code = t.get("code")
        m = meta.get(code)
        if not m:
            missing.append(code)
            continue
        fields = {}
        if m.get("flag") and t.get("flag_emoji") != m["flag"]:
            fields["flag_emoji"] = m["flag"]
        if m.get("kit") and t.get("kit_color_primary") != m["kit"]:
            fields["kit_color_primary"] = m["kit"]
        if m.get("fifa_ranking") is not None and t.get("fifa_ranking") != m["fifa_ranking"]:
            fields["fifa_ranking"] = m["fifa_ranking"]
        if fields:
            fields["team_id"] = t["team_id"]
            updates.append(fields)
    return updates, missing


def dark_horse_eligible(meta):
    """-> sorted list of codes ranked outside the top 16 (the legal Dark Horse pool)."""
    return sorted(c for c, m in meta.items() if (m.get("fifa_ranking") or 999) > 16)

# ---- airtable ----------------------------------------------------------------

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
    out, offset, q = [], None, {"pageSize": 100}
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


def at_upsert(base, table, pat, records, merge_on, dry=False):
    n = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        if dry:
            n += len(batch); continue
        at_request("PATCH", f"{base}/{urllib.parse.quote(table)}", pat, {
            "performUpsert": {"fieldsToMergeOn": merge_on},
            "records": [{"fields": r} for r in batch], "typecast": True})
        time.sleep(WRITE_PAUSE)
        n += len(batch)
    return n

# ---- main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    pat, base = load_keys()

    data = json.loads((ROOT / "data" / "team_meta_2026.json").read_text())
    meta = data["teams"]
    print(f"backfill_team_meta · ranking edition {data.get('ranking_edition', '?')}"
          f"{'  · DRY RUN' if args.dry_run else ''}")

    team_rows = []
    for r in at_list(base, "Teams", pat,
                     fields=["team_id", "code", "flag_emoji", "kit_color_primary", "fifa_ranking"]):
        f = r.get("fields", {})
        if f.get("team_id") is not None:
            team_rows.append(f)

    updates, missing = build_updates(team_rows, meta)
    for u in updates:
        print(f"  · {next(t['code'] for t in team_rows if t['team_id'] == u['team_id']):<4} → "
              + ", ".join(f"{k}={v}" for k, v in u.items() if k != "team_id"))
    if missing:
        print(f"  ⚠ no metadata for seeded code(s): {', '.join(sorted(set(missing)))}")
    extra = sorted(set(meta) - {t.get("code") for t in team_rows})
    if extra:
        print(f"  ⚠ metadata for codes not in the base: {', '.join(extra)}")

    n = at_upsert(base, "Teams", pat, updates, ["team_id"], dry=args.dry_run)
    elig = dark_horse_eligible(meta)
    print(f"· {n} team(s) updated{' (dry)' if args.dry_run else ''} · "
          f"{len(team_rows)} in base · Dark Horse-eligible (rank >16): {len(elig)} teams")


if __name__ == "__main__":
    main()
