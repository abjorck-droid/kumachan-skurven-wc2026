#!/usr/bin/env python3
"""
pickentry_server.py — local pick-entry server for the World Cup 2026 bracket pool.

Keeps the Airtable PAT server-side (it never reaches the browser) and proxies reads/writes.
Run it on your Mac, then open the printed URL. You and Cal each pick a player at the top.

    cd ~/Desktop/WorldCup2026
    python3 scripts/pickentry_server.py            # serves http://127.0.0.1:8787
    python3 scripts/pickentry_server.py --port 9000

Requires the Airtable base to exist (run scripts/create_base.py first) and
AIRTABLE_PAT / AIRTABLE_BASE_ID in .env.local. Stdlib only.

Predictions are keyed on a deterministic `label` ("<Player>|<pick-key>") and written with
Airtable upsert, so saving repeatedly just updates — no duplicates. Player-name side games
use free text (predicted_text) until the Footballers table is populated.
"""
import argparse, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "index.html"
REST = "https://api.airtable.com/v0"
START_TOKENS = {"Double": 4, "Triple": 2, "AllIn": 1}

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
        sys.exit("✗ AIRTABLE_PAT / AIRTABLE_BASE_ID missing from .env.local")
    return keys["AIRTABLE_PAT"], keys["AIRTABLE_BASE_ID"]

PAT, BASE = (None, None)  # set in main()

# ---- airtable --------------------------------------------------------------
def at(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{REST}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {PAT}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.2 * (attempt + 1)); continue
            raise RuntimeError(f"Airtable HTTP {e.code} {method} {path}: {e.read().decode()[:240]}")
    raise RuntimeError(f"Airtable retries exhausted: {method} {path}")

def at_list(table, fields=None):
    out, offset, q = [], None, {"pageSize": 100}
    if fields:
        q["fields[]"] = fields
    while True:
        qq = dict(q)
        if offset:
            qq["offset"] = offset
        res = at("GET", f"{BASE}/{urllib.parse.quote(table)}?" + urllib.parse.urlencode(qq, doseq=True))
        out.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset:
            return out

def at_upsert(table, records, merge_on):
    n = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        at("PATCH", f"{BASE}/{urllib.parse.quote(table)}", {
            "performUpsert": {"fieldsToMergeOn": merge_on},
            "records": [{"fields": r} for r in batch], "typecast": True})
        time.sleep(0.2); n += len(batch)
    return n

# ---- pure transform (unit-tested) ------------------------------------------
def prediction_fields(player, pick, team_map, player_rec, sidegame_map, footballer_map=None):
    """Build one Predictions record's fields from a client pick dict."""
    footballer_map = footballer_map or {}
    rec = {"label": f"{player}|{pick['key']}", "pool_player": [player_rec],
           "prediction_type": pick["type"]}
    if pick.get("bracket_slot"):
        rec["bracket_slot"] = pick["bracket_slot"]
    if pick.get("side_game") and pick["side_game"] in sidegame_map:
        rec["side_game"] = [sidegame_map[pick["side_game"]]]
    if pick.get("team_id") is not None and int(pick["team_id"]) in team_map:
        rec["predicted_team"] = [team_map[int(pick["team_id"])]]
    # player picks: prefer a real Footballers link; fall back to free text if squads
    # aren't imported yet (or the chosen id isn't in the table).
    pid = pick.get("player_id")
    if pid not in (None, "") and str(pid).isdigit() and int(pid) in footballer_map:
        rec["predicted_player"] = [footballer_map[int(pid)]]
    elif pick.get("player_text"):
        rec["predicted_text"] = pick["player_text"]
    if pick.get("scalar") is not None and pick["scalar"] != "":
        rec["predicted_scalar"] = pick["scalar"]
    if pick.get("token"):
        rec["confidence_token"] = pick["token"]
    if pick.get("pundit_note"):
        rec["pundit_note"] = pick["pundit_note"]
    return rec

def token_counts(picks):
    used = {"Double": 0, "Triple": 0, "AllIn": 0}
    for p in picks:
        t = p.get("token")
        if t in used:
            used[t] += 1
    return used

# ---- request handling ------------------------------------------------------
def get_player(name):
    for rec in at_list("PoolPlayers"):
        if rec.get("fields", {}).get("name") == name:
            return rec
    return None

