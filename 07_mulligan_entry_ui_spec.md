# Mulligan Entry — UI + Server Guard Spec (sketch)

**Status: DESIGN SKETCH, 2026-06-24. Build target: before the window opens (June 26).** Implements the v1.1 mulligan (bracket slot **or** Dark Horse) in the existing `pickentry_server.py` + client entry pattern. Scoring is already done and tested (`tests/test_mulligan_darkhorse.py`); this is the missing *entry* path.

## Scope

The mulligan is the one pick-entry flow never built — the handoffs always slated it for ~June 26 because the window can't open earlier. It must:

- Let a player spend their **one** mulligan to re-pick **one** target: any bracket slot (R16/QF/SF/Finalist/Champion) **or** their Dark Horse.
- Enforce eligibility and consume the mulligan irreversibly.
- Be live **only during the window** (June 26–28, tentative on FIFA's draft schedule — keep the dates in config, not hardcoded).
- Reuse what already exists: `bracket_guard` (nesting + dedupe), the `dark_horse_eligible` rule (`fifa_ranking > 16`), the `RuntimeError`-fragment guard style, and the full-replace `save` discipline.

## Data already in place

- `PoolPlayers.mulligans_remaining` (starts at 1).
- `Mulligans` table: `pool_player`, `used_at`, `original_prediction`→Predictions, `new_prediction`→Predictions, `note`.
- `Teams.fifa_ranking`, pinned to the **11 June 2026 edition** in `data/team_meta_2026.json` (`ranking_edition: "2026-06-11"`) → 33 Dark-Horse-eligible teams. This is the frozen list the eligibility guard reads; it must not drift if `team_meta` is ever re-backfilled mid-tournament. This is the edition the players based their original Dark Horse picks on — at the 16/17 boundary, **USA (17th) is eligible** and **Uruguay (16th) is not**. The rank values were already correct in the data; only the `ranking_edition` label was previously mis-set to 2026-06-10 (fixed 2026-06-24), so **no Airtable re-backfill is needed** — `Teams.fifa_ranking` already holds these values.

## UX flow (three steps, one screen)

**Step 1 — choose the target.** Show the player's mulligan-eligible picks as a single-select list: each bracket slot with its current team, plus the Dark Horse with its current team. Radio selection — exactly one. Group visually: "Bracket ladder" then "Dark Horse." A spent-mulligan state replaces the whole screen with a read-only record of what was swapped.

**Step 2 — choose the replacement.**
- *Bracket slot:* team picker constrained to that tier; the would-be full bracket is re-validated by `bracket_guard` (nesting + within-round dedupe) so the swap can't produce an illegal bracket.
- *Dark Horse:* team picker **filtered to the eligible pool** (rank > 16, pinned edition). Optionally attach one **unspent** confidence token (v1.1 allows it; locks at use). Original's token, if any, is untouched.

**Step 3 — confirm.** Spell out the irreversible consequences before commit:
- Both the original (now invalidated) and the replacement score at **50%**.
- The swap is **visible to your opponent the instant you confirm.**
- This **consumes your one mulligan** — no take-backs.

## Server guard — `mulligan_guard(player, target_rec, replacement, token)`

Mirrors `bracket_guard`: validate everything, raise `RuntimeError(fragment)` on the first violation, write nothing until it passes.

- **Window:** server-clock date ∈ config window, else `"mulligan window is not open"`.
- **Budget:** `mulligans_remaining > 0`, else `"mulligan already used"`.
- **Ownership:** `target_rec` is one of *this player's* own predictions and is mulligan-eligible (`prediction_type ∈ {bracket_slot, dark_horse}`), else `"… is not a mulligan-eligible pick"`.
- **No-op:** replacement team ≠ original team, else `"replacement is identical to the original pick"`.
- **Dark Horse eligibility:** replacement code in `dark_horse_eligible(meta)` (rank > 16, pinned edition), else `"{code} is not Dark-Horse-eligible (FIFA rank ≤ 16)"`.
- **Bracket-slot legality:** re-run `bracket_guard` on the player's pick set *with the swap applied* — reuses every nesting/dedupe rule for free.
- **Token:** if a token is attached, it must come from unspent inventory (same budget check `save_bonus`/`save` use), else `"token budget exceeded"`. Dark-Horse-only in practice but enforce generally.

## Writes — `save_mulligan(player, target_rec, replacement, token, note)`

Airtable has no transactions, so order writes for safe retry on partial failure:

1. **Create the replacement Prediction** (`dark_horse` or `bracket_slot`), `locked_at = now`, token attached if any. (An orphaned new pred that isn't linked yet is harmless — a retry re-links.)
2. **Create the `Mulligans` row** linking `original_prediction=[target_rec]`, `new_prediction=[new_rec]`, `used_at=now`, `note`.
3. **Decrement `mulligans_remaining` → 0** (last, so a crash before this leaves the budget spendable and the half-written swap re-doable).

The original prediction is **left in place** — the scoring engine reads the `Mulligans` row and halves both sides via `mulligan_affected` / `finalize_points`. No engine change; no recompute trigger needed beyond the normal poll cycle.

## Scoring interaction (done — for reference)

`scoring_engine.mulligan_affected()` collects both linked records type-agnostically; `finalize_points()` applies token-then-halve with `int(round())`. Covered by `tests/test_mulligan_darkhorse.py` (71 assertions, incl. dark_horse SF/Champion, All-In ordering, round-half-to-even, and pre-refactor equivalence).

## Edge cases to handle

- **Busted original** (e.g. a Dark Horse knocked out in groups): replacement still scores at 50%; original scores 50% × 0 = 0. Nothing special needed — just don't block a mulligan because the original already resolved to 0.
- **Double-submit / race:** the budget check + decrement guard against spending twice; make the decrement conditional (only if currently 1).
- **Window drift:** FIFA's R32 dates may move; the window is config so it can track the real schedule.
- **Edition drift:** pin eligibility to `ranking_edition` read at guard time, not whatever `team_meta` currently holds.

## Build checklist (before June 26)

1. `mulligan_guard()` + `save_mulligan()` in `pickentry_server.py`; new `do_POST` action `"mulligan"`.
2. Import/repoint `dark_horse_eligible()` (currently in `backfill_team_meta.py`) so the guard and the client share one eligibility source.
3. Client: target list → replacement picker (eligibility-filtered for Dark Horse) → confirm modal with the three consequences.
4. Extend `tests/test_pickentry_guard.py` with `mulligan_guard` cases: window closed/open, budget exhausted, non-eligible Dark Horse team, no-op re-pick, token-budget overflow, and a bracket-slot swap that breaks nesting.

## Open questions for Cal

- Confirm the exact window dates once FIFA publishes the R32 schedule.
- Eligibility = the **11 June 2026** FIFA edition (the one the original picks were based on; USA eligible, Uruguay not). Now consistent across the spec, the data label, and this doc.
