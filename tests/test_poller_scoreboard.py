#!/usr/bin/env python3
"""poller scoreboard date window — boundary-crossing fixtures (no network).

Regression for 2026-06-13: the scoreboard poller queried only today's UTC date.
API-Football buckets a fixture under its kickoff's UTC date, so a match still in
progress when the UTC day rolled over (BRA v MAR, 22:00 UTC kickoff) dropped out
of the single-date query and froze at its last-seen Live minute (81'), never
recording full time. Fix: the automated run polls yesterday AND today.
"""
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import poller as po

PASS = FAIL = 0
def check(label, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("  ✓ " + label)
    else: FAIL += 1; print("  ✗ " + label)

TODAY = dt.date(2026, 6, 14)
YESTERDAY = dt.date(2026, 6, 13)
TOMORROW = dt.date(2026, 6, 15)

# ---- automated run: yesterday + today + tomorrow -----------------------------
# Tomorrow is the 2026-07-05 regression: a late-US-evening game (ENG v MEX,
# 02:00 UTC) buckets under the NEXT UTC date — without tomorrow in the window its
# Matches row is never created in time and the bonus tab locks the whole evening.
auto = po.poll_dates(TODAY)
check("automated run polls three days", len(auto) == 3)
check("automated run includes yesterday", YESTERDAY in auto)
check("automated run includes today", TODAY in auto)
check("automated run includes tomorrow (bonus-bet row creation)", TOMORROW in auto)
check("chronological order", auto == [YESTERDAY, TODAY, TOMORROW])

# The actual bug: a 22:00 UTC June 13 kickoff is bucketed June 13. After midnight
# the run executes on June 14 — June 13 must still be queried or FT is never seen.
bra_mar_bucket = dt.date(2026, 6, 13)
check("June-13 bucket still polled on a June-14 run", bra_mar_bucket in po.poll_dates(TODAY))

# ---- explicit --date backfill: that one day only ----------------------------
one = po.poll_dates(TODAY, target_date=YESTERDAY)
check("--date polls exactly one day", one == [YESTERDAY])
check("--date does not widen to a window", len(one) == 1)
check("--date for today polls only today", po.poll_dates(TODAY, target_date=TODAY) == [TODAY])

# ---- month boundary (timedelta, not naive arithmetic) -----------------------
check("crosses month start correctly",
      po.poll_dates(dt.date(2026, 7, 1)) == [dt.date(2026, 6, 30), dt.date(2026, 7, 1), dt.date(2026, 7, 2)])
check("crosses month end correctly",
      po.poll_dates(dt.date(2026, 6, 30)) == [dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)])

# ---- to_match_fields: KO fixture published before pairings (null teams) -------
# The daily season-schedule refresh and the tomorrow poll can both see fixtures
# whose teams aren't decided yet — must not crash, label falls back to "? v ?".
tbd = {"fixture": {"id": 999001, "date": "2026-07-11T20:00:00+00:00",
                   "status": {"short": "NS"}, "venue": {}},
       "league": {"round": "Quarter-finals"},
       "teams": {"home": None, "away": None}, "goals": {}}
rec = po.to_match_fields(tbd, {}, "2026-07-05T00:00:00Z")
check("TBD fixture doesn't crash, keeps id", rec["fixture_id"] == 999001)
check("TBD fixture label falls back", rec["label"] == "? v ?")
check("TBD fixture stays Scheduled", rec["status"] == "Scheduled")
check("TBD fixture links no teams", "home_team" not in rec and "away_team" not in rec)
tbd2 = dict(tbd); tbd2["teams"] = {"home": {"id": None, "name": None}, "away": {"id": None, "name": None}}
check("null-name team objects also fall back", po.to_match_fields(tbd2, {}, "x")["label"] == "? v ?")

# ---- should_fetch_events: capture final-minutes goals on Live→Finished -------
sfe = po.should_fetch_events
check("live match always refetched", sfe("2H", "Live", True) is True)
check("live match, nothing stored yet", sfe("1H", None, False) is True)
check("half-time counts as live", sfe("HT", "Live", True) is True)
# THE fix: a match that was Live last poll and is now Finished must be fetched
# once more, even though live polls already stored (partial) events — otherwise a
# goal after the last Live snapshot is lost.
check("Live→Finished transition refetched (the bug)", sfe("FT", "Live", True) is True)
check("finished first sighting, no events stored", sfe("FT", "Live", False) is True)
check("finished & already settled → stop", sfe("FT", "Finished", True) is False)
check("finished but somehow no events → fetch", sfe("FT", "Finished", False) is True)
check("AET transition refetched", sfe("AET", "Live", True) is True)
check("PEN already settled → stop", sfe("PEN", "Finished", True) is False)
check("scheduled never fetched", sfe("NS", None, False) is False)
check("postponed never fetched", sfe("PST", None, False) is False)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