def bootstrap(player):
    team_recs = at_list("Teams", fields=["team_id", "code", "name", "group"])
    rec2tid = {r["id"]: r["fields"].get("team_id") for r in team_recs}
    team_by_rec = {r["id"]: {"code": r["fields"].get("code"), "group": r["fields"].get("group")}
                   for r in team_recs}
    teams = [{"id": r["fields"].get("team_id"), "code": r["fields"].get("code"),
              "name": r["fields"].get("name"), "group": r["fields"].get("group")}
             for r in team_recs if r["fields"].get("team_id") is not None]
    teams.sort(key=lambda t: (t.get("group") or "Z", t.get("name") or ""))
    side = [{"name": r["fields"].get("name"), "base_points": r["fields"].get("base_points"),
             "resolution_type": r["fields"].get("resolution_type")}
            for r in at_list("SideGames", fields=["name", "base_points", "resolution_type"])]
    # Footballers (empty until import_squads.py runs → UI falls back to free text).
    footballers, rec2pid = [], {}
    try:
        for r in at_list("Footballers", fields=["player_id", "name", "position", "shirt_number", "team"]):
            f = r.get("fields", {})
            pid = f.get("player_id")
            if pid is None:
                continue
            rec2pid[r["id"]] = pid
            link = f.get("team") or []
            tinfo = team_by_rec.get(link[0], {}) if link else {}
            footballers.append({"player_id": pid, "name": f.get("name"), "position": f.get("position"),
                                "shirt_number": f.get("shirt_number"),
                                "team_code": tinfo.get("code"), "group": tinfo.get("group")})
        footballers.sort(key=lambda x: ((x.get("group") or "Z"), (x.get("team_code") or ""), (x.get("name") or "")))
    except Exception:
        footballers, rec2pid = [], {}
    prow = get_player(player)
    pf = (prow or {}).get("fields", {})
    existing = []
    locked = False
    for r in at_list("Predictions"):
        f = r.get("fields", {})
        lbl = f.get("label", "")
        if lbl.startswith(player + "|"):
            link = f.get("predicted_team") or []
            plink = f.get("predicted_player") or []
            existing.append({"key": lbl.split("|", 1)[1], "type": f.get("prediction_type"),
                             "bracket_slot": f.get("bracket_slot"),
                             "team_id": rec2tid.get(link[0]) if link else None,
                             "player_id": rec2pid.get(plink[0]) if plink else None,
                             "player_text": f.get("predicted_text"), "scalar": f.get("predicted_scalar"),
                             "token": f.get("confidence_token"), "note": f.get("pundit_note")})
            if f.get("locked_at"):
                locked = True
    return {"player": player, "players": ["Andreas", "Cal"], "teams": teams, "sideGames": side,
            "footballers": footballers,
            "tokensStart": START_TOKENS, "locked": locked, "existing": existing,
            "tokensRemaining": {"Double": pf.get("tokens_remaining_double", 4),
                                "Triple": pf.get("tokens_remaining_triple", 2),
                                "AllIn": pf.get("tokens_remaining_allin", 1)}}

def save(player, picks):
    prow = get_player(player)
    if not prow:
        raise RuntimeError(f"player '{player}' not found in PoolPlayers (run create_base.py seed)")
    player_rec = prow["id"]
    team_map = {int(r["fields"]["team_id"]): r["id"]
                for r in at_list("Teams", fields=["team_id"]) if r["fields"].get("team_id") is not None}
    sg_map = {r["fields"].get("name"): r["id"] for r in at_list("SideGames", fields=["name"])}
    foot_map = {int(r["fields"]["player_id"]): r["id"]
                for r in at_list("Footballers", fields=["player_id"]) if r["fields"].get("player_id") is not None}
    records = [prediction_fields(player, p, team_map, player_rec, sg_map, foot_map) for p in picks if p.get("key")]
    n = at_upsert("Predictions", records, ["label"]) if records else 0
    used = token_counts(picks)
    at("PATCH", f"{BASE}/PoolPlayers", {"records": [{"id": player_rec, "fields": {
        "tokens_remaining_double": START_TOKENS["Double"] - used["Double"],
        "tokens_remaining_triple": START_TOKENS["Triple"] - used["Triple"],
        "tokens_remaining_allin": START_TOKENS["AllIn"] - used["AllIn"]}}]})
    return {"saved": n, "tokensUsed": used}

def lock(player):
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    ids = [r["id"] for r in at_list("Predictions", fields=["label"])
           if r["fields"].get("label", "").startswith(player + "|")]
    for i in range(0, len(ids), 10):
        at("PATCH", f"{BASE}/Predictions",
           {"records": [{"id": rid, "fields": {"locked_at": now}} for rid in ids[i:i + 10]]})
        time.sleep(0.2)
    return {"locked": len(ids), "at": now}

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not SITE.exists():
                return self._send(500, {"error": "site/index.html missing"})
            return self._send(200, SITE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/bootstrap":
            player = (urllib.parse.parse_qs(u.query).get("player") or ["Andreas"])[0]
            try:
                return self._send(200, bootstrap(player))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or "{}") if length else {}
        try:
            if u.path == "/api/save":
                return self._send(200, save(body["player"], body.get("picks", [])))
            if u.path == "/api/lock":
                return self._send(200, lock(body["player"]))
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

def main():
    global PAT, BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    PAT, BASE = load_keys()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Pick-entry server running →  http://127.0.0.1:{args.port}")
    print("Open it in your browser. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")

if __name__ == "__main__":
    main()
