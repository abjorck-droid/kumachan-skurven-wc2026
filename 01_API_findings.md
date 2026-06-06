# API Spike Findings — World Cup 2026 Bracket Tool

**Status:** Full sicko mode is feasible on API-Football — but **requires a PAID plan**, not the free tier.

> **⚠️ VERIFIED 2026-06-05 (corrects the original assumption below).** Ran a real free-tier key against the live API.
> `/status` authenticates (plan: Free, 100/day), but `leagues / fixtures / teams / rounds` for `league=1&season=2026`
> all return **empty**. Cause: API-Football's pricing page confirms *"Free plans are limited in terms of available
> seasons"* — the 2026 season is **not** included on the free tier. The World Cup data is live on their servers
> (their own guide shows 2026 standings), but a free key can't see it. **Fix: upgrade to the Pro plan ($19/month,
> 7,500 req/day).** Tournament runs June 11–July 19 (~39 days), so budget ~2 prepaid months (~$38). Pro also makes
> the rate-limit section below moot — 7,500/day vs 100/day removes all polling-discipline risk. The free-tier
> rate-limit analysis is retained below only for reference.
>
> **CONFIRMED 2026-06-05 (later same day):** Pro upgrade is live and working. `teams?league=1&season=2026`
> returns all **48 teams**; `verify_api.py` runs clean. Caveat: `/fixtures/rounds` currently lists only the three
> group-stage rounds (`Group Stage - 1/2/3`) — the knockout round strings (incl. the exact "Round of 32" label)
> aren't published in the feed yet and remain the one open uncertainty until those fixtures schedule.

---

## TL;DR

- **Primary data source:** API-Football (api-sports.io, also distributed via RapidAPI). The World Cup is covered as `league=1`, `season=2026`, with all 104 matches in the new 48-team format.
- **Fallback / sanity-check:** football-data.org free tier (World Cup is on the perpetual-free competition list).
- **Coverage:** every feature on our "full sicko mode" list is supported by the API, including event-level data (goals, cards, own goals, substitutions), per-fixture player statistics, pre-match odds, and top-scorer / top-assist leaderboards.
- **The one real constraint:** API-Football's free tier is **100 calls per day**, no burst capacity, resets at midnight UTC. We have to be disciplined about call budget. Workable; details below.
- **Update frequency:** fixtures and events update server-side every ~15 seconds; player stats every ~5 minutes. Way faster than we need.

---

## Coverage matrix

| Feature we need | Endpoint | Confirmed? |
|---|---|---|
| Fixtures + final scores | `/fixtures?league=1&season=2026` | Yes |
| Match status (Live / Finished / Scheduled) | same | Yes |
| Goals, cards, own goals, subs (events) | `/fixtures/events?fixture={id}` | Yes |
| Per-player per-match stats (for GK clean-sheet tracking) | `/fixtures/players?fixture={id}` | Yes |
| Top scorers leaderboard (Golden Boot) | `/players/topscorers?league=1&season=2026` | Yes |
| Top assists | `/players/topassists?league=1&season=2026` | Yes |
| Team statistics (clean sheets, GF/GA) | `/teams/statistics` | Yes |
| Group standings | `/standings?league=1&season=2026` | Yes |
| Round names (group / R32 / R16 / QF / SF / Final) | `/fixtures/rounds?league=1&season=2026` | Yes |
| Pre-match bookmaker odds (for upset multipliers, if we want them) | `/odds?fixture={id}` | Yes — note 7-day history limit, but live pre-match is always available |
| Squads / player profiles | `/players?league=1&season=2026` | Yes |

Verdict: nothing on our wish list is blocked by the data layer.

---

## Sicko-mode feature feasibility

| Side game | Implementation note |
|---|---|
| Golden Boot | Direct from `/players/topscorers`. Trivial. |
| Golden Glove | Derive from `/fixtures/players` — pull GK who started, cross-reference with match clean-sheet status. Have to compute ourselves; not a one-call answer. |
| Per-group top scorer (12 prizes) | Aggregate from `/fixtures/events` filtered by group's matches and event type = Goal. Computed on our side. |
| Dark Horse | No API work — pure prediction logic against bracket progress. |
| First red card of tournament | Scan `/fixtures/events` across all matches in chronological order, first event with type=Card, detail=Red Card. |
| First own goal | Same pattern; events with type=Goal, detail=Own Goal. |
| Total tournament goals | Sum of all `home_score + away_score` at tournament end. |
| Exact-score per-match bets | Direct from fixture final scores. |
| Upset multiplier (if we ever add it) | Pre-match odds via `/odds`. Available. |

