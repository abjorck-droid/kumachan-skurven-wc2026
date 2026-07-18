#!/usr/bin/env python3
"""
setup_stoppage_pot.py — v1.2 "Stoppage Time" endgame pot: Airtable migration + tally.

Adopted 2026-07-17 (see 08_stoppage_time_amendment_proposal.md, Variant A, and
09_stoppage_pot_airtable_migration.md for the full conventions).

Modes
    (default)      Migrate schema. Idempotent — safe to re-run:
                     · Predictions:  + pot (singleSelect: "stoppage"), + pot_points (number)
                     · PoolPlayers:  + stoppage_pot (number), + stoppage_token_remaining (number)
                     · select options: prediction_type + "stoppage_bet",
                       confidence_token + "Stoppage2x", bonus_bet_type + 10 wild types
                     · SideGames: seed "The Duel" row
                     · PoolPlayers: stoppage_token_remaining -> 1 where empty
    --tally        Sum pot_points per player -> PoolPlayers.stoppage_pot, then print the
                   margin conversion:  recorded = max(1, M - N) if N > 0 else M + |N|
                   (M = main-game margin, N = trailing pot - leading pot).
                   Run after the scoring engine has resolved the legacy items.
    --dry-run      Print what would change; write nothing. Works with both modes.

Run ON THE MAC (the Cowork sandbox has no network):
    cd ~/Desktop/WorldCup2026 && python3 scripts/setup_stoppage_pot.py --dry-run

Scoring stays MANUAL by design: type each pot bet's points into Predictions.pot_points
(already token-multiplied if Stoppage2x is on the row). The scoring engine never reads
pot rows — prediction_type "stoppage_bet" falls through its dispatch untouched, so
total_score stays clean. Stdlib only, same .env.local pattern as the other scripts.
"""
import argparse, json, sys, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST = "https://api.airtable.com/v0"
META = "https://api.airtable.com/v0/meta/bases"
WRITE_PAUSE = 0.2

WILD_BET_TYPES = [
    "Extra time played",          # 15  auto
    "Decided on penalties",       # 25  auto
    "Own goal in match",          # 25  auto
    "Substitute scores",          # 15  auto (lineups + events)
    "Goal in 90+ stoppage time",  # 20  auto (minute.extra, either half)
    "No second-half goals",       # 25  auto
    "5+ combined cards",          # 15  auto
    "Hat-trick in match",         # 40  auto
    "Keeper saves penalty",       # 30  judged (API can't split saved vs off-target)
    "VAR overturn",               # 20  judged (API VAR events are patchy)
]

DUEL_ROW = {
    "name": "The Duel",
    "resolution_type": "player",
    "base_points": 25,
    "lock_at_utc": "2026-07-18T21:00:00.000Z",   # 3rd-place kickoff — both matches count
    "description": ("Stoppage-pot special (v1.2): Messi vs Mbappé, goals scored across the "
                    "3rd Place Final and the Final combined. Pick Messi / Mbappé / Level "
                    "(predicted_text). Scores into pot_points, not the main game."),
}

# ---- env + http (create_base.py pattern) -----------------------------------

def load_keys():
    import os
    keys = {k: os.environ.get(k) for k in ("AIRTABLE_PAT", "AIRTABLE_BASE_ID")}
    p = ROOT / ".env.local"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys.setdefault(k.strip(), None)
                if not keys.get(k.strip()):
                    keys[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k, v in keys.items() if not v]
    if missing:
        sys.exit(f"missing {missing} — set in .env.local or environment")
    return keys["AIRTABLE_PAT"], keys["AIRTABLE_BASE_ID"]


def http(method, url, pat, body=None):
    req = urllib.request.Request(url, method=method,
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1 + attempt); continue
            sys.exit(f"Airtable {e.code} {method} {url}: {e.read().decode()[:300]}")
    sys.exit("Airtable retries exhausted")


