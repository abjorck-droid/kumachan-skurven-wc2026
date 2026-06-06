// Cloudflare Pages Function — hosted pick-entry API for the World Cup 2026 pool.
//
// Routes (all under /api/*, auth via ?p={magic_link_token} except /api/public):
//   GET  /api/bootstrap?p=TOKEN          -> teams, side games, footballers, the player's existing picks
//   POST /api/save?p=TOKEN   {picks:[]}  -> upsert that player's predictions, recompute token reserves
//   POST /api/lock?p=TOKEN               -> stamp locked_at on all of that player's predictions
//   GET  /api/public                     -> NO token. Sanitized read-only feed for the public view:
//                                           scores, standings, matches, and each player's picks —
//                                           revealed only once THAT player has locked. Never includes
//                                           magic tokens; pundit notes only after the pick resolves.
//
// The Airtable PAT lives ONLY in the Pages environment (env.AIRTABLE_PAT) — never in the browser.
// This mirrors scripts/pickentry_server.py (same logic, same Predictions.label keying) so the local
// server and the hosted version stay interchangeable. The player is identified by their token, so a
// person can only read/write their own picks.

const REST = "https://api.airtable.com/v0";
const START_TOKENS = { Double: 4, Triple: 2, AllIn: 1 };

const json = (obj, status = 200, extraHeaders = {}) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...extraHeaders } });
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
function predictionFields(playerName, pick, teamMap, playerRec, sgMap, footMap, matchMap) {
  matchMap = matchMap || {};
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
  // group-match picks: outcome (Home/Draw/Away) + optional exact score, linked to the match
  if (pick.match_id != null && matchMap[parseInt(pick.match_id)]) rec.match = [matchMap[parseInt(pick.match_id)]];
  if (pick.outcome) rec.predicted_outcome = pick.outcome;
  if (pick.score_home != null && pick.score_home !== "") rec.predicted_score_home = pick.score_home;
  if (pick.score_away != null && pick.score_away !== "") rec.predicted_score_away = pick.score_away;
  if (pick.scalar != null && pick.scalar !== "") rec.predicted_scalar = pick.scalar;
  if (pick.token) rec.confidence_token = pick.token;
  if (pick.pundit_note) rec.pundit_note = pick.pundit_note;
  return rec;
}

