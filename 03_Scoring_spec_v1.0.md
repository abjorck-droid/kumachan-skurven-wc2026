# Scoring & Mechanics Spec — World Cup 2026 Bracket

**Version 1.1 — LOCKED 2026-06-24 by Andreas & Cal.** (v1.0 locked 2026-06-06.) Designed for two players (Andreas vs. Cal), 48-team World Cup, "full sicko mode" side games, broadcast-aesthetic UI.

This is the source-of-truth doc the front-end, the scoring engine, and the UI copy all derive from. Edit here first, then code.

**Changelog**

- **v1.1 (2026-06-24)** — Mulligan eligibility extended to the **Dark Horse**, agreed by both players. Same **50%** factor as a bracket-slot mulligan; the replacement must satisfy the original outside-top-16 eligibility judged against the **frozen June-11 ranking list**; the replacement may carry a still-unspent confidence token (locks at use), while any token on the original stays put. No scoring-engine change — Dark Horse is already a `Prediction` and rides the standard mulligan path; the only new work is the (not-yet-built) mulligan entry UI allowing Dark Horse as a target.
- **v1.0 erratum (2026-06-06, late)** — Clarification, agreed by both players: within a single
  bracket round, **each team counts at most once per player**. Duplicate slot picks of the same
  team in one round are void (0 points; the lowest-numbered slot is the one that counts). The
  pick-entry UI now blocks duplicates outright; the scoring engine voids any that slip through.
  Closes the "16 slots of France" expected-value exploit — no other scoring values change.
- **v1.0 (2026-06-06)** — Locked. One value changed from the draft: **Champion bonus 100 → 150**. Every other point value and mechanic confirmed as drafted. Lock semantics corrected: knockout per-match picks cannot lock at tournament kickoff (pairings don't exist until the group stage ends) — they lock per-match, if/when that entry flow is built. Editorial pass same day: player-specific phrasing neutralized so the doc reads identically for both players (the "Beat-Cal bonus" is now the **Beat-Rival bonus**); no rule changes.
- v0.1 (2026-05-19) — first draft.

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
| Champion correctly named | **150 points** |

These stack with per-match outcome picks — they're independent. (Predicting a team into the QF + predicting the QF match outcome correctly = two separate scores.)

---

## Side games (season-long, locked at tournament start)

| Side game | If correct |
|---|---|
| **Golden Boot** (top scorer of tournament) | **60 points** |
| **Golden Glove** (best goalkeeper — most clean sheets among GKs reaching at least the QF) | **60 points** |
| **First red card of the tournament** (name the team whose player is sent off) | **30 points** |
| **First own goal of the tournament** (name the team whose player scores it) | **40 points** |

*Amended 2026-06-10 (pre-lock, agreed): red card and own goal were player picks in v1.0 — naming the exact player was judged too hard. Now team picks; points unchanged.*
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

The Dark Horse is **mulligan-eligible** (see **The Mulligan**) — a re-pick in the post-group window scores at the standard 50%, with the replacement subject to the same outside-top-16 eligibility (frozen June-11 ranking).

---

## Per-match bonus bets (locked at each match's kickoff)

Each player can attach **up to two** bonus bets per match — these lock at that match's kickoff and reveal to the opponent on the first poll after kickoff (effectively at-kickoff with up to 15 min lag, or instant via client-side time-gating).

### Co-participation rule (anti-carpet-bomb)

A bonus bet on a given match only scores if **both players have attached at least one bonus bet (of any type) to that match**. If only one player opted in, no bonus bets on that match score for either player.

Once both have opted in, each player's individual bets are scored independently on their own correctness — bet types and values do not have to match.

Strategic implication: because per-match bonus bets are hidden until kickoff, the decision to opt-in to a match happens blind. Each player is betting on which matches the other player will also find interesting enough to engage with. This kills the "stack 100 bonus bets and rack up free points" strategy without enabling reactive play.

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

This makes token placement a strategic act. The All-In, in particular, is a single-shot signal of conviction, visible to the other player the moment the relevant prediction locks.

---

## Mechanics

### Beat-Rival bonus (every match)

For every match (group stage, R32, R16, QF, SF, Final), if one player correctly predicts the outcome **and** the other doesn't, the correct player gets a **+3 bonus** on top of the base score.

Independent of tokens. Small but accumulates — 64 matches × max 3 = 192 potential head-to-head bonus points.

### The Mulligan

Each player gets one. Usage window: **before the Round of 32 begins**. The final 2026 schedule has **no gap** between the group stage and the knockouts (last group games June 28, R32 starts June 29), so the window opens during the final group matchday: **June 24–28** (inclusive). A choice made before all groups finish simply has *less* hindsight — in keeping with the mulligan's blind-swing spirit.

When used:
- Player can re-pick **one** bracket-slot prediction **or** their **Dark Horse**. Any bracket slot — not just R32.
- Both the original prediction (now invalidated) and the new prediction are scored at **50% of their normal value**. This is so a mulligan recovers something even on a wrong original pick, without making the mechanic strictly better than not having one.
- A mulliganed **Dark Horse replacement** must still be **outside the FIFA top 16 by the June-11 lock-time ranking** (the same list used for the original pick).
- The replacement pick **may carry a still-unspent confidence token**, which locks the moment the mulligan is used. A token already attached to the original stays on the original and cannot be moved.
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
| Bracket ladder (R16 through Champion), Dark Horse, all season-long side games, all 72 group-stage outcome/score picks | **At tournament kickoff** (2026-06-11) |
| Knockout outcome/score picks (pairings unknown until the group stage ends) | **At that match's kickoff** — entry flow not yet built; in/out decision pending |
| Per-match bonus bets | **At that match's kickoff** — entry flow not yet built; in/out decision pending |
| Mulligan use | **Window: June 24–28** (opens during the final group matchday; before R32, which starts June 29) |

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

## Resolutions at the v1.0 lock (2026-06-06)

The four questions left open in v0.1, now settled:

1. **Champion bonus → 150** (was 100). Andreas + Cal wanted the champion to feel like THE big bracket call, able to offset a pile of smaller misses. 150 makes it worth ~1.9 full bracket tiers (and 30 group-match outcomes), and — critically — keeps an All-In champion (5×150 = 750) *below* the Dark Horse's signature 1000 ceiling, preserving the risk/reward hierarchy. 200 was the considered cap (an All-In champion would tie an All-In Dark Horse winning it all) and was rejected for flattening that distinction.
2. **Beat-Rival bonus → +3, confirmed.** Across 64 scoreable matches, the 192-point max is roughly the magnitude of guessing 4 quarter-final winners — present but not dominant.
3. **All-In strategy note stands:** an All-In on a 5-point group pick yields only 25 — the token is built for high-base picks (Champion = 750, or a Dark Horse on a deep run).
4. **Total tournament goals → "closest without going over," confirmed.** Forces a committed lower bound rather than rewarding hedged overshoots.
