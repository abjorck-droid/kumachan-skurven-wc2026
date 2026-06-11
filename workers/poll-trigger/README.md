# poll-trigger Worker — setup (one-time, ~5 minutes, all in the browser)

Dispatches `scoreboard-poll.yml` every 15 minutes via Cloudflare's cron (punctual),
replacing reliance on GitHub's `schedule:` cron (best-effort; fired ~9×/day on opening
day instead of 96×). This file is the canonical copy; the deployed Worker lives in the
Cloudflare dashboard.

## 1. Create the GitHub token (fine-grained PAT)

GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token

- **Repository access:** Only select repositories → `kumachan-skurven-wc2026`
- **Permissions:** Repository permissions → **Actions: Read and write**. Nothing else.
- **Expiration:** 2026-07-31 (just past the final — token dies with the tournament)

Copy the token; it's shown once.

## 2. Create the Worker

Cloudflare dashboard (same account as the Pages site) → Workers & Pages →
Create → Worker → name it `wc2026-poll-trigger` → Deploy the hello-world,
then **Edit code** → replace everything with `worker.js` from this folder → Deploy.

## 3. Add the secret

Worker → Settings → Variables and Secrets → Add → type **Secret**,
name `GH_PAT`, value = the token from step 1.

## 4. Add the cron trigger

Worker → Settings → Trigger Events → Add → Cron Trigger → `*/15 * * * *`.

## 5. Verify (takes one cycle)

Within ~15 min the repo's Actions page should show a `scoreboard-poll` run with
event **workflow_dispatch** (GitHub-cron runs say "Scheduled"). After two ticks
~15 min apart, the local poll loop on the Mac is redundant — Ctrl-C it.

Failures (bad token, GitHub down) throw, so they show up in the Worker's
dashboard under Metrics → Errors; logs via Worker → Logs → Begin log stream.

## Notes

- API-Football budget: paid plan, 7,500 req/day. 96 dispatches/day × (1 fixtures
  call + 1 events call per live/finished match) ≈ 200–900/day worst case. Plenty.
- `leaderboards-poll.yml` stays on GitHub's daily cron — daily schedules have
  been firing fine, and standings aren't latency-sensitive.
- The workflow keeps its `schedule:` block as a free backup heartbeat; the
  `concurrency: scoreboard-poll` group prevents overlapping runs.
- The Worker self-skips outside 2026-06-10 → 2026-07-21, so it can stay
  installed after the final without burning anything; delete it (and let the
  PAT expire) whenever.
