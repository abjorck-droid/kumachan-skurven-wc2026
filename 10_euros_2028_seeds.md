# Euros 2028 — Design Seeds
*Drafted at the WC2026 wrap-up party, 2026-07-20/21, Cal & Andreas present. Distilled
from the full-season export (`data/season_export/`, 2026-07-21). Status: brainstorm,
nothing agreed except where marked.*

## The one settled thing
**Stoppage pot (v1.2) is a permanent rule from day one.** The season data closed the
case: main margin was functionally decided July 7 (gap 234 with three rounds left),
yet the endgame stayed electric because the pot was live. Cal's Spain conviction
filled it 113–25 and civilized a 179 blowout into a 91 result of record, winner
untouched. No more mid-tournament amendments — the pot ships in v1.0 of the Euros
spec, with The Duel and Golden Glove as standing pot specials.

## Rebalance candidates (discuss)
1. **Bonus-bet budget.** WC2026: Andreas 151 bets at 30% (680 pts), Cal 93 at 48%
   (725 pts) — both hit exactly 45. Volume and precision roughly cancelled, which
   means the market is efficient but shapeless. A quota (per-match cap or a season
   budget of ~N bets) would make *selection* strategic, the way tokens already are.
2. **Exact scores are underpriced.** 3 hits in 121 attempts all season (all Andreas,
   15 pts each). A rarity that rare deserves 25–30, or a two-tier reward
   (exact = 30, correct goal difference = 10).
3. **Steepen the bracket tiers.** QF slot at 10 felt thin against Champion 150.
   Euros has fewer rounds (24 teams, 51 matches) — tier values need a fresh curve
   anyway. Keep Champion as THE call (and keep All-In × Champion below the Dark
   Horse ceiling, per the WC2026 spec hierarchy).
4. **Token inventory.** 4×Double / 2×Triple / 1×All-In felt right (16 placements,
   6 died, drama throughout). Revisit only the *timing* rules — Cal's late All-In
   (F-2, locked pre-knockout) vs Andreas's day-one Champion All-In were different
   games entirely. Maybe: All-In placeable no earlier than the knockout bracket?
5. **Dark Horse ladder: untouchable.** Produced the call of the tournament
   (NOR ×Triple = 225). Port as-is; re-tune eligibility rank for Euros field depth
   (WC2026 used FIFA rank > 16).

## Structural notes for the Euros format
- 24 teams, 6 groups, best-third qualification — the R32 disappears; bracket_struct
  picks (group orders, thirds table) become proportionally bigger content.
  The thirds-qualification table itself is a prediction-worthy object.
- Hosts UK + Ireland: England at home. The Cartagena cup stands ready.
- Shorter tournament → the mulligan window needs rethinking (WC2026's window had
  zero gap between group end and R32).

## Open questions parked for the next session
- Pot conversion formula: keep `max(1, M − N)` as-is?
- Beat-rival bonus (+3): kept both seasons? (WC2026: Andreas 12, Cal 8 — small but spicy.)
- A bonus-bet type retrospective: Red card hit 12× in 104 matches; "Both teams
  score 2+" was the value market (A 11/18, C 12/23). Prune or reprice the menu?
- Site: reuse the Pages architecture (poller → Airtable → /api/public → site)
  or simplify now that the pipeline is proven?
