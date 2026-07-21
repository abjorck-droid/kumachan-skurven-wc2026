#!/usr/bin/env python3
"""
export_season.py — dump the entire WC2026 Airtable base to local JSON for the
season wrap-up. Read-only; writes nothing to Airtable. Stdlib only.

    cd ~/Desktop/WorldCup2026
    python3 scripts/export_season.py

Output: data/season_export/<Table>.json (full records, all fields) + manifest.json
"""
import json
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickentry_server as ps

ps.PAT, ps.BASE = ps.load_keys()  # module leaves these None until main() runs

TABLES = ["Teams", "Footballers", "Matches", "PoolPlayers",
          "Predictions", "SideGames", "Mulligans", "PollLog"]

out_dir = Path(__file__).resolve().parent.parent / "data" / "season_export"
out_dir.mkdir(parents=True, exist_ok=True)

manifest = {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(), "tables": {}}
for t in TABLES:
    try:
        rows = ps.at_list(t)
    except Exception as e:  # PollLog may not exist in the live base
        print(f"  ! {t}: skipped ({e})")
        manifest["tables"][t] = {"count": None, "error": str(e)}
        continue
    p = out_dir / f"{t}.json"
    p.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    manifest["tables"][t] = {"count": len(rows), "bytes": p.stat().st_size}
    print(f"  ✓ {t}: {len(rows)} records → {p.name}")

(out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
print(f"\nDone. Export in {out_dir}")
