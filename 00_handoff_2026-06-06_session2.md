# Session Handoff — 2026-06-06, session 2

**Read this first.** Supersedes `00_handoff_2026-06-06.md` (which supersedes both June-5 files).
Kickoff is **2026-06-11 — 5 days out.** Pre-kickoff stack remains fully built and deployed;
this session added the **public read-only live board** (was priority 1).

---

## What this session accomplished

1. **`GET /api/public`** added to `functions/api/[[route]].js` — the only tokenless route.
   Returns players (scores, token reserves, lock status — **never** `magic_link_token`),
   teams, all matches with scores/status/winner, group standings, side games incl.
   `resolved_value`, and each player's picks. Reveal rules enforced server-side:
   - A player's picks appear **only after that player locks** (same promise the pick-entry UI makes).
   - `pundit_note` rides along **only once `Predictions.resolved` is checked**.
   - Linked footballers resolved to names via targeted `RECORD_ID()` lookups (no 1,248-row page-through).
   - `Cache-Control: public, max-age=60` to soften Airtable's 5 rps under public traffic.

2. **`site/live.html`** — the public board, same aesthetic as pick-entry/mockups. Five tabs:
   - **Scoreboard** — live/up-next/latest matches with both players' pick chips (✓/✗/pts), plus a
     points-by-category table (match / bracket / side / dark horse / beat-rival).
   - **Group matches** — all 72 fixtures grouped A–L, both calls side by side, ◎ = exact-score hit.
   - **Brackets** — tier-by-tier ladder compare (Champion → R16), split background where both picked
     the same team, token marks, shared-pick counts, Dark Horse cards. (The knockout *tree* view from
     mockup 05 becomes buildable once the draw exists, ~June 26 — ladders are the honest pre-draw view.)
   - **Side bets** — answers side by side, resolved values, revealed pundit notes.
   - **Standings** — 12 group tables from the `Standings` table.
   - Auto-refreshes every 90 s + on tab refocus. **`?demo=1`** renders an offline synthetic payload —
     open `site/live.html?demo=1` in a browser to eyeball it without the API.

3. **Pick-entry fixes**: Champion label corrected **100 → 150 pts** (was stale vs the locked v1.0
   spec), and the lock hint now links to `/live.html`.

### Verification (sandbox has no network — see environment note in prior handoff)
- Function syntax-checked as an ES module.
- `/api/public` integration-tested against a **stubbed Airtable** through the real router:
  19 checks — token/PAT leak audit, unlocked-player hiding, sealed/revealed notes, shapes.
- `live.html` pure functions unit-tested (24 checks) and all five tabs render-tested under a
  stub DOM with the demo payload (40 checks). All green.

---

## ⚠ Blocked: git commit (stale lock)

`.git/index.lock` (0 bytes, created ~23:01 June 6) exists and the Cowork sandbox **cannot delete
it** ("Operation not permitted" across the mount). Nothing is committed from this session yet.

**Andreas — on your Mac:**
```
rm ~/Desktop/WorldCup2026/.git/index.lock
```
then commit & push (GitHub Desktop is fine). The working tree holds, ready to go:
- `functions/api/[[route]].js` (modified — /api/public)
- `site/live.html` (new), `site/index.html` (modified — 150 pts + link)
- `03_Scoring_spec_v1.0.md` + `WC2026_Scoring_Spec_v1.0.pdf` (new), `03_Scoring_spec_v0.1.md` (deleted)
- `scripts/scoring_engine.py` (comment fix), `00_handoff_2026-06-06.md` + this file

Pages auto-deploys on push; the board goes live at
**`https://kumachan-skurven-wc2026.pages.dev/live.html`** — shareable, no token needed.

---

## Outstanding — Andreas's actions

1. **Clear the git lock, commit, push** (above).
2. **Send Cal his link** (`…/?p={cal-token}` from `PoolPlayers`) if not already done.
3. **Both: enter and LOCK picks before 2026-06-11.**
4. After push: open `…/live.html` once to sanity-check the real (pre-lock) state — expect the
   "picks appear as players lock" notice and empty standings. Optionally also `…/live.html?demo=1`.
5. *(Optional, from last session)* delete the stray "S" option on `Teams.group` in Airtable.

---

## Next-session priorities

1. **Side-game auto-resolution** (now top of the list) — fill `SideGames.resolved_value`
   automatically: Golden Boot via `/players/topscorers`, first red/own goal via `events_json` scan,
   per-group top scorers, running total-goals. Scoring engine already consumes `resolved_value`.
2. **Knockouts (~June 26)** — re-run `load_fixtures.py` for knockout fixtures; fill
   `ROUND_TIER_OVERRIDES` in `scoring_engine.py` with exact round strings; consider upgrading the
   Brackets tab to the real tree (mockup `05_mockup_bracket.html` is the blueprint, and
   `/api/public` already carries everything it needs).
3. *(Optional)* bonus-bet entry, knockout match-outcome picks, custom subdomain, Cloudflare Access.

## Open questions (carried)

- Bonus bets in/out for this tournament.
- Dark Horse display lives on the Brackets tab of the live board (and Knockouts tab of pick-entry) — fine?
- Custom subdomain vs `pages.dev`.

## What I'd do first next session

Confirm the push landed and `…/live.html` renders against the real base, then start
**side-game auto-resolution** (priority 1).