// Fetch specific records by Airtable record id (used to resolve the handful of
// Footballers linked from predictions without paging all 1,248 of them).
async function atListByIds(env, table, ids, fields) {
  const out = [];
  const uniq = [...new Set(ids)].filter(Boolean);
  for (let i = 0; i < uniq.length; i += 40) {
    const chunk = uniq.slice(i, i + 40);
    const qs = new URLSearchParams();
    qs.set("pageSize", "100");
    qs.set("filterByFormula", "OR(" + chunk.map((id) => `RECORD_ID()='${id}'`).join(",") + ")");
    if (fields) for (const f of fields) qs.append("fields[]", f);
    const res = await atReq(env, "GET", `${env.AIRTABLE_BASE_ID}/${encodeURIComponent(table)}?${qs}`);
    out.push(...(res.records || []));
  }
  return out;
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
    teamByRec[r.id] = { code: r.fields.code, group: r.fields.group, name: r.fields.name, team_id: r.fields.team_id };
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

  // Group-stage fixtures (empty until load_fixtures.py runs). Group stage only.
  let matches = [];
  try {
    for (const r of await atList(env, "Matches", ["fixture_id", "label", "round", "home_team", "away_team", "kickoff_utc"])) {
      const f = r.fields || {};
      const fid = f.fixture_id;
      const rnd = f.round || "";
      if (fid == null || !String(rnd).toLowerCase().startsWith("group")) continue;
      const h = f.home_team || [], a = f.away_team || [];
      const hi = h.length ? (teamByRec[h[0]] || {}) : {};
      const ai = a.length ? (teamByRec[a[0]] || {}) : {};
      matches.push({ fixture_id: fid, round: rnd, kickoff: f.kickoff_utc,
        group: hi.group || ai.group,
        home_id: hi.team_id, home_code: hi.code, home_name: hi.name,
        away_id: ai.team_id, away_code: ai.code, away_name: ai.name });
    }
    matches.sort((a, b) =>
      (a.group || "Z").localeCompare(b.group || "Z") || (a.kickoff || "").localeCompare(b.kickoff || ""));
  } catch (e) { matches = []; }

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
        outcome: f.predicted_outcome,
        score_home: f.predicted_score_home, score_away: f.predicted_score_away,
        token: f.confidence_token, note: f.pundit_note,
      });
      if (f.locked_at) locked = true;
    }
  }

  return {
    player: playerName, players: [playerName], teams, sideGames: side, footballers, matches,
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
  const matchMap = {};
  for (const r of await atList(env, "Matches", ["fixture_id"]))
    if (r.fields.fixture_id != null) matchMap[parseInt(r.fields.fixture_id)] = r.id;

  const records = (picks || [])
    .filter((p) => p && p.key)
    .map((p) => predictionFields(playerName, p, teamMap, playerRec, sgMap, footMap, matchMap));
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

// ---- public read-only view ---------------------------------------------------
// Everything here is safe to show anyone with the URL. The hard rules:
//   1. NEVER include PoolPlayers.magic_link_token (or the PAT, which never leaves env).
//   2. A player's picks appear only once that player has locked ("locking reveals
//      them to your opponent" — same rule the pick-entry UI promises).
//   3. pundit_note rides along only after Predictions.resolved is checked
//      ("hidden until it resolves").
async function publicView(env) {
  const [playerRecs, teamRecs, matchRecs, sideRecs] = await Promise.all([
    atList(env, "PoolPlayers", ["name", "display_color", "total_score",
      "tokens_remaining_double", "tokens_remaining_triple", "tokens_remaining_allin", "mulligans_remaining"]),
    atList(env, "Teams", ["team_id", "code", "name", "group", "fifa_ranking", "kit_color_primary"]),
    atList(env, "Matches", ["fixture_id", "round", "kickoff_utc", "venue", "home_team", "away_team",
      "home_score", "away_score", "status", "winner", "winner_method"]),
    atList(env, "SideGames", ["name", "base_points", "resolution_type", "resolved_value", "dark_horse_ladder"]),
  ]);

  // Standings may be empty pre-tournament; tolerate a missing table too.
  let standRecs = [];
  try {
    standRecs = await atList(env, "Standings", ["label", "group", "rank", "team", "played", "win",
      "draw", "loss", "goals_for", "goals_against", "goal_diff", "points", "form"]);
  } catch (e) { standRecs = []; }

  const teamByRec = {};
  const teams = [];
  for (const r of teamRecs) {
    const f = r.fields || {};
    if (f.team_id == null) continue;
    teamByRec[r.id] = { team_id: f.team_id, code: f.code, name: f.name, group: f.group };
    teams.push({ id: f.team_id, code: f.code, name: f.name, group: f.group,
      fifa_ranking: f.fifa_ranking, kit: f.kit_color_primary });
  }
  teams.sort((a, b) => (a.group || "Z").localeCompare(b.group || "Z") || (a.name || "").localeCompare(b.name || ""));

  const matchByRec = {};
  const matches = [];
  for (const r of matchRecs) {
    const f = r.fields || {};
    if (f.fixture_id == null) continue;
    matchByRec[r.id] = f.fixture_id;
    const h = (f.home_team || [])[0], a = (f.away_team || [])[0], w = (f.winner || [])[0];
    const hi = teamByRec[h] || {}, ai = teamByRec[a] || {};
    matches.push({
      fixture_id: f.fixture_id, round: f.round, kickoff: f.kickoff_utc, venue: f.venue,
      group: hi.group || ai.group, status: f.status,
      home_id: hi.team_id, home_code: hi.code, home_name: hi.name,
      away_id: ai.team_id, away_code: ai.code, away_name: ai.name,
      home_score: f.home_score ?? null, away_score: f.away_score ?? null,
      winner_id: w ? (teamByRec[w] || {}).team_id : null, winner_method: f.winner_method || null,
    });
  }
  matches.sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || ""));

  const standings = standRecs.map((r) => {
    const f = r.fields || {};
    const t = (f.team || [])[0];
    return { group: f.group, rank: f.rank, team_id: t ? (teamByRec[t] || {}).team_id : null,
      played: f.played, win: f.win, draw: f.draw, loss: f.loss,
      gf: f.goals_for, ga: f.goals_against, gd: f.goal_diff, points: f.points, form: f.form };
  }).filter((s) => s.team_id != null);
  standings.sort((a, b) => (a.group || "Z").localeCompare(b.group || "Z") || (a.rank || 99) - (b.rank || 99));

  const sgByRec = {};
  const sideGames = sideRecs.map((r) => {
    sgByRec[r.id] = (r.fields || {}).name;
    const f = r.fields || {};
    return { name: f.name, base_points: f.base_points, resolution_type: f.resolution_type,
      resolved_value: f.resolved_value || null, dark_horse_ladder: f.dark_horse_ladder || null };
  });

  // Predictions: full table once; reveal per player only after that player locks.
  const predRecs = await atList(env, "Predictions");
  const playerNames = playerRecs.map((r) => (r.fields || {}).name).filter(Boolean);
  const lockedAt = {};                       // name -> earliest locked_at stamp
  for (const r of predRecs) {
    const f = r.fields || {};
    const lbl = f.label || "";
    if (!f.locked_at) continue;
    for (const n of playerNames)
      if (lbl.startsWith(n + "|") && (!lockedAt[n] || f.locked_at < lockedAt[n])) lockedAt[n] = f.locked_at;
  }

  // Resolve the few linked footballers to names (only for locked players' picks).
  const footIds = [];
  for (const r of predRecs) {
    const f = r.fields || {};
    const owner = playerNames.find((n) => (f.label || "").startsWith(n + "|"));
    if (owner && lockedAt[owner] && (f.predicted_player || []).length) footIds.push(f.predicted_player[0]);
  }
  const footName = {};
  if (footIds.length) {
    for (const r of await atListByIds(env, "Footballers", footIds, ["name", "position", "shirt_number"]))
      footName[r.id] = (r.fields || {}).name;
  }

  const picks = {};
  for (const n of playerNames) if (lockedAt[n]) picks[n] = [];
  for (const r of predRecs) {
    const f = r.fields || {};
    const lbl = f.label || "";
    const owner = playerNames.find((n) => lbl.startsWith(n + "|"));
    if (!owner || !lockedAt[owner]) continue;           // unlocked players stay hidden
    const teamLink = (f.predicted_team || [])[0];
    const p = {
      key: lbl.split("|").slice(1).join("|"),
      type: f.prediction_type,
      bracket_slot: f.bracket_slot || null,
      side_game: (f.side_game || []).length ? (sgByRec[f.side_game[0]] || null) : null,
      match_id: (f.match || []).length ? (matchByRec[f.match[0]] ?? null) : null,
      team_id: teamLink ? (teamByRec[teamLink] || {}).team_id ?? null : null,
      player_name: (f.predicted_player || []).length ? (footName[f.predicted_player[0]] || null) : null,
      text: f.predicted_text || null,
      outcome: f.predicted_outcome || null,
      score_home: f.predicted_score_home ?? null,
      score_away: f.predicted_score_away ?? null,
      scalar: f.predicted_scalar ?? null,
      token: f.confidence_token || null,
      points: f.points_awarded ?? null,
      rival_bonus: f.beat_rival_bonus ?? null,
      resolved: !!f.resolved,
    };
    if (f.resolved && f.pundit_note) p.note = f.pundit_note;   // notes stay sealed until resolution
    picks[owner].push(p);
  }

  const players = playerRecs.map((r) => {
    const f = r.fields || {};
    return {
      name: f.name, color: f.display_color || null,
      total_score: f.total_score ?? 0,
      tokens: { Double: f.tokens_remaining_double ?? null, Triple: f.tokens_remaining_triple ?? null,
        AllIn: f.tokens_remaining_allin ?? null },
      mulligans: f.mulligans_remaining ?? null,
      locked: !!lockedAt[f.name], locked_at: lockedAt[f.name] || null,
    };
  });

  return { generated_at: new Date().toISOString(), players, teams, matches, standings, sideGames, picks };
}

// ---- router ----------------------------------------------------------------
export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  try {
    if (!env.AIRTABLE_PAT || !env.AIRTABLE_BASE_ID)
      return json({ error: "server not configured (missing AIRTABLE_PAT / AIRTABLE_BASE_ID)" }, 500);

    // Public, tokenless, cache-friendly (60 s at the edge/browser softens Airtable's 5 rps).
    if (url.pathname.replace(/\/+$/, "").endsWith("/api/public") && request.method === "GET")
      return json(await publicView(env), 200, { "Cache-Control": "public, max-age=60" });

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
