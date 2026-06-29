// poll-trigger — Cloudflare Worker cron that dispatches the GitHub Actions polls.
//
// Why this exists: GitHub's own `schedule:` cron is best-effort and heavily
// throttled for low-activity repos — on 2026-06-11 (opening day) it fired
// ~9×/day instead of 96×/day, leaving the live board stale through kickoff.
// Cloudflare cron triggers are punctual, so the Worker provides the heartbeat
// and GitHub Actions stays the executor (keys, runner, scripts all unchanged).
// Each workflow keeps its own cron as a free backup; the `concurrency` groups
// dedupe if both fire close together.
//
// Dispatches:
//   • scoreboard-poll   — every tick (15 min): live fixtures/scores/events.
//   • leaderboards-poll — once daily on the ~04:00 UTC tick: group standings,
//     which feed the live board's 3rd-place elimination logic. Wiring it through
//     the punctual Worker (rather than GitHub's best-effort daily cron) keeps the
//     "out of tournament" marking from going stale.
//
// Setup: see README.md next to this file. One secret required: GH_PAT.

const REPO = "abjorck-droid/kumachan-skurven-wc2026";
const SCOREBOARD = "scoreboard-poll.yml";
const LEADERBOARDS = "leaderboards-poll.yml";
// Self-skip outside the tournament (matches poller.py's window, plus grace
// for late resolutions). Cheap to keep the trigger installed year-round.
const WINDOW_START = "2026-06-10T00:00:00Z";
const WINDOW_END = "2026-07-21T23:59:59Z";

// Fire one workflow_dispatch. GitHub answers 204 No Content on success; anything
// else throws so the failure surfaces in the Worker's dashboard metrics/logs
// instead of rotting silently — the exact failure mode this Worker exists to fix.
async function dispatch(workflow, env) {
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GH_PAT}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "wc2026-poll-trigger",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );
  if (res.status !== 204) {
    const body = await res.text();
    throw new Error(`${workflow} dispatch failed: HTTP ${res.status} — ${body.slice(0, 300)}`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date();
    if (now < new Date(WINDOW_START) || now > new Date(WINDOW_END)) return;

    const errors = [];
    // Scoreboard every tick.
    try { await dispatch(SCOREBOARD, env); }
    catch (e) { errors.push(String((e && e.message) || e)); }

    // Leaderboards once per day, on the single tick at ~04:00 UTC (the */15 cron
    // fires at :00/:15/:30/:45, so minute < 15 matches exactly one tick per hour,
    // and hour === 4 narrows it to once daily). The workflow keeps its own daily
    // `schedule:` as a backup if this tick is ever missed.
    if (now.getUTCHours() === 4 && now.getUTCMinutes() < 15) {
      try { await dispatch(LEADERBOARDS, env); }
      catch (e) { errors.push(String((e && e.message) || e)); }
    }

    // Surface either dispatch's failure (without one masking the other).
    if (errors.length) throw new Error(errors.join(" | "));
  },
};
