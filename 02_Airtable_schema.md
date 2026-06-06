# Airtable Schema Draft — World Cup 2026 Bracket

Working draft, v0.1. The goal is a schema that the poller can write into, the front-end can read from, and that you (Andreas) can hand-edit when something weird happens during the tournament.

---

## Base philosophy

- **Few tables, wide rows.** Airtable rewards denormalization more than a relational DB would. We keep the schema readable when you open the base directly.
- **One Predictions table for everything.** All picks — match outcomes, bracket slots, side games, per-match bonus bets — live in one table, distinguished by a `prediction_type` field. Single source of truth for scoring.
- **Computed fields belong in the scoring engine, not Airtable formulas.** A few simple lookups are fine, but anything multi-step gets computed by the GitHub Action and written back. Keeps the scoring logic in version control.

---

## Tables

### 1. `Teams`

The 48 World Cup participants.

| Field | Type | Notes |
|---|---|---|
| `team_id` | Number | API-Football team ID. Primary key. |
| `name` | Single line text | e.g. "Argentina" |
| `code` | Single line text | 3-letter, e.g. "ARG" |
| `flag_emoji` | Single line text | 🇦🇷 |
| `group` | Single select | "A" through "L" (12 groups) |
| `fifa_ranking` | Number | Populated manually at tournament start. Used for Dark Horse eligibility. |
| `eliminated_at_round` | Single select | NULL while alive; set to "Group" / "R32" / "R16" / "QF" / "SF" / "Final" when knocked out |
| `kit_color_primary` | Single line text | Hex code, for UI accents |
| `kit_color_secondary` | Single line text | Hex code |

### 2. `Footballers`

Individual players. Populated automatically from `/players?league=1&season=2026` once squads are announced (~June 4).

| Field | Type | Notes |
|---|---|---|
| `player_id` | Number | API-Football player ID. Primary key. |
| `name` | Single line text | |
| `team` | Link → Teams | |
| `position` | Single select | "G" / "D" / "M" / "F" |
| `shirt_number` | Number | |
| `goals_in_tournament` | Number | Updated by poller. |
| `assists_in_tournament` | Number | Updated by poller. |
| `clean_sheets_started` | Number | GKs only; computed from per-fixture lineups. |

### 3. `Matches`

All 104 fixtures.

| Field | Type | Notes |
|---|---|---|
| `fixture_id` | Number | API-Football fixture ID. Primary key. |
| `kickoff_utc` | Date with time | |
| `venue` | Single line text | |
| `round` | Single select | "Group A"…"Group L" / "Round of 32" / "Round of 16" / "Quarter-final" / "Semi-final" / "Third-place" / "Final" |
| `home_team` | Link → Teams | |
| `away_team` | Link → Teams | |
| `home_score` | Number | NULL until match has a score. |
| `away_score` | Number | |
| `status` | Single select | "Scheduled" / "Live" / "Finished" / "Postponed" |
| `winner` | Link → Teams | NULL for draws (group stage only — knockouts always have a winner). |
| `winner_method` | Single select | "Regulation" / "Extra Time" / "Penalties" — relevant for knockout-only logic. |
| `events_json` | Long text | Raw event payload from `/fixtures/events`. Useful for debugging and recomputing on rule changes. |
| `last_polled_at` | Date with time | |

### 4. `PoolPlayers`

You and Cal. Possibly a third person one day.

| Field | Type | Notes |
|---|---|---|
| `name` | Single line text | "Andreas" / "Cal" |
| `display_color` | Single line text | Hex, for UI accents |
| `magic_link_token` | Single line text | UUID. Used for auth — login is `worldcup.host/?p={token}`. |
| `tokens_remaining_double` | Number | Starts at 4. Decrements when token spent. |
| `tokens_remaining_triple` | Number | Starts at 2. |
| `tokens_remaining_allin` | Number | Starts at 1. |
| `mulligans_remaining` | Number | Starts at 1. |
| `total_score` | Number | Updated by scoring engine after every poll. |

### 5. `Predictions`

The big one. One row per prediction. Type-tagged.