def at_list(pat, base, table, fields):
    out, offset = [], None
    while True:
        qs = urllib.parse.urlencode([("pageSize", 100)] + [("fields[]", f) for f in fields])
        url = f"{REST}/{base}/{urllib.parse.quote(table)}?{qs}"
        if offset:
            url += f"&offset={urllib.parse.quote(offset)}"
        res = http("GET", url, pat)
        out += res.get("records", [])
        offset = res.get("offset")
        if not offset:
            return out

# ---- migration -------------------------------------------------------------

def get_tables_full(pat, base):
    res = http("GET", f"{META}/{base}/tables", pat)
    return {t["name"]: t for t in res.get("tables", [])}


def add_field(pat, base, tid, spec, dry):
    if dry:
        print(f"    + would add field {spec['name']}")
        return
    http("POST", f"{META}/{base}/tables/{tid}/fields", pat, spec)
    print(f"    + added field {spec['name']}")
    time.sleep(WRITE_PAUSE)


def extend_select(pat, base, table, field_name, new_choices, dry):
    """Add missing singleSelect options.

    The metadata update-field endpoint rejects `options` payloads
    (422 INVALID_REQUEST_UNKNOWN — observed live 2026-07-17), so options are
    materialized the way create_base.py's seeds do it: record writes with
    `typecast: true` auto-create unknown select options. One temp row is created,
    PATCHed through each new value, then deleted. Existing options are untouched."""
    fld = next((f for f in table["fields"] if f["name"] == field_name), None)
    if fld is None:
        sys.exit(f"field {field_name} not found on {table['name']}")
    have = [c["name"] for c in fld.get("options", {}).get("choices", [])]
    todo = [c for c in new_choices if c not in have]
    if not todo:
        print(f"    · {field_name}: all options present")
        return
    if dry:
        print(f"    + would add options to {field_name}: {todo}")
        return
    tname = urllib.parse.quote(table["name"])
    pid = table.get("primaryFieldId")
    primary = next((f["name"] for f in table["fields"] if f["id"] == pid),
                   table["fields"][0]["name"])
    res = http("POST", f"{REST}/{base}/{tname}", pat,
               {"records": [{"fields": {primary: "zz|stoppage_migration_temp"}}],
                "typecast": True})
    rid = res["records"][0]["id"]
    try:
        for c in todo:
            http("PATCH", f"{REST}/{base}/{tname}", pat,
                 {"records": [{"id": rid, "fields": {field_name: c}}], "typecast": True})
            time.sleep(WRITE_PAUSE)
    finally:
        http("DELETE", f"{REST}/{base}/{tname}/{rid}", pat)   # runs even if a PATCH exits
    print(f"    + {field_name}: added {todo} (via typecast temp row)")


def migrate(pat, base, dry):
    tables = get_tables_full(pat, base)
    preds, pool, sides = tables["Predictions"], tables["PoolPlayers"], tables["SideGames"]

    print("  Predictions fields:")
    have = {f["name"] for f in preds["fields"]}
    if "pot" not in have:
        add_field(pat, base, preds["id"], {"name": "pot", "type": "singleSelect",
                  "options": {"choices": [{"name": "stoppage"}]}}, dry)
    else:
        print("    · pot exists")
    if "pot_points" not in have:
        add_field(pat, base, preds["id"], {"name": "pot_points", "type": "number",
                  "options": {"precision": 0}}, dry)
    else:
        print("    · pot_points exists")

    print("  PoolPlayers fields:")
    have = {f["name"] for f in pool["fields"]}
    tok_existed = "stoppage_token_remaining" in have
    for fname in ("stoppage_pot", "stoppage_token_remaining"):
        if fname not in have:
            add_field(pat, base, pool["id"], {"name": fname, "type": "number",
                      "options": {"precision": 0}}, dry)
        else:
            print(f"    · {fname} exists")

    print("  Select options:")
    extend_select(pat, base, preds, "prediction_type", ["stoppage_bet"], dry)
    extend_select(pat, base, preds, "confidence_token", ["Stoppage2x"], dry)
    extend_select(pat, base, preds, "bonus_bet_type", WILD_BET_TYPES, dry)

    print("  SideGames seed:")
    rows = at_list(pat, base, "SideGames", ["name"])
    if any((r.get("fields", {}).get("name")) == DUEL_ROW["name"] for r in rows):
        print("    · The Duel exists")
    elif dry:
        print("    + would create SideGames row: The Duel")
    else:
        http("POST", f"{REST}/{base}/SideGames", pat,
             {"records": [{"fields": DUEL_ROW}], "typecast": True})
        print("    + created SideGames row: The Duel")

    print("  Stoppage tokens:")
    if not tok_existed:
        # Field didn't exist at scan time — it was just created above (or this is a dry
        # run and it doesn't exist yet). Don't query it (422 UNKNOWN_FIELD_NAME on dry
        # runs, and dodges any metadata-propagation race right after creation): every
        # player necessarily needs the init.
        players = at_list(pat, base, "PoolPlayers", ["name"])
        ups = [{"id": r["id"], "fields": {"stoppage_token_remaining": 1}} for r in players]
    else:
        # Field pre-existed: only fill blanks, never reset a spent token back to 1.
        players = at_list(pat, base, "PoolPlayers", ["name", "stoppage_token_remaining"])
        ups = [{"id": r["id"], "fields": {"stoppage_token_remaining": 1}}
               for r in players if r.get("fields", {}).get("stoppage_token_remaining") is None]
    if not ups:
        print("    · already initialized")
    elif dry:
        print(f"    + would set stoppage_token_remaining=1 for {len(ups)} player(s)")
    else:
        http("PATCH", f"{REST}/{base}/PoolPlayers", pat, {"records": ups})
        print(f"    + initialized {len(ups)} player(s) at 1 token")

