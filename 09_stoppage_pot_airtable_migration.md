# Airtable Migration — "Stoppage Time" Pot (v1.2)

**Companion to `08_stoppage_time_amendment_proposal.md` (Variant A, adopted 2026-07-17).**
Migration is applied by `scripts/setup_stoppage_pot.py` — run **on the Mac** (no sandbox
network), `--dry-run` first. No scoring-engine, poller, or site changes; nothing to deploy.

## Design in one line

Pot rows are Predictions with `prediction_type = "stoppage_bet"` — a value the scoring
engine's dispatch doesn't recognize, so it never scores them and `total_score` stays clean
(verified against `scoring_engine.py:404ff`: unknown types fall through with 0 points).
Pot scoring is manual in a new `pot_points` field; the script's `--tally` mode sums pots
and prints the margin conversion.

## Schema changes

| Table | Change |
|---|---|
| Predictions | + `pot` (single select: "stoppage") — human filter for views |
| Predictions | + `pot_points` (number) — manual score per pot bet, token-multiplied |
| Predictions | `prediction_type` + option **"stoppage_bet"** (all pot rows use this) |
| Predictions | `confidence_token` + option **"Stoppage2x"** |
| Predictions | `bonus_bet_type` + 10 wild options (values in 08 doc / script header) |
| PoolPlayers | + `stoppage_pot` (number, written by `--tally`) |
| PoolPlayers | + `stoppage_token_remaining` (number, initialized to 1) |
| SideGames | + row **"The Duel"** (base 25, resolution "player", locks at 3rd-place kickoff) |

## Row encoding (all rows: `prediction_type=stoppage_bet`, `pot=stoppage`)

Label convention: `{Player}|stoppage|{3rd|final}|{what}` — the `{Player}|` prefix is
load-bearing (tally and site both key on it).

| Bet | Fields used | Example label |
|---|---|---|
| Outcome (advancing team) | `match` link + `predicted_team` | `Cal\|stoppage\|final\|outcome` |
| Exact score after 90' | `match` link + `predicted_score_home/away` | `Cal\|stoppage\|3rd\|exact` |
| Bonus / wild bet | `match` link + `bonus_bet_type` + `bonus_bet_value` | `Andreas\|stoppage\|final\|bonus1` |
| The Duel | `side_game` → The Duel + `predicted_text` (Messi/Mbappé/Level) | `Cal\|stoppage\|duel` |

Token: set `confidence_token = "Stoppage2x"` on one pot row, decrement
`stoppage_token_remaining` by hand. Enter `pot_points` **already doubled**.
Beat-Rival (+3) rides on the outcome rows: add it into that row's `pot_points`.

Match links: 3rd Place Final = fixture **1591865**, Final = **1591866**.

## Entry protocol (no site changes, no leaks)

Bets are sealed by **simultaneous reveal in chat**: before each kickoff, both players
paste their full slate for that match (3-2-1-go). Transcribe into Airtable *after*
kickoff — nothing sensitive ever sits in the shared base pre-kickoff, which is also why
the `/api/public` bonus-bet sealing logic doesn't need to learn the new type. Pundit
notes go in `pundit_note` as usual, revealed on resolution. Per match: 1 outcome,
1 exact, up to 3 bonus/wild; plus 1 Duel pick each; ≤1 Stoppage2x total.

## Scoring workflow

1. After each match: agree each bet's result, type `pot_points` (0 or the value from the
   08 doc menus; ×2 if tokened; +3 Beat-Rival on outcome rows where exactly one was right).
   Two judged types ("Keeper saves penalty", "VAR overturn") are pool-decided, per Glove
   precedent.
2. After the Final, once the engine has resolved the legacy items (Champion slot, Golden
   Boot, Golden Glove, Total Tournament Goals):
   `python3 scripts/setup_stoppage_pot.py --tally`
   → writes `stoppage_pot`, prints **M**, **N**, and the recorded margin
   `max(1, M − N)` / `M + |N|`.
3. Record the result: recommend a short addendum in the 03 spec changelog with the final
   line ("{winner} d. {runner-up} by {margin}, Stoppage {consolation|bonus} {N}").

## Untouched, on purpose

Scoring engine, poller, Worker, site, and `savebonus` validation (its `BONUS_TYPES` list
never sees these rows). The site's picks tab may render `stoppage_bet` rows as an unknown
type or skip them — cosmetic; rows only exist post-kickoff. If we ever want the pot ON
the site, that's a live.html follow-up, not a scoring change.

## Checklist

- [ ] `python3 scripts/setup_stoppage_pot.py --dry-run` (on the Mac) — review
- [ ] run for real; spot-check new fields/options in Airtable
- [ ] commit script + docs via GitHub Desktop (no git from sandbox)
- [ ] before 3rd-place kickoff (Jul 18, 21:00 UTC): chat-reveal slates → transcribe
- [ ] before Final kickoff (Jul 19, 19:00 UTC): same
- [ ] post-Final: manual `pot_points` pass → `--tally` → record the margin
