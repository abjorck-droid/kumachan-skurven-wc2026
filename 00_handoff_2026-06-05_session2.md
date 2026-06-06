# Session Handoff — 2026-06-05 (session 2, evening)

**Read this first.** It supersedes `00_handoff_2026-06-05.md` (the morning version). The four working
docs (01–04) and the bracket mockup (05) are still valid; where this session changed them, it's noted below.

Kickoff is **2026-06-11** — 6 days out. The pre-kickoff stack is now essentially built; what remains is
mostly *your* actions (GitHub setup, smoke tests) plus two optional polish items.

---

## What this session accomplished

1. **Bracket mockup (`05_mockup_bracket.html`)** — built the full official FIFA knockout tree (Matches 73–104)
   as a mirrored two-sided bracket, then iterated per your feedback:
   - Fixed the confidence-token badge overlapping the slot source label.
   - Rebuilt **Compare** as a neutral head-to-head (Andreas teal / Cal purple / split bar where they agree —
     no foreground/background framing). Andreas / Cal / Compare toggle.
   - **Zoom-to-fit is the default** (whole tree scales to the window), with a 100% toggle.
   - Teams shown are illustrative; structure + slot-source labels are the real FIFA pairings.

2. **API verification (`scripts/verify_api.py`)** — read-only spike. Confirmed the big uncertainty:
   **API-Football's free tier excludes the 2026 season.** Upgraded to **Pro ($19/mo, 7,500 req/day)** — now
   working (returns all 48 teams). Doc 01 updated with the correction. The free-tier rate-limit discipline is
   now moot.

3. **Airtable base (`scripts/create_base.py`)** — builds all tables via the meta API; **run for real, base now
   exists.** 9 tables (the 8 from doc 02 **plus a `Standings` table**), 13 linked-record fields, idempotent,
   dry-run. Seeded: PoolPlayers (Andreas, Cal w/ 4D·2T·1A + mulligan), 18 SideGames, and 48 real Teams.

4. **Poller (`scripts/poller.py` + `.github/workflows/`)** — `scoreboard` mode upserts the day's fixtures into
   `Matches` (scores, status, round, team links, winner) keyed on `fixture_id`, fetches `events_json` for
   live/newly-finished matches, logs to `PollLog`. `leaderboards` mode upserts `Standings`. Two GitHub Actions
   (every 15 min / daily) call it with repo secrets. Tournament-window self-guard.

5. **Pick-entry (`scripts/pickentry_server.py` + `site/index.html`)** — local server keeps the PAT server-side
   and proxies Airtable; serves a single guided flow (bracket slots → side games → Dark Horse → tokens →
   review/lock). Saves to `Predictions` (upsert on `Player|slot`), recomputes token reserves, lock stamps
   `locked_at`. Player-name side games are **free text in v1** (Footballers not yet populated).

All scripts are stdlib-only and verified (compile + unit-tested transforms/geometry). None could be run live
from Claude's sandbox — see the environment note below.

---

## Decisions locked this session

- **Data source:** API-Football **Pro** (not free). Confirmed working.
- **Compare view:** symmetric/neutral (no Andreas-centric default).
- **Bracket zoom:** fit-to-width default, 100% optional.
- **Schema:** events stored as **JSON in `Matches`** (no Events table); a **`Standings` table** IS included
  (you didn't take the "computed, no table" default).
- **Pick-entry:** single guided flow, wired to Airtable via a **local server** (PAT can't live in browser JS).
- **Player-name side games:** free-text for v1, pending a squad import.

---

## Environment note (important for whoever picks this up)

Claude's Cowork sandbox shell has **no outbound internet** (DNS fails for everything; only package mirrors work).
So API-Football / Airtable work **cannot run from Claude** — every script is built to run **locally on Andreas's
Mac** (which has internet + `.env.local`), exactly like the Dominion uploader. The production poller runs on
**GitHub Actions** (which has internet). Claude verifies scripts by compile + unit-testing pure functions, not by
executing them live.

---

## File inventory (this folder)

```
00_handoff_2026-06-05_session2.md   ← this file (latest)
00_handoff_2026-06-05.md            morning handoff (superseded)
01_API_findings.md                  updated: Pro required; knockout round strings still pending
02_Airtable_schema.md               schema (now also includes Standings table as built)
03_Scoring_spec_v0.1.md             unchanged
04_mockup_match_card.html           match-card aesthetic source
05_mockup_bracket.html              bracket mockup (token fix + neutral compare + zoom-fit)
.env.local                          API_FOOTBALL_KEY (Pro), AIRTABLE_PAT, AIRTABLE_BASE_ID  [gitignored]
.gitignore
.github/workflows/scoreboard-poll.yml
.github/workflows/leaderboards-poll.yml
data/round_names_2026.json          group rounds only so far (knockouts not yet in feed)
data/teams_2026.json                48 teams
scripts/verify_api.py               read-only API spike
scripts/create_base.py              base builder (already run)
scripts/poller.py                   live poller (scoreboard + leaderboards)
scripts/pickentry_server.py         local pick-entry server
site/index.html                     guided pick-entry UI
```

---

## Outstanding — Andreas's actions

1. **Smoke-test pick-entry** (highest priority): `python3 scripts/pickentry_server.py` → open the URL →
   confirm 48 teams load, make + save a couple picks, check they appear in the `Predictions` table.
2. **Delete the empty `Table 1`** left in the base by Airtable's default (UI only — no safe delete-table API).
3. **Stand up the poller:** create a GitHub repo (public recommended — code only; picks live in Airtable →
   unlimited Action minutes), add secrets `API_FOOTBALL_KEY` / `AIRTABLE_PAT` / `AIRTABLE_BASE_ID`, push, then
   hit "Run workflow" on `scoreboard-poll` once to confirm green. Optionally test locally first:
   `python3 scripts/poller.py --mode scoreboard --date 2026-06-11 --dry-run`.

---

## Next-session priorities (in order)

1. **Squad import** — small script (`/players?league=1&season=2026` paginated) to populate `Footballers`, then
   upgrade pick-entry's player-name side games from free-text to real dropdowns (→ `predicted_player` links).
2. **Deploy the public side** — bracket mockup + a read-only standings / H2H scoreboard view to Cloudflare Pages.
   Decide subdomain (`worldcup.<domain>` CNAME) vs the free `*.pages.dev`.
3. **Scoring engine** — compute `points_awarded` / `beat_rival_bonus` from resolved matches + predictions
   (per `03_Scoring_spec_v0.1.md`); runs after each poll. This is the next big build after picks are in.
4. **Lock the knockout round strings** — the one remaining doc-01 uncertainty. `/fixtures/rounds` only lists the
   3 group rounds today; re-run `verify_api.py` then `create_base.py` once knockout fixtures publish, to
   reconcile `Matches.round` options.

---

## Still-open questions (not blockers)

- **Champion bonus = 100**, Beat-Cal = +3, Total-goals = closest-without-going-over — all still as proposed in
  doc 03; Andreas & Cal to confirm or tweak.
- **Exact knockout round-name strings** (incl. whether the API says "Round of 32") — pending the feed.
- **Magic-link auth** for a hosted pick-entry (so Cal enters his own picks remotely) — the local server is the
  v1; revisit if/when we host it.