# ---- tally -----------------------------------------------------------------

def tally(pat, base, dry):
    preds = at_list(pat, base, "Predictions", ["label", "pot", "pot_points"])
    players = at_list(pat, base, "PoolPlayers", ["name", "total_score", "stoppage_pot"])
    names = [r["fields"].get("name") for r in players]

    pots = {n: 0 for n in names}
    for r in preds:
        f = r.get("fields", {})
        if f.get("pot") != "stoppage":
            continue
        owner = next((n for n in names if (f.get("label") or "").startswith(n + "|")), None)
        if owner:
            pots[owner] += f.get("pot_points") or 0

    print("  Pot totals:")
    ups = []
    for r in players:
        n = r["fields"].get("name")
        print(f"    · {n:<8} pot={pots[n]}  (main={r['fields'].get('total_score', 0)})")
        if r["fields"].get("stoppage_pot") != pots[n]:
            ups.append({"id": r["id"], "fields": {"stoppage_pot": pots[n]}})
    if ups and not dry:
        http("PATCH", f"{REST}/{base}/PoolPlayers", pat, {"records": ups})
        print(f"    + wrote stoppage_pot for {len(ups)} player(s)")
    elif ups:
        print(f"    + would write stoppage_pot for {len(ups)} player(s)")

    if len(names) == 2:
        a, b = players
        lead, trail = (a, b) if (a["fields"].get("total_score", 0) >=
                                 b["fields"].get("total_score", 0)) else (b, a)
        ln, tn = lead["fields"]["name"], trail["fields"]["name"]
        M = lead["fields"].get("total_score", 0) - trail["fields"].get("total_score", 0)
        N = pots[tn] - pots[ln]
        rec = max(1, M - N) if N > 0 else M + abs(N)
        print(f"\n  Conversion:  M = {M} ({ln} leads)   N = {N} "
              f"({'consolation' if N > 0 else 'bonus' if N < 0 else 'level'})")
        print(f"  RECORDED MARGIN: {ln} defeats {tn} by {rec}")
        print("  (only final once the engine has resolved Champion slot, Golden Boot,")
        print("   Golden Glove and Total Tournament Goals — check those rows are resolved)")

# ---- main ------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stoppage-pot Airtable migration + tally")
    ap.add_argument("--tally", action="store_true", help="sum pot_points -> stoppage_pot + print conversion")
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = ap.parse_args()
    pat, base = load_keys()
    print(f"{'DRY RUN — ' if args.dry_run else ''}base {base}")
    (tally if args.tally else migrate)(pat, base, args.dry_run)
    print("done.")
