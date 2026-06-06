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

4. **Side-game auto-resolution** (was priority 2, also done this session).
   **`scripts/resolve_sidegames.py`** — Airtable-only (no API-Football key; reads the
   `events_json` the poller already stores). Resolves, with conservative timing rules:
   - **First Red Card / First Own Goal** — earliest qualifying event, final only once its match
     is Finished AND every match kicking off at/before it is Finished (VAR-safe, handles
     simultaneous kickoffs; straight red or second yellow both count as "red").
   - **Top Scorer Group A–L** — once all 6 of a group's fixtures are Finished. Own goals and
     missed penalties excluded.
   - **Golden Boot** — once the Final is Finished. Goals, tie-break assists (from goal events),
     still tied → joint. **Total Tournament Goals** — once every fixture is Finished; extra-time
     goals count, shootout kicks don't.
   - **Write-once**: never overwrites an existing `resolved_value` (protects manual entries);
     `--force` to recompute. `--dry-run` / `--verbose` as usual. Player names canonicalized via
     the `Footballers` table so they string-match what the pick dropdowns saved.
   - **Engine patch**: joint winners are written `"Name | Name"`; `scoring_engine.py` got
     `rv_winners()`/`side_game_hit()` so each side of the pipe pays. Scalar path untouched.
   - **Workflow**: `scoreboard-poll` is now poll → **resolve** → score, every 15 min.

5. **Pool decisions locked (2026-06-06):** scorer ties resolve **FIFA-style for Golden Boot**
   (goals → assists → joint) and **joint for per-group top scorers**; **Golden Glove stays
   manual** (needs lineups, partly judged — Andreas types it at tournament end). **Dark Horse**
   needs no `resolved_value` (engine computes its ladder directly).

### Verification (sandbox has no network — see environment note in prior handoff)
- Function syntax-checked as an ES module.
- `/api/public` integration-tested against a **stubbed Airtable** through the real router:
  19 checks — token/PAT leak audit, unlocked-player hiding, sealed/revealed notes, shapes.
- `live.html` pure functions unit-tested (24 checks) and all five tabs render-tested under a
  stub DOM with the demo payload (40 checks). All green.
- `resolve_sidegames.py` + engine patch: 47 checks — event parsing/classification, the
  first-event finality rule (live/VAR/simultaneous-kickoff cases), group-complete gating,
  tally exclusions, FIFA tie-break, end-to-end `compute_resolutions` pre/post-Final, and the
  engine's joint-winner matching. All green.

---

## ⚠ Sandbox + git: don't mix

Any git **write** from the Cowork sandbox (`add`/`commit`) leaves a stale `.git/index.lock` it
cannot delete ("Operation not permitted" on unlink across the mount). It bit us twice today.
**Rule going forward: Claude never runs git writes; Andreas commits/pushes via GitHub Desktop.**

State as of end of session: the **public-view batch is already committed & pushed** by Andreas
(`81043e4 "Public view update"`). The **side-game batch is staged but NOT committed**, and a
fresh stale lock exists. **Andreas — on your Mac:**
```
rm ~/Desktop/WorldCup2026/.git/index.lock
```
then commit & push (GitHub Desktop). In the batch:
- `scripts/resolve_sidegames.py` (new)
- `scripts/scoring_engine.py` (joint-winner support: `rv_winners`/`side_game_hit`)
- `.github/workflows/scoreboard-poll.yml` (poll → resolve → score)
- this handoff (updated)

---

## Outstanding — Andreas's actions

1. **Clear the git lock again, commit, push** (above).
2. **Send Cal his link** (`…/?p={cal-token}` from `PoolPlayers`) if not already done.
3. **Both: enter and LOCK picks before 2026-06-11.**
4. Sanity-check `…/live.html` against the real base (expect the "picks appear as players lock"
   notice pre-lock); `…/live.html?demo=1` shows it fully populated.
5. *(Optional, carried)* delete the stray "S" option on `Teams.group` in Airtable.

---

## Next-session priorities

1. **Knockouts (~June 26, after the draw)** — re-run `load_fixtures.py` for knockout fixtures;
   fill `ROUND_TIER_OVERRIDES` in `scoring_engine.py` with the exact knockout round strings
   (doc-01's last open item — also feeds `resolve_sidegames.py`, which imports `round_tier`);
   consider upgrading the live board's Brackets tab to the real tree (mockup
   `05_mockup_bracket.html` is the blueprint; `/api/public` already carries everything needed).
2. **First-poll-day watch (June 11)** — eyeball the first real `scoreboard-poll` runs: poller →
   resolver → engine all writing, live board updating. The resolver prints "pending" rows with
   `--verbose` if you want a local check: `python3 scripts/resolve_sidegames.py --dry-run --verbose`.
3. *(Optional)* bonus-bet entry, knockout match-outcome picks, custom subdomain, Cloudflare Access.

## Open questions (carried)

- Bonus bets in/out for this tournament.
- Dark Horse display lives on the Brackets tab of the live board (and Knockouts tab of pick-entry) — fine?
- Custom subdomain vs `pages.dev`.

## What I'd do first next session

Nothing is buildable before the knockout draw that isn't optional — so: confirm the side-game
batch pushed, watch the June-11 first polls, and pick from the optional list (bonus bets being
the most game-relevant) or rest until the draw.
