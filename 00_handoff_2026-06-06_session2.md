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

6. **Bonus bets are IN** (open question closed; second decision: **tokens MAY ride bonus bets**,
   spec-faithful, shared 7-token budget). Full flow built across every layer:
   - **Function `/api/savebonus`** (token-auth) — stays open after tournament lock, gated
     **per match by kickoff** (server-side). Full-replace semantics for not-yet-started matches
     (cleared slots are deleted via a new `atDelete`); started matches immutable. Token budget
     enforced across ALL of the player's predictions (400 on overspend). `/api/save` now counts
     bonus-row tokens when recomputing reserves. Bet menu (binary Yes/No; "No" on Over 2.5 =
     Under): BTTS 10 · Over/Under 2.5 10 · Penalty 15 · Red card 20 · Both score 2+ 15 ·
     Goal in first 15′ 15.
   - **`/api/public`** — bonus picks stay sealed until their match kicks off, even for locked
     players (the blind co-participation game depends on it); bet fields serialized after.
   - **Engine** — `bonus_actuals()` from `events_json` (missed pen = awarded; VAR-cancelled ≠
     awarded; shootout kicks never count; own goal counts for "goal in first 15′"),
     `score_bonus()`, and the **co-participation rule**: a match's bonus bets only score if both
     players attached ≥1 bet; one-sided opt-ins resolve void (0). No Beat-Rival on bonus bets;
     tokens/mulligan apply normally.
   - **Pick-entry** — new **Bonus bets** tab (chronological, knockouts included once loaded,
     group-matches tab now filters group rounds since bootstrap returns all fixtures). Exempt
     from the locked-UI freeze; per-slot bet-type + Yes/No (Over/Under labels), token + pundit
     note; own "Save bonus bets" button; started matches shown as a read-only recap.
   - **Live board** — bonus chip line under match rows once revealed: hit/miss/points, gold
     token marks, dashed **void** styling when co-participation failed; "Bonus bets" row added
     to points-by-category.
   - **`pickentry_server.py`** — full parity port (savebonus, all-fixtures bootstrap, shared
     token recount), so local mode keeps matching hosted.

