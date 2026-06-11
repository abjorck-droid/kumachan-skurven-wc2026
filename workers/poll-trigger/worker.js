// poll-trigger — Cloudflare Worker cron that dispatches the scoreboard-poll
// GitHub Actions workflow every 15 minutes.
//
// Why this exists: GitHub's own `schedule:` cron is best-effort and heavily
// throttled for low-activity repos — on 2026-06-11 (opening day) it fired
// ~9×/day instead of 96×/day, leaving the live board stale through kickoff.
// Cloudflare cron triggers are punctual, so the Worker provides the heartbeat
// and GitHub Actions stays the executor (keys, runner, scripts all unchanged).
// The workflow keeps its own cron as a free backup; the `concurrency` group
// in scoreboard-poll.yml dedupes if both fire close together.
//
// Setup: see README.md next to this file. One secret required: GH_PAT.

const REPO = "abjorck-droid/kumachan-skurven-wc2026";
const WORKFLOW = "scoreboard-poll.yml";
// Self-skip outside the tournament (matches poller.py's window, plus grace
// for late resolutions). Cheap to keep the trigger installed year-round.
const WINDOW_START = "2026-06-10T00:00:00Z";
const WINDOW_END = "2026-07-21T23:59:59Z";

export default {
  async scheduled(event, env, ctx) {
    const now = new Date();
    if (now < new Date(WINDOW_START) || now > new Date(WINDOW_END)) return;

    const res = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
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

    // GitHub answers 204 No Content on success. Throwing on anything else
    // surfaces the failure in the Worker's dashboard metrics/logs instead of
    // rotting silently — the exact failure mode this Worker exists to fix.
    if (res.status !== 204) {
      const body = await res.text();
      throw new Error(`workflow_dispatch failed: HTTP ${res.status} — ${body.slice(0, 300)}`);
    }
  },
};
