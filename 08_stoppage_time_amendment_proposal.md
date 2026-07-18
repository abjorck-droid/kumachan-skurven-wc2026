# Amendment Proposal — "Stoppage Time" Endgame Pot (v1.2 draft)

**Status: ADOPTED 2026-07-17 by Andreas — Variant A (Stoppage Pot); awaiting Cal's sign-off before 3rd Place Final kickoff (Jul 18, 21:00 UTC). Airtable changes: `09_stoppage_pot_airtable_migration.md` + `scripts/setup_stoppage_pot.py`.**

Two matches remain (FRA–ENG 3rd place, ESP–ARG Final). This proposes a ring-fenced side-pot
covering all betting on those two fixtures — new outcome/exact betting (including the 3rd-place
game, omitted from the original betting entirely), an expanded bonus-bet menu with wild types,
and one fresh token each — converted at the end into a **margin adjustment** that can shrink the
recorded winning gap to a single point or blow it out, but can never flip the winner.

---

## Why a pot, not just more points

As of Jul 17 the main game stands **Andreas 1563, Cal 1414**, with Andreas holding a locked
+60 (Total Tournament Goals: 280 vs 187 against an actual already at 297) → effective
**1623 vs 1414**. Still open in the main game: Cal's Champion slot (ESP, +150), Andreas's
Golden Boot (Mbappé ×Double, +120), and bonus bets on the last two matches (≤35/match each).

Cal's ceiling under current rules is 1414 + 150 + 70 = **1634** — an 11-point live path that
runs entirely through bonus-bet sweeps. Golden Glove is dead for both: Unai Simón has personally
kept all 6 Spanish clean sheets (a World Cup record streak); Maignan maxes at 5, Martínez at 3.

So under current rules any *added* betting widens a still-live path and could upset the result —
exactly what we don't want. The fix: move all remaining per-match betting into a pot that scores
the **margin**, not the winner.

**Consequence of adoption (state it plainly):** with final/3rd-place bonus bets moved out of the
main game, Cal's main-game ceiling becomes 1414 + 150 = **1564 < 1623**. Signing this amendment
formally decides the main game — **Andreas is champion of record**. What remains at stake:

| Still resolving in the MAIN game | Effect on margin M |
|---|---|
| Champion slot (Cal: ESP) | −150 if Spain wins |
| Golden Boot (Andreas: Mbappé ×2) | +120 if Mbappé wins/shares (goals → assists → joint) |
| Total Tournament Goals (Andreas) | +60, already locked |
| Golden Glove | 0 for both (Simón) |

M therefore lands between **59** (Spain wins, Messi keeps the Boot) and **329** (Argentina wins,
Mbappé takes it).

---

## The pot

Every pot point is a normal point in every way — same values, same scoring order, same
`int(round())` — it just accumulates in `stoppage_pot` per player instead of `total_score`.
Any bonus bets already quietly placed on these two fixtures migrate to the pot at adoption.

### Conversion (after the Final)

Let **M** = main-game margin after the legacy items resolve, **N** = (trailing player's pot) −
(leading player's pot).

> **Recorded margin = max(1, M − N)** if N > 0 · **M + |N|** if N ≤ 0

- Trailing player sweeps → the archive shows a **1-point** championship. Full consolation,
  maximum trash-talk asymmetry, zero effect on who won.
- Leading player sweeps → the blowout is certified and permanent.

### Outcome betting (finally using the spec's KO values)

Sealed until kickoff, like bonus bets — these are entered with the pairings known, so blind
mutual entry preserves the co-participation-era spirit. Pundit Note strongly recommended.

| Pick | Value |
|---|---|
| 3rd place outcome / exact score | **20 / +15** |
| Final outcome / exact score after 90' | **50 / +30** |
| Beat-Rival bonus (per match, unchanged) | **+3** |

### Bonus bets: cap raised to 3/match, co-participation dropped

For these two fixtures only: up to **3 bonus bets per match**, from the classic menu *or* the
wild menu below, **no co-participation gate**. Rationale: the gate existed to stop carpet-bombing
across 104 matches; with 2 fixtures, a hard cap, and a ring-fenced pot, it protects nothing —
and dropping it removes the degenerate "clinch by abstention" line the current rules allow.

### Wild menu (these two fixtures only)

| Bet | Value | Resolution |
|---|---|---|
| Extra time played | **15** | auto |
| Decided on penalties | **25** | auto |
| Own goal in match | **25** | auto |
| Substitute scores | **15** | auto (lineups + events) |
| Goal in 90'+ stoppage time (either half) | **20** | auto (`minute.extra`) |
| No second-half goals | **25** | auto |
| 5+ combined cards | **15** | auto |
| Hat-trick by any player | **40** | auto |
| Keeper saves a penalty (in regulation) | **30** | judged — API "Missed Penalty" doesn't distinguish saved from off-target |
| VAR overturns a decision | **20** | judged — API VAR events are patchy |

### The Duel (cross-match special, one per player)

**Messi vs Mbappé, goals across both remaining matches** — pick Messi / Mbappé / Level: **25**.
The Golden Boot sweat, playable by both. Auto-resolvable.

### Stoppage Token

Each player receives **one fresh ×2 token, pot-only**, attachable to any single pot prediction,
locking and revealing at that prediction's kickoff. The endgame deserves one last conviction
signal; the main-game token economy stays untouched (all 7+7 spent).

### Ceiling math

Per player: outcomes 121 (incl. rival bonuses) + bonus 3×best ≈ 95/match → 190 + Duel 25 +
token on the Final outcome +50 ≈ **385 max pot**. A genuine sweep-vs-blank lands 150–250 of
net N — enough to floor any realistic M at 1, or roughly double it. Tuned, not decorative.

---

## Variant B — "Let it ride" (the chaos option)

No pot. All of the above scores straight into the main game. Cal's miracle path *widens* from
11 to ~11 + 121 + extra bonus headroom — the Final actually decides the pool. Maximum stakes,
but it abandons the stated goal that these bets can't upset the result, and it makes adding
the 3rd-place outcome betting a competitive act rather than a fun one. Included for honesty;
not recommended.

| | A — Stoppage Pot | B — Let it ride |
|---|---|---|
| Winner decided by | Main game (at adoption) | Possibly the last kick |
| New bets affect | Recorded margin only | Everything |
| Co-participation | Dropped (capped, ring-fenced) | Must keep (still load-bearing) |
| Consolation narrative | Margin → 1 pt | None — it's just points |
| Engine work | `stoppage_pot` rollup or manual | KO outcome scoring path, live |

## Implementation note

Two fixtures, ≤10 predictions per player: **manual scoring in Airtable is entirely adequate**
(a `pot` single-select on Predictions excluded from the `total_score` rollup, or a plain
shared sheet). The KO outcome/exact scoring path exists in the engine but has never run in
anger — don't debut it with the pool on the line unless someone wants the test-writing as
entertainment.

## Changelog entry (if adopted)

> - **v1.2 (2026-07-18)** — "Stoppage Time" endgame pot, agreed by both players. All betting on
>   the 3rd Place Final and Final (outcome/exact per spec KO values, bonus bets at 3/match from
>   an expanded menu, one pot-only ×2 token each, the Duel special) scores into a ring-fenced
>   per-player pot converted post-Final into a margin adjustment: max(1, M − N) / M + |N|.
>   Co-participation waived for these two fixtures. Main game consequently decided at adoption.
