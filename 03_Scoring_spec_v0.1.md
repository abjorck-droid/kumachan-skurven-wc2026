# Scoring & Mechanics Spec — World Cup 2026 Bracket

Version 0.1. Designed for two players (Andreas vs. Cal), 48-team World Cup, "full sicko mode" side games, broadcast-aesthetic UI.

This is the source-of-truth doc the front-end, the scoring engine, and the UI copy all derive from. Edit here first, then code.

---

## Player setup (per player, set once at base creation)

Each player begins the tournament with:

- **4 × Double tokens** (2× multiplier)
- **2 × Triple tokens** (3× multiplier)
- **1 × All-In token** (5× multiplier)
- **1 × Mulligan**

Total tokens: 7 multiplier tokens and 1 mulligan. Tight enough that each placement feels like a real decision.

---

## Pick types and base point values

### Group-stage matches (72 matches)

Per match, a player can submit two related predictions:

| Pick | If correct |
|---|---|
| Match outcome (Home win / Draw / Away win) | **5 points** |
| Exact score | **+10 points** (15 total if both correct) |

Predicting the wrong outcome but the right score isn't possible (the outcome is a function of the score). The exact-score bonus only triggers if the outcome is also right.

### Round-of-32 matches (16 matches — new round in 2026 format)

| Pick | If correct |
|---|---|
| Match outcome (the team that advances) | **10 points** |
| Exact score after 90 min | **+15 points** |

For knockouts, "outcome" = which team advances, regardless of extra time or penalties.

### Round-of-16 matches (8 matches)

| Pick | If correct |
|---|---|
| Outcome | **15 points** |
| Exact score after 90 min | **+15 points** |

### Quarter-finals (4 matches)

| Pick | If correct |
|---|---|
| Outcome | **20 points** |
| Exact score after 90 min | **+20 points** |

### Semi-finals (2 matches)

| Pick | If correct |
|---|---|
| Outcome | **30 points** |
| Exact score after 90 min | **+25 points** |

### Final and Third-place playoff

| Pick | If correct |
|---|---|
| Final outcome | **50 points** |
| Final exact score after 90 min | **+30 points** |
| Third-place playoff outcome | **20 points** |
| Third-place exact score | **+15 points** |

---

## Bracket-slot picks (locked at tournament start)

These are predicted *before* the tournament begins — naming the team you think will reach each round, regardless of who actually plays the match.

| Bracket slot | If correct |
|---|---|
| Each Round of 16 team correctly named (16 slots) | **5 points each** (max 80) |
| Each Quarter-finalist correctly named (8 slots) | **10 points each** (max 80) |
| Each Semi-finalist correctly named (4 slots) | **20 points each** (max 80) |
| Each Finalist correctly named (2 slots) | **40 points each** (max 80) |
| Champion correctly named | **100 points** |

These stack with per-match outcome picks — they're independent. (Predicting a team into the QF + predicting the QF match outcome correctly = two separate scores.)

---

## Side games (season-long, locked at tournament start)

| Side game | If correct |
|---|---|
| **Golden Boot** (top scorer of tournament) | **60 points** |
| **Golden Glove** (best goalkeeper — most clean sheets among GKs reaching at least the QF) | **60 points** |
| **First red card of the tournament** (name the player) | **30 points** |
| **First own goal of the tournament** (name the player) | **40 points** |
| **Total tournament goals** (closest without going over) | **30 points** |
| **Top scorer of each group** (12 awards, one per group) | **15 points each** (max 180) |
| **Dark Horse** | Ladder, see below |

### Dark Horse ladder

Each player names one Dark Horse at tournament lock. Eligibility: team must be ranked **outside the FIFA top 16** at lock time.

Only the *highest tier reached* pays out (not cumulative):

| Furthest round the Dark Horse reaches | Payout |
|---|---|
| Round of 16 | 25 |
| Quarter-final | 75 |
| Semi-final | 200 |
| Final | 500 |
| Champion | 1000 |

This is the highest single-prediction payout in the game by a wide margin. Bold picks are big swings.

---

## Per-match bonus bets (locked at each match's kickoff)

Each player can attach **up to two** bonus bets per match — these lock at that match's kickoff and reveal to the opponent on the first poll after kickoff (effectively at-kickoff with up to 15 min lag, or instant via client-side time-gating).

### Co-participation rule (anti-carpet-bomb)

A bonus bet on a given match only scores if **both players have attached at least one bonus bet (of any type) to that match**. If only one player opted in, no bonus bets on that match score for either player.

Once both have opted in, each player's individual bets are scored independently on their own correctness — bet types and values do not have to match.

Strategic implication: because per-match bonus bets are hidden until kickoff, the decision to opt-in to a match happens blind. You're betting on which matches Cal will also find interesting enough to engage with. This kills the "stack 100 bonus bets and rack up free points" strategy without enabling reactive play.

Bet types and payouts (all binary, all 10–20 points):

| Bonus bet | If correct |
|---|---|
| Both Teams To Score (yes/no) | **10 points** |
| Over / Under 2.5 goals | **10 points** |
| Penalty awarded in match | **15 points** |
| Red card shown in match | **20 points** |
| Both teams score 2+ goals | **15 points** |
| Goal in first 15 min | **15 points** |

