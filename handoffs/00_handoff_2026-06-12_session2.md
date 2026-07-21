# Session Handoff — 2026-06-12 (session 2)

**Read this first.** Supersedes `00_handoff_2026-06-12.md` (morning). Tournament live, day 2 done.
Pipeline autonomous (CF Worker heartbeat — see the 06-12 morning handoff for infrastructure facts).

## Fixed this session: duplicated/stale Standings tables on live.html

**Symptom**: Standings tab showed 12 stale all-zero group tables (A–L) on top, live tables
("Stage - A"…) duplicated below, plus stray aggregate tables. 120 rows in Airtable instead of 48.

**Root cause**: API-Football renamed its standings group strings when play started —
`"Group A"` pre-tournament → `"Group Stage - Group A"` on matchday 1 (verified against the raw
feed). The poller's upsert keyed on `label = f"{raw group name}:{team_id}"`, so the rename
orphaned every pre-tournament row instead of updating it. The old `.replace("Group ", "")`
stripped *both* occurrences, hence the `"Stage - A"` group values seen in Airtable.

**Fix (all deployed and verified on the live board — 48 rows, 12 clean tables):**

1. `poller.py: norm_group()` — reduces any API naming variant to a stable key: `A`–`L` for
   groups, `3rd` for the third-place ranking, `None` (skipped) for aggregates like the 12-row
   "Group Stage" winners table. Labels are now `A:25`-style — immune to future renames.
2. `run_leaderboards` now **prunes** Standings rows whose label the API no longer publishes,
   after each upsert. Guarded: an empty API response never wipes the table. Self-heals any
   future rename. Prints skipped table names per run.
3. `live.html standingsTab` filters to `A`–`L` + `3rd` defensively and renders the third-place
   ranking as its own card ("top 8 advance", qualification line under rank 8 via `tr.cut`).
4. Tests: `tests/test_poller_standings.py` (17 checks — incl. the literal 2026-06-12 feed
   string and label stability across both naming eras).

**Thirds caveat**: API-Football currently does NOT publish the "Ranking of third-placed teams"
table (the 12 rows we had were pre-tournament placeholders; pruned now). The feed today has 13
tables: 12 groups + the skipped "Group Stage" aggregate. The thirds card and `3rd` rows appear
automatically once the API republishes it — **scheduled reminder set for June 24** to verify it's
back before the mulligan/R32 window (June 26–28). If it isn't, R32 qualification needs a fallback
(compute thirds ranking ourselves from group tables — FIFA tiebreakers: pts, GD, GF, …).

## New this session: "still alive" indicator v1 (was on the June 26–28 list)

`live.html: eliminatedSet(D)` — in the PURE block, tested. **Conservative: only marks a team out
when mathematically certain.** Rules: (1) rank 4 in a finished group (all four rows played 3);
(2) rank 3 only when ALL groups are finished AND the API thirds ranking says rank > 8 — no thirds
table → no third marked out; (3) lost a finished knockout match (3rd-place playoff harmless —
both teams already out). No mid-group maths, so no false positives while a team can still qualify.

Surfaced everywhere on the Brackets tab:

- **Ladders** (`ttag`): red strikethrough + "✕ out" chip on unresolved picks; resolved picks keep
  hit/miss styling untouched.
- **Tree + narrow stack** (`bkChip`): losers of finished KO matches are struck; a "✕" is added
  when a player had picked that team to advance and the pick is still open. Champion box
  (`bkChampion`) strikes a dead picked champion with "✕ out" in all three modes. Note the tree
  can only mark dead picks on teams that appear in real fixtures — a team eliminated in an
  earlier round never reaches the later chip, so the per-tier truth lives in the Ladders view.
- **Both views**: a `bk-deadnote` line under the toolbar — "✕ N picks can no longer score" —
  via pure `deadPickCount()` (counts open bracket_slot + dark_horse picks on eliminated teams),
  pointing at the Ladders view from the tree. Dark Horse card shows "✕ out" + "+N — final".

Tests: `tests/test_live_alive.mjs` (25 checks) — extracts the PURE block from live.html via the
PURE-START/PURE-END markers, plus `bkChip`/`bkChampion` rendering via function extraction; first
test coverage for live.html logic, pattern reusable.

Full suite: 153/153 across 6 files (test_api_save 22, test_bracket_logic 57, test_consistency 13,
test_live_alive 25, test_poller_standings 17, test_pickentry_guard 19).

## Outstanding (carried)

1. **Cal heads-up** (from 06-11): bonus bets he entered after his re-lock were silently dropped
   pre-fix — he should re-enter under the fixed page. Status unknown.
2. UX hardening: confirm-dialog on locking incomplete set; sticky save-error banner; server-side
   lock guard on `/api/save`.
3. Airtable cosmetics: SideGames resolution_type/description, stray group select options (now
   also unused `Stage - A`…`Stage - L`; a `3rd` option appears via typecast when thirds return),
   `PoolPlayers.display_color`, Cal's magic link.
4. **June 26–28**: mulligan mechanics; knockout fixtures via `load_fixtures.py`; round names into
   `ROUND_TIER_OVERRIDES`; `site/bracket_map_2026.json` (still-alive tree marking is done).
5. Own-goal attribution sanity check on first real own goal.

## Gotchas (unchanged from morning handoff)

No sandbox network (local scripts for Airtable/API); no git from sandbox (GitHub Desktop);
`/api/public` truncates ~86 KB via web_fetch — **use Claude-in-Chrome JS fetch to verify live
data instead** (worked well this session: parse in-page, stash on `window`, read back);
edge cache 60 s (`?cb=` to bust); four bracket-template mirrors must stay in sync.

## What I'd do first next session

Check the June 24 reminder outcome if past that date. Otherwise: the hardening items.
Mulligan mechanics need agreeing with Cal before June 26.
