#!/usr/bin/env python3
"""
check_mulligans.py — read-only audit of the mulligan writes (no changes, ever).

Surfaces exactly what `mulligan.py --list` hides: the `|mull` replacement rows and the
Mulligans link table, so we can confirm each player's mulligan actually WROTE its sibling
+ link (not just decremented the counter). Run after a mulligan to verify, or any time to
see who re-picked what.

    cd ~/Desktop/WorldCup2026
    python3 scripts/check_mulligans.py

Requires .env.local with AIRTABLE_PAT / AIRTABLE_BASE_ID. Stdlib only. Writes nothing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickentry_server as ps


def main():
    ps.PAT, ps.BASE = ps.load_keys()

    # team rec -> code, and prediction rec -> {label, team code, type, token, points, resolved}
    rec2code = {}
    for r in ps.at_list("Teams", fields=["team_id", "code"]):
        f = r["fields"]
        if f.get("code"):
            rec2code[r["id"]] = f["code"]

    preds = {}
    for r in ps.at_list("Predictions",
                        fields=["label", "prediction_type", "predicted_team",
                                "confidence_token", "points_awarded", "resolved", "locked_at"]):
        f = r.get("fields", {})
        link = f.get("predicted_team") or []
        preds[r["id"]] = {
            "label": f.get("label", ""),
            "type": f.get("prediction_type"),
            "code": rec2code.get(link[0]) if link else None,
            "token": f.get("confidence_token"),
            "points": f.get("points_awarded"),
            "resolved": f.get("resolved"),
            "locked_at": f.get("locked_at"),
        }

    players = {}
    for r in ps.at_list("PoolPlayers", fields=["name", "mulligans_remaining"]):
        f = r.get("fields", {})
        if f.get("name"):
            players[f["name"]] = f.get("mulligans_remaining")

    print("=" * 64)
    print("MULLIGAN AUDIT (read-only)")
    print("=" * 64)
    for nm in sorted(players):
        print(f"\n{nm}: mulligans_remaining = {players[nm]}")
        sibs = [p for p in preds.values()
                if p["label"].startswith(nm + "|") and "|mull" in p["label"]]
        if not sibs:
            print("  ⚠ NO |mull replacement rows found for this player.")
        for p in sibs:
            print(f"  • {p['label']:<26} → {p['code'] or '—':<5}  "
                  f"token={p['token'] or '-':<6} pts={p['points']} resolved={p['resolved']} "
                  f"locked={'yes' if p['locked_at'] else 'NO'}")

    # Mulligans link table — original -> new, with resolved team codes
    print("\n" + "-" * 64)
    print("Mulligans table (original → replacement):")
    mulls = ps.at_list("Mulligans")
    if not mulls:
        print("  ⚠ Mulligans table is EMPTY — no link rows were written.")
    for m in mulls:
        f = m.get("fields", {})
        o = (f.get("original_prediction") or [None])[0]
        n = (f.get("new_prediction") or [None])[0]
        op = preds.get(o, {}); npk = preds.get(n, {})
        note = f.get("note") or f.get("notes") or ""
        print(f"  • {op.get('label','?'):<22} ({op.get('code') or '—'})  →  "
              f"{npk.get('label','?'):<26} ({npk.get('code') or '—'})  {('· ' + note) if note else ''}")

    print("\nIf a player's counter is 0 but has NO |mull row / NO Mulligans link above,")
    print("the write only spent the counter — re-run that mulligan to create the rows.")


if __name__ == "__main__":
    main()
