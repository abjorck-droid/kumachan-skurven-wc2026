// Cloudflare Pages Function — hosted pick-entry API for the World Cup 2026 pool.
//
// Routes (all under /api/*, auth via ?p={magic_link_token}):
//   GET  /api/bootstrap?p=TOKEN          -> teams, side games, footballers, the player's existing picks
//   POST /api/save?p=TOKEN   {picks:[]}  -> upsert that player's predictions, recompute token reserves
//   POST /api/lock?p=TOKEN               -> stamp locked_at on all of that player's predictions
//
// The Airtable PAT lives ONLY in the Pages environment (env.AIRTABLE_PAT) — never in the browser.
// This mirrors scripts/pickentry_server.py (same logic, same Predictions.label keying) so the local
// server and the hosted version stay interchangeable. The player is identified by their token, so a
// person can only read/write their own picks.

const REST = "https://api.airtable.com/v0";
const START_TOKENS = { Double: 4, Triple: 2, AllIn: 1 };

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Airtable client (Bearer PAT from env) ---------------------------------
async function atReq(env, method, path, body) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(`${REST}/${path}`, {
      method,
      headers: { Authorization: `Bearer ${env.AIRTABLE_PAT}`, "Content-Type": "application/json" },
      body: body != null ? JSON.stringify(body) : undefined,
    });
    if (res.status === 429) { await sleep(1200 * (attempt + 1)); continue; }
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`Airtable ${res.status} ${method} ${path}: ${t.slice(0, 240)}`);
    }
    return res.status === 204 ? {} : res.json();
  }
  throw new Error(`Airtable retries exhausted: ${method} ${path}`);
}

async function atList(env, table, fields) {
  const out = [];
  let offset = null;
  do {
    const qs = new URLSearchParams();
    qs.set("pageSize", "100");
    if (fields) for (const f of fields) qs.append("fields[]", f);
    if (offset) qs.set("offset", offset);
    const res = await atReq(env, "GET", `${env.AIRTABLE_BASE_ID}/${encodeURIComponent(table)}?${qs}`);
    out.push(...(res.records || []));
    offset = res.offset;
  } while (offset);
  return out;
}

async function atUpsert(env, table, records, mergeOn) {
  let n = 0;
  for (let i = 0; i < records.length; i += 10) {
    const batch = records.slice(i, i + 10);
    await atReq(env, "PATCH", `${env.AIRTABLE_BASE_ID}/${encodeURIComponent(table)}`, {
      performUpsert: { fieldsToMergeOn: mergeOn },
      records: batch.map((r) => ({ fields: r })),
      typecast: true,
    });
    n += batch.length;
  }
  return n;
}

// ---- pure transform (mirrors pickentry_server.prediction_fields) -----------
function predictionFields(playerName, pick, teamMap, playerRec, sgMap, footMap) {
  const rec = { label: `${playerName}|${pick.key}`, pool_player: [playerRec], prediction_type: pick.type };
  if (pick.bracket_slot) rec.bracket_slot = pick.bracket_slot;
  if (pick.side_game && sgMap[pick.side_game]) rec.side_game = [sgMap[pick.side_game]];
  if (pick.team_id != null && teamMap[parseInt(pick.team_id)]) rec.predicted_team = [teamMap[parseInt(pick.team_id)]];
  // player picks: prefer a real Footballers link; fall back to free text if squads aren't imported.
  const pid = pick.player_id;
  if (pid != null && pid !== "" && /^\d+$/.test(String(pid)) && footMap[parseInt(pid)]) {
    rec.predicted_player = [footMap[parseInt(pid)]];
  } else if (pick.player_text) {
    rec.predicted_text = pick.player_text;
  }
  if (pick.scalar != null && pick.scalar !== "") rec.predicted_scalar = pick.scalar;
  if (pick.token) rec.confidence_token = pick.token;
  if (pick.pundit_note) rec.pundit_note = pick.pundit_note;
  return rec;
}

// ---- auth ------------------------------------------------------------------
async function playerByToken(env, token) {
  if (!token) return null;
  const recs = await atList(env, "PoolPlayers");
  return recs.find((r) => (r.fields || {}).magic_link_token === token) || null;
}