7. **Both mockups are now live** (Andreas's call, same session):
   - **Match cards (mockup 04 → live).** The live board's Scoreboard and Group-matches tabs now
     render full match cards: status pill (Open/Locked/Live/Final), venue + kickoff + countdown
     ("Kicks off in 2d 14h"), kit-bar matchup with big score, **live minute** (new
     `Matches.elapsed`, see actions below), two-column prediction cells (predicted score +
     advancer, outcome verdict, token chip with spent state, **pundit notes** — revealed in the
     handwritten font, or shown as "sealed" via a new `has_note` boolean that never leaks
     content), **Beat-rival flag**, and the bonus strip (opt-in dots pre-kickoff → revealed bets
     with ✓/✗/+pts → void styling). Header gained **streak chips** (▲ N right / ▼ N wrong).
   - **Bracket tree (mockup 05 → live).** The Brackets tab now has a **Tree / Ladders toggle**.
     The tree renders the official FIFA 2026 template (matches 73–104, source labels like
     "RU A" / "3rd A/B/C/D/F"), SVG wires, Fit/100% zoom, mobile stacked view, and
     **{P1}/{P2}/Compare** modes. Chips fill from knockout fixtures via
     **`site/bracket_map_2026.json`** (fixture_id → FIFA match number; kickoff-order fallback
     until it's filled at draw time). Highlights come from **ladder-set membership** (a team
     lights up in a round if the player picked it to reach the next round), tokens ride the
     deciding chip, finished matches check the winner. Ladders remain the pre-draw default;
     tree auto-defaults once knockout fixtures exist.
   - **Poller** writes `Matches.elapsed` in a separate tolerant upsert — if the field doesn't
     exist yet it prints a warning and the score write is untouched.

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
- Bonus bets: `/api/savebonus` integration-tested through the real router with a mutable
  Airtable stub (17 checks — kickoff gating, validation, slot-clearing deletes, cross-prediction
  token budget, public reveal sealing); engine `bonus_actuals`/`score_bonus` (22 checks);
  pick-entry render + collect logic under a stub DOM (15 checks); live board re-render suite
  incl. void state (45 checks). Earlier suites re-run green after every change.
- Match cards + bracket tree: pure functions (streaks, round labels, knockout round mapping,
  bracket-map fallback, ladder sets — 16 checks) and a full stub-DOM render pass over every tab
  incl. the built tree (66 checks: card chrome, live minute, sealed notes, beat flag, template
  sources, mapped fixtures, winner checks, token tags, highlight classes). Whole suite (7 test
  files) re-run green at the end.

---

## ⚠ Sandbox + git: don't mix

Any git **write** from the Cowork sandbox (`add`/`commit`) leaves a stale `.git/index.lock` it
cannot delete ("Operation not permitted" on unlink across the mount). It bit us twice today.
**Rule going forward: Claude never runs git writes; Andreas commits/pushes via GitHub Desktop.**

State as of end of session: the **public-view batch is already committed & pushed** by Andreas
(`81043e4 "Public view update"`). The **side-game + bonus-bet work is NOT committed**, and a
stale lock exists. **Andreas — on your Mac:**
```
rm ~/Desktop/WorldCup2026/.git/index.lock
```
then commit & push everything (GitHub Desktop). In the batch:
- `scripts/resolve_sidegames.py` (new) and `.github/workflows/scoreboard-poll.yml`
  (poll → resolve → score)
- `scripts/scoring_engine.py` (joint winners + full bonus-bet scoring)
- `functions/api/[[route]].js` (`/api/savebonus`, all-fixtures bootstrap, public sealing,
  `elapsed` + `has_note`)
- `site/index.html` (Bonus bets tab), `site/live.html` (bonus display + match cards + bracket
  tree), `site/bracket_map_2026.json` (new, empty until the draw)
- `scripts/pickentry_server.py` (parity port), `scripts/poller.py` (live minute)
- this handoff (updated)

---

## Outstanding — Andreas's actions

1. **Clear the git lock again, commit, push** (above).
2. **Add a Number field named `elapsed` to the `Matches` table** in the Airtable UI (one click;
   needed for live minutes on match cards — the poller warns but keeps working without it).
2b. **New player accent colors** (Coolors palette, decided end of session): Andreas =
   **blue green `#219EBC`**, Cal = **tiger orange `#FB8500`**. CSS defaults, demo data, and the
   both-agree gradients are updated in `site/live.html` + `site/index.html` — but
   **`PoolPlayers.display_color` in Airtable overrides the CSS on the live board**, so update
   those two fields (or clear them) to make it real. Known trade-off: orange is now kin to the
   gold token color (~12° apart); they touch on token tags over Cal-colored slots. Accepted.
3. **Send Cal his link** (`…/?p={cal-token}` from `PoolPlayers`) if not already done.
4. **Both: enter and LOCK picks before 2026-06-11.**
5. Sanity-check `…/live.html` against the real base (expect the "picks appear as players lock"
   notice pre-lock); `…/live.html?demo=1` shows everything populated — cards, bonus strips,
   streaks, and the bracket tree with a mapped semi-final.
6. **At draw time (~June 26):** after `load_fixtures.py` pulls the knockout fixtures, fill
   `site/bracket_map_2026.json` (`fixture_to_match`: fixture_id → FIFA match number 73–104) and
   push — the tree places fixtures by kickoff-order fallback until then.
7. *(Optional, carried)* delete the stray "S" option on `Teams.group` in Airtable.

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

- Dark Horse display lives on the Brackets tab of the live board (and Knockouts tab of pick-entry) — fine?
- Custom subdomain vs `pages.dev`.
- One schema nicety: the seeded `Predictions.bonus_bet_type` select options predate the final
  menu ("BTTS"/"Over 2.5"/"Under 2.5"/…). Writes use `typecast: true`, so the new option names
  ("Over 2.5 goals", "Goal in first 15 min", …) auto-create on first save; the stale unused
  options can be deleted in the Airtable UI whenever (cosmetic only — like the old "S" group).

## What I'd do first next session

Everything pre-kickoff is now built: poller, scorer, side-game resolver, pick entry, bonus bets,
public board. Confirm the push landed, then watch the June-11 first polls. The next real build
is the **knockout draw work (~June 26)**; before that, only sanity checks and pile-on polish.