| Field | Type | Notes |
|---|---|---|
| `pool_player` | Link → PoolPlayers | |
| `prediction_type` | Single select | "match_outcome" / "match_exact_score" / "bracket_slot" / "side_game" / "bonus_bet" / "dark_horse" |
| `match` | Link → Matches | Used for match_outcome, match_exact_score, bonus_bet. |
| `bracket_slot` | Single line text | Used for bracket_slot. e.g. "R32-Match-3-Winner" / "Champion" / "Runner-up" |
| `side_game` | Link → SideGames | Used for side_game and dark_horse. |
| `predicted_outcome` | Single select | "Home" / "Draw" / "Away" — for match_outcome only |
| `predicted_score_home` | Number | for match_exact_score |
| `predicted_score_away` | Number | for match_exact_score |
| `predicted_team` | Link → Teams | for bracket_slot and dark_horse |
| `predicted_player` | Link → Footballers | for side_game (Golden Boot, Glove, etc.) |
| `predicted_scalar` | Number | for "total tournament goals" |
| `predicted_text` | Single line text | for "first red card" — name of player |
| `bonus_bet_type` | Single select | for bonus_bet: "BTTS" / "Over 2.5" / "Under 2.5" / "Penalty in match" / "Red card in match" / "Both teams score 2+" |
| `bonus_bet_value` | Single select | "Yes" / "No" or other |
| `confidence_token` | Single select | NULL / "Double" / "Triple" / "AllIn" |
| `pundit_note` | Long text | Optional. Locked at same time as prediction. |
| `locked_at` | Date with time | When prediction became immutable. |
| `points_awarded` | Number | Computed by scoring engine. |
| `beat_rival_bonus` | Number | Computed by scoring engine. |
| `resolved` | Checkbox | True once the underlying event has finalized. |

### 6. `SideGames`

Definitions for the season-long bonus predictions.

| Field | Type | Notes |
|---|---|---|
| `name` | Single line text | "Golden Boot" / "Golden Glove" / "Dark Horse" / "First Red Card" / "First Own Goal" / "Total Tournament Goals" / "Top Scorer Group A"…"Top Scorer Group L" |
| `description` | Long text | |
| `resolution_type` | Single select | "player" / "team" / "scalar" / "event_player" |
| `lock_at_utc` | Date with time | Almost always = tournament kickoff (2026-06-11). |
| `resolved_value` | Single line text | Filled in once known. |
| `resolved_at` | Date with time | |
| `base_points` | Number | See Scoring spec. |
| `dark_horse_ladder` | Long text | JSON ladder for Dark Horse: `{"R32":25,"R16":75,"QF":200,"SF":500,"Final":1000}` — only this side_game uses it. |

### 7. `Mulligans`

Log of mulligan usage. Mostly cosmetic — the scoring engine reads `Predictions.points_awarded` directly — but having this table makes it easy to show the moment a mulligan happened in the UI.

| Field | Type | Notes |
|---|---|---|
| `pool_player` | Link → PoolPlayers | |
| `used_at` | Date with time | |
| `original_prediction` | Link → Predictions | The pre-mulligan pick. Its `points_awarded` is multiplied by 0.5. |
| `new_prediction` | Link → Predictions | The replacement pick. Same 0.5 multiplier. |
| `note` | Long text | Optional player-supplied reason. |

### 8. `PollLog`

Operational, for debugging.

| Field | Type | Notes |
|---|---|---|
| `run_at` | Date with time | |
| `workflow` | Single select | "scoreboard-poll" / "leaderboards-poll" / "manual" |
| `calls_made` | Number | |
| `rate_limit_remaining` | Number | From API response headers. |
| `fixtures_touched` | Number | |
| `errors` | Long text | |

---

## Relationships

```
Teams ──┬─< Footballers
        ├─< Matches (home_team, away_team, winner)
        └─< Predictions (predicted_team)

Footballers ──< Predictions (predicted_player)

Matches ──< Predictions (match)

PoolPlayers ──< Predictions
            └─< Mulligans

SideGames ──< Predictions (side_game)

Predictions ──< Mulligans (original_prediction, new_prediction)
```

---

## Open schema questions

1. **Do we store the raw `/fixtures/events` payload as JSON in `Matches.events_json`?** I've assumed yes. It's bulky but lets us recompute scoring after rule changes without re-polling. The alternative is parsing into a normalized `Events` table — cleaner but more moving parts. Lean toward keeping JSON for v1.

2. **Group standings — table or computed?** I'd say computed by the poller (it's simple aggregation off `Matches`) and exposed to the front-end via a derived JSON blob. No Airtable table needed. If you want to eyeball standings inside Airtable, we add a view rather than a table.

3. **Should bonus bets be opt-in per match?** Yes. Player chooses which matches to attach a bonus bet to, and the menu of bet types per match. Not all matches must have bets attached. UI affordance: each match card has a "+ add bonus bet" button until kickoff.

4. **Do we need a `Notifications` table for the live-update feed?** For v1, probably no — the front-end polls Airtable every minute when open and shows live deltas. If we ever want push notifications (e.g. "Cal just locked his bracket"), add later.