Bonus bets do **not** stack with per-match exact-score predictions in any special way — they're independent payouts.

---

## Confidence tokens (the mechanic)

The full mechanic:

- Each player has a fixed inventory of multiplier tokens (4 Double, 2 Triple, 1 All-In).
- A token is attached to *one specific prediction* before that prediction locks.
- Maximum one token per prediction.
- A token attached to a correct prediction multiplies the points awarded.
- A token attached to a wrong prediction is consumed for nothing (**soft downside** — no point loss, just the wasted token).
- Once attached, a token cannot be moved or unspent.
- Tokens are **revealed to the opponent at lock time** of the prediction they're attached to (consistent with the visibility rules — same-time-as-pick).

This makes token placement a strategic act. The All-In, in particular, is a single-shot signal of conviction, visible to your rival the moment the relevant prediction locks.

---

## Mechanics

### Beat-Cal bonus (every match)

For every match (group stage, R32, R16, QF, SF, Final), if one player correctly predicts the outcome **and** the other doesn't, the correct player gets a **+3 bonus** on top of the base score.

Independent of tokens. Small but accumulates — 64 matches × max 3 = 192 potential head-to-head bonus points.

### The Mulligan

Each player gets one. Usage window: **after the group stage ends, before the Round of 32 begins** (June 26–28 if FIFA's draft schedule holds — confirm closer to the tournament).

When used:
- Player can re-pick **one** bracket-slot prediction. Any slot — not just R32.
- Both the original prediction (now invalidated) and the new prediction are scored at **50% of their normal value**. This is so a mulligan recovers something even on a wrong original pick, without making the mechanic strictly better than not having one.
- The act is **visible to the opponent the moment it's used.**

### Pundit Notes

- Each prediction can have an optional one-line note attached.
- Locked at the same time as the prediction.
- Revealed to the opponent only after the prediction resolves.
- No point value. Pure trash talk and self-reflection.

### Dark Horse selection

- Locked at tournament start.
- Team must be ranked outside FIFA top 16 (which generally means: not Brazil, Argentina, France, England, Spain, Portugal, Netherlands, Belgium, Italy, Germany, Croatia, USA, Mexico, Morocco, Uruguay, Colombia — the exact list depends on FIFA's June 2026 ranking).
- Pundit Note recommended.
- A Dark Horse pick **can** have a confidence token attached. The All-In token on a Dark Horse pick is the spiciest move available in the game.

---

## Visibility rules

| What | When visible to opponent |
|---|---|
| Player has begun entering picks (progress indicator only) | Anytime |
| Specific picks during entry phase | Never (until lock) |
| Bracket-slot picks | At tournament lock |
| Side-game picks (Golden Boot, Glove, Dark Horse, etc.) | At tournament lock |
| Confidence token placements | At the lock time of the prediction they're attached to (= tournament lock for most picks) |
| Match outcome and exact-score picks for group stage / knockouts | At tournament lock |
| Per-match bonus bets | At that match's kickoff (client-side time-gated) |
| Pundit Notes | After the relevant prediction resolves (match ends / side game resolves) |
| Mulligan use | Instantly when used |
| Score totals and standings | Always |

---

## Lock semantics summary

| What | Locks |
|---|---|
| Bracket (R32 through Final, Champion, Dark Horse, all season-long side games, all group-stage and knockout outcome/score picks) | **At tournament kickoff** (2026-06-11) |
| Per-match bonus bets | **At that match's kickoff** |
| Mulligan use | **Window: June 26–28** (after group stage, before R32) |

Nothing locks before tournament start except the tournament itself. Once kickoff happens, nearly everything is set in stone.

---

## Things explicitly **not** in v1

These are decided-no-for-now, with rationale:

- **Vote of No Confidence.** Dropped after discussion — soft-downside makes it confusing.
- **Shadow Bets.** Held for v1.1 if the game feels static. Same logic as Vote of No Confidence but cleaner.
- **Brier / probabilistic scoring.** Too heavy cognitively for a friendly competition.
- **Underdog multiplier from pre-match odds.** Cool idea but adds complexity; revisit if Dark Horse alone doesn't reward bold picks enough.
- **Streak bonuses.** Tried in earlier discussion. Removed to keep mechanics clean.
- **Push notifications / Slack integration.** Not needed for two-player.

---

## Open scoring questions before code

1. **Champion bonus.** Is 100 points right? Feels right given the bracket-slot ladder (R16: 5, QF: 10, SF: 20, Final: 40, Champion: 100) follows roughly 2× per round.
2. **Beat-Cal bonus value.** I picked +3 to keep it from dominating. Sanity check: across 64 matches, max 192 H2H bonus = roughly the same magnitude as guessing 4 quarter-final winners correctly. Feels balanced.
3. **All-In on a 5-point pick = 25 points.** Is that worth the token? Probably not — implies you should save All-In for high-base-value picks like the Champion (5× 100 = 500) or Dark Horse pick on a deep run.
4. **Total tournament goals.** "Closest without going over" punishes over-estimation. Alternative is "closest in either direction." Closest-without-going-over is more interesting because it forces you to commit to a lower bound. Keep as proposed unless you push back.