// ---- handlers --------------------------------------------------------------
async function bootstrap(env, prow) {
  const playerName = (prow.fields || {}).name;
  const teamRecs = await atList(env, "Teams", ["team_id", "code", "name", "group"]);
  const rec2tid = {}, teamByRec = {};
  for (const r of teamRecs) {
    rec2tid[r.id] = r.fields.team_id;
    teamByRec[r.id] = { code: r.fields.code, group: r.fields.group };
  }
  const teams = teamRecs
    .filter((r) => r.fields.team_id != null)
    .map((r) => ({ id: r.fields.team_id, code: r.fields.code, name: r.fields.name, group: r.fields.group }));
  teams.sort((a, b) => (a.group || "Z").localeCompare(b.group || "Z") || (a.name || "").localeCompare(b.name || ""));

  const side = (await atList(env, "SideGames", ["name", "base_points", "resolution_type"])).map((r) => ({
    name: r.fields.name, base_points: r.fields.base_points, resolution_type: r.fields.resolution_type,
  }));

  let footballers = [], rec2pid = {};
  try {
    for (const r of await atList(env, "Footballers", ["player_id", "name", "position", "shirt_number", "team"])) {
      const f = r.fields || {};
      if (f.player_id == null) continue;
      rec2pid[r.id] = f.player_id;
      const link = f.team || [];
      const tinfo = link.length ? (teamByRec[link[0]] || {}) : {};
      footballers.push({ player_id: f.player_id, name: f.name, position: f.position,
        shirt_number: f.shirt_number, team_code: tinfo.code, group: tinfo.group });
    }
    footballers.sort((a, b) =>
      (a.group || "Z").localeCompare(b.group || "Z") ||
      (a.team_code || "").localeCompare(b.team_code || "") ||
      (a.name || "").localeCompare(b.name || ""));
  } catch (e) { footballers = []; rec2pid = {}; }

  const pf = prow.fields || {};
  const existing = [];
  let locked = false;
  for (const r of await atList(env, "Predictions")) {
    const f = r.fields || {};
    const lbl = f.label || "";
    if (lbl.startsWith(playerName + "|")) {
      const link = f.predicted_team || [];
      const plink = f.predicted_player || [];
      existing.push({
        key: lbl.split("|").slice(1).join("|"),
        type: f.prediction_type, bracket_slot: f.bracket_slot,
        team_id: link.length ? rec2tid[link[0]] : null,
        player_id: plink.length ? rec2pid[plink[0]] : null,
        player_text: f.predicted_text, scalar: f.predicted_scalar,
        token: f.confidence_token, note: f.pundit_note,
      });
      if (f.locked_at) locked = true;
    }
  }

  return {
    player: playerName, players: [playerName], teams, sideGames: side, footballers,
    tokensStart: START_TOKENS, locked, existing,
    tokensRemaining: {
      Double: pf.tokens_remaining_double ?? 4,
      Triple: pf.tokens_remaining_triple ?? 2,
      AllIn: pf.tokens_remaining_allin ?? 1,
    },
  };
}

async function save(env, prow, picks) {
  const playerName = (prow.fields || {}).name;
  const playerRec = prow.id;
  const teamMap = {};
  for (const r of await atList(env, "Teams", ["team_id"]))
    if (r.fields.team_id != null) teamMap[parseInt(r.fields.team_id)] = r.id;
  const sgMap = {};
  for (const r of await atList(env, "SideGames", ["name"])) sgMap[r.fields.name] = r.id;
  const footMap = {};
  for (const r of await atList(env, "Footballers", ["player_id"]))
    if (r.fields.player_id != null) footMap[parseInt(r.fields.player_id)] = r.id;

  const records = (picks || [])
    .filter((p) => p && p.key)
    .map((p) => predictionFields(playerName, p, teamMap, playerRec, sgMap, footMap));
  const n = records.length ? await atUpsert(env, "Predictions", records, ["label"]) : 0;

  const used = { Double: 0, Triple: 0, AllIn: 0 };
  for (const p of picks || []) if (used[p.token] != null) used[p.token]++;
  await atReq(env, "PATCH", `${env.AIRTABLE_BASE_ID}/PoolPlayers`, {
    records: [{ id: playerRec, fields: {
      tokens_remaining_double: START_TOKENS.Double - used.Double,
      tokens_remaining_triple: START_TOKENS.Triple - used.Triple,
      tokens_remaining_allin: START_TOKENS.AllIn - used.AllIn,
    } }],
  });
  return { saved: n, tokensUsed: used };
}

async function lock(env, prow) {
  const playerName = (prow.fields || {}).name;
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const ids = (await atList(env, "Predictions", ["label"]))
    .filter((r) => (r.fields.label || "").startsWith(playerName + "|"))
    .map((r) => r.id);
  for (let i = 0; i < ids.length; i += 10) {
    await atReq(env, "PATCH", `${env.AIRTABLE_BASE_ID}/Predictions`, {
      records: ids.slice(i, i + 10).map((rid) => ({ id: rid, fields: { locked_at: now } })),
    });
  }
  return { locked: ids.length, at: now };
}

// ---- router ----------------------------------------------------------------
export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  try {
    if (!env.AIRTABLE_PAT || !env.AIRTABLE_BASE_ID)
      return json({ error: "server not configured (missing AIRTABLE_PAT / AIRTABLE_BASE_ID)" }, 500);
    const token = url.searchParams.get("p");
    const prow = await playerByToken(env, token);
    if (!token) return json({ error: "missing access token" }, 401);
    if (!prow) return json({ error: "invalid access token" }, 403);

    const path = url.pathname.replace(/\/+$/, "");
    if (path.endsWith("/api/bootstrap") && request.method === "GET")
      return json(await bootstrap(env, prow));
    if (path.endsWith("/api/save") && request.method === "POST") {
      const body = await request.json().catch(() => ({}));
      return json(await save(env, prow, body.picks || []));
    }
    if (path.endsWith("/api/lock") && request.method === "POST")
      return json(await lock(env, prow));
    return json({ error: "not found" }, 404);
  } catch (e) {
    return json({ error: String((e && e.message) || e) }, 500);
  }
}