---

## Rate-limit reality check

The free tier is **100 requests/day**. Here's a realistic poll budget for a peak day (e.g. 4 matches in one day during group stage):

| Call | Frequency | Daily cost |
|---|---|---|
| `/fixtures?date={today}&league=1&season=2026` (single call returning all of today's matches and their statuses) | every 15 min during match windows | ~32 calls (8h × 4/hr) |
| `/fixtures/events?fixture={id}` (only for matches with status="LIVE") | every 15 min while live | ~24 calls (4 matches × 6 polls each) |
| `/players/topscorers` (rankings refresh) | 1× per day, end-of-day | 1 call |
| `/standings` (group standings refresh) | 1× per day | 1 call |
| Buffer / one-offs | — | 10–20 calls |
| **Daily total** | | **~70–80 calls** |

This sits comfortably under 100. The discipline is: poll the *fixtures list* often, but only drill into per-fixture events when a fixture is actually live.

**If we ever hit the cap:** API-Football's first paid tier is $19/month for 7,500 calls/day. We can buy our way out of the constraint at any point for the price of a sandwich. Not a blocker.

**One operational risk:** the daily reset is at midnight UTC. With matches in Mexico, the US, and Canada, our active hours straddle the reset. The poller logic should treat the budget as global per UTC day, not per local day.

---

## Recommended polling architecture

GitHub Actions cron, two workflows:

1. **`scoreboard-poll`** — runs every 15 minutes during a configurable date window (the tournament). Does the fixture-list call, then for each live fixture pulls events. Writes deltas to Airtable.
2. **`leaderboards-poll`** — runs once per day at, say, 04:00 UTC. Pulls top scorers, top assists, standings. These don't change during a single match enough to matter.

We persist a `PollLog` row per run with `calls_used_today`, `rate_limit_remaining` (returned in response headers), and timestamps — visible in Airtable for debugging.

---

## Gotchas / things to verify with a real API key

These are unknowns I can't fully resolve from public docs alone, and want to spot-check once we have a free key:

1. **GK identification per match.** API-Football returns lineups with positions. I want to confirm GK position is reliably labeled as "G" or similar so the Golden Glove logic is straightforward.
2. **Own-goal attribution.** Events with `detail: Own Goal` should clearly distinguish from regular goals. Want to confirm the data model.
3. **Round naming consistency.** The new 48-team format introduces a "Round of 32." Want to confirm this exact string is what the API returns (vs. e.g. "Last 32" or some variant).
4. **Squad availability before tournament.** Squads are typically finalized ~7 days before kickoff. The `/players` endpoint should populate when teams announce their squads (June 4-ish).
5. **Odds endpoint coverage for World Cup specifically.** The coverage flag says yes, but coverage can vary by competition. If we want pre-match odds as part of upset detection, we'd want to confirm at least one major bookmaker is publishing.

None of these are blockers — they're just things I'd want to verify in week 1 of build, not at the eleventh hour.

---

## Recommendation

Proceed with API-Football as the primary data source. Sign up for the free tier on api-sports.io (direct, not RapidAPI — fewer hops, same quota). Get an API key. Stash it in `.env` and in the GitHub Actions secrets store.

Football-data.org stays as a backup we can hit if API-Football ever has an outage during a match. We don't build against it unless something forces us to.

---

## Sources

- [API-Football: FIFA World Cup 2026 Guide](https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports)
- [API-Football Documentation v3](https://www.api-football.com/documentation-v3)
- [API-Football Pricing](https://www.api-football.com/pricing)
- [API-Football Rate Limit Explainer](https://www.api-football.com/news/post/how-ratelimit-works)
- [football-data.org Coverage](https://www.football-data.org/coverage)
- [football-data.org API Policies](https://docs.football-data.org/general/v4/policies.html)
