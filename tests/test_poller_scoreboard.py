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

# ---- automated run: yesterday + today ---------------------------------------
auto = po.poll_dates(TODAY)
check("automated run polls two days", len(auto) == 2)
check("automated run includes yesterday", YESTERDAY in auto)
check("automated run includes today", TODAY in auto)
check("yesterday precedes today (chronological)", auto == [YESTERDAY, TODAY])

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
      po.poll_dates(dt.date(2026, 7, 1)) == [dt.date(2026, 6, 30), dt.date(2026, 7, 1)])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
