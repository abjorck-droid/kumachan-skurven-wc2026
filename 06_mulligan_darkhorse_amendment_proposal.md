# Amendment Proposal — Dark Horse as Mulligan-Eligible (v1.1 draft)

**Status: DECIDED 2026-06-24 — Variant A (standard parity, 50%) chosen and folded into `03_Scoring_spec_v1.0.md` as v1.1. This doc is retained as the decision record.** Token-on-replacement question is moot in practice: the only likely user is Cal, who put no token on his Dark Horse. (Andreas's Dark Horse = Norway, not changing.)

The current rule restricts the mulligan to one bracket-slot pick. This proposes adding `dark_horse` to the eligible set. Two variants below: **A (standard parity)** treats Dark Horse like any bracket slot; **B (tamed)** keeps it eligible but blunts the hindsight advantage. Everything common to both is stated once, then each variant gives exact drop-in text for the `### The Mulligan` section.

---

## Why this needs a decision, not just a toggle

The mulligan window is **after the group stage** (June 26–28). The original Dark Horse was a blind pick at June-11 kickoff; a re-pick in that window is made with full hindsight of who survived and how they looked over three games. The Dark Horse exists as a *blind, high-variance prophecy* — its first rung doesn't even pay until R16, so a group-stage bust scores 0, which makes a mulligan on it nearly pure upside. Even at 50%, "informed second guess" is a categorically stronger mechanic than "bold blind swing," and the 1000-pt ceiling amplifies it. Allowing it is fine — but decide it on purpose.

---

## Common to both variants

- The mulligan remains **one per player, total.** Spending it on the Dark Horse means you cannot also mulligan a bracket slot.
- A mulligan creates a **new `dark_horse` Prediction record** for the replacement; the original record stays in the system. Both are linked via `Mulligans.original_prediction` / `new_prediction`. The replacement is the "active" Dark Horse for display.
- **Visible to the opponent the instant it's used** (unchanged from existing rule).
- **Scoring order is unchanged: ladder payout → confidence token → discount → `int(round())`.**

### Ruling 1 — Eligibility timing (same in both variants)

The replacement Dark Horse must satisfy the original eligibility: **ranked outside the FIFA top 16, judged against the frozen June-11 lock-time ranking list** — *not* a fresh June-26 list. The eligibility list was already fixed at lock; reusing it keeps the constraint stable and prevents ranking-shift gaming. A team inside the top 16 at June 11 is never Dark-Horse-eligible, even if it underperformed in groups.

### Ruling 2 — Token on the replacement (differs by variant)

Tokens lock at their prediction's lock time, and per the no-move rule a token already on the original **stays on the original**. The open question is whether the *replacement* may carry a still-unspent token, locking at the moment the mulligan is used. The variants answer this differently.

---

## Variant A — Standard parity

Dark Horse behaves exactly like a bracket slot: **0.5 discount**, replacement **may** carry a fresh unspent token (locks at use).

**Engine change: none.** Dark Horse is already a `Prediction`, and the existing type-agnostic `mull_affected` × `MULLIGAN_FACTOR = 0.5` logic in `finalize` applies automatically. Token-then-halve already holds. The only non-engine work is the entry layer: allow Dark Horse as a target and enforce Ruling 1.

**Ceiling:** replacement Champion + All-In = 1000 × 5 × 0.5 = **2,500**. Without a token, 1000 × 0.5 = **500**.

### Drop-in replacement for `### The Mulligan`

> ### The Mulligan
>
> Each player gets one. Usage window: **after the group stage ends, before the Round of 32 begins** (June 26–28 if FIFA's draft schedule holds — confirm closer to the tournament).
>
> When used:
> - Player can re-pick **one** bracket-slot prediction **or** their **Dark Horse**. Any bracket slot — not just R32.
> - Both the original prediction (now invalidated) and the new prediction are scored at **50% of their normal value.** This is so a mulligan recovers something even on a wrong original pick, without making the mechanic strictly better than not having one.
> - A mulliganed **Dark Horse replacement** must still be **outside the FIFA top 16 by the June-11 lock-time ranking** (the same list used for the original pick).
> - The replacement pick **may carry a still-unspent confidence token,** which locks the moment the mulligan is used. A token already attached to the original stays on the original and cannot be moved.
> - The act is **visible to the opponent the moment it's used.**

### Changelog entry

> - **v1.1 (2026-06-2X)** — Mulligan eligibility extended to the Dark Horse, agreed by both players. Same 50% factor; replacement must satisfy the original outside-top-16 eligibility by the frozen June-11 ranking; replacement may carry an unspent token (locks at use). No engine change — Dark Horse already rides the standard mulligan path.

---

## Variant B — Tamed

Dark Horse eligible, but two levers blunt the hindsight edge: **0.25 discount** on a mulliganed Dark Horse (both original and replacement), and **no token on the replacement.** This keeps the Dark Horse as the game's biggest swing while making a post-group re-pick clearly worse EV than the original blind pick would have been.

**Why 0.25:** a quarter-value Dark Horse Champion is 1000 × 0.25 = **250** — still larger than a full Champion bracket slot (150), so it remains the spiciest pick on the board, just no longer a hindsight free-roll. SF replacement = 200 × 0.25 = **50**; Final = 500 × 0.25 = **125**. No-token rule means the 2,500 All-In ceiling from Variant A is off the table.

**Engine change: small but real.** The current engine hardcodes a single `MULLIGAN_FACTOR = 0.5` applied to every record in `mull_affected`. A per-type discount needs one of:
- **(i) Branch on type in `finalize`:** use `0.25` when the record's `prediction_type == "dark_horse"`, else `0.5`. Minimal diff.
- **(ii) Data-driven (preferred):** add a `discount_factor` field to the `Mulligans` table (default `0.5`), and have the engine read the factor per linked record. Future-proofs any later "different discount per mulligan" idea and keeps the rule out of code.

The **no-token-on-replacement** lever is enforced in the **entry layer**, not the engine — the UI must block attaching a token to a Dark Horse mulligan replacement (the engine would otherwise happily multiply whatever token is attached).

### Drop-in replacement for `### The Mulligan`

> ### The Mulligan
>
> Each player gets one. Usage window: **after the group stage ends, before the Round of 32 begins** (June 26–28 if FIFA's draft schedule holds — confirm closer to the tournament).
>
> When used:
> - Player can re-pick **one** bracket-slot prediction **or** their **Dark Horse**. Any bracket slot — not just R32.
> - A mulliganed **bracket slot** scores at **50%** (original and replacement). A mulliganed **Dark Horse** scores at **25%** (original and replacement) — the steeper discount offsets the hindsight advantage of re-picking after the group stage.
> - A mulliganed **Dark Horse replacement** must still be **outside the FIFA top 16 by the June-11 lock-time ranking** (the same list used for the original pick), and **may not carry a confidence token.** A token already attached to the original stays on the original and cannot be moved.
> - The act is **visible to the opponent the moment it's used.**

### Changelog entry

> - **v1.1 (2026-06-2X)** — Mulligan eligibility extended to the Dark Horse, agreed by both players, at a **steeper 25% factor** (vs 50% for bracket slots) and **no token on the replacement**, to offset the post-group hindsight advantage. Requires a per-type mulligan factor in the scoring engine (new `Mulligans.discount_factor`, default 0.5) and an entry-layer block on tokens for Dark Horse replacements.

---

## Side-by-side

| | Variant A — Standard | Variant B — Tamed |
|---|---|---|
| Dark Horse discount | 0.5 | 0.25 |
| Token on replacement | Allowed (locks at use) | Blocked |
| Replacement eligibility | Outside top 16 (June-11 list) | Outside top 16 (June-11 list) |
| Ceiling (Champion + token) | 2,500 | n/a (no token) |
| Ceiling (Champion, no token) | 500 | 250 |
| Engine work | None | Per-type factor + entry-layer token block |
| Character | Spicy hindsight free-roll | Biggest swing, but hindsight-taxed |

## Mix-and-match note

The two levers are independent — you don't have to take Variant B whole. Intermediate points: **0.5 but no replacement token** (ceiling 500, zero engine change beyond the token block) or **0.25 but token allowed** (ceiling 1000 × 5 × 0.25 = 1,250). If you'd rather only tax the hindsight side, an **asymmetric** option keeps the original at 0.5 (it was a legit blind pick) and discounts only the replacement at 0.25 — cleanest to express as a per-record factor via the data-driven engine option (ii).

## Recommendation

If the goal is preserving the Dark Horse's identity as a blind prophecy, **Variant B** (or the "0.5 + no token" middle option, which needs no engine math change) is the more defensible design. **Variant A** is the right pick if you want maximum chaos and zero new code before the window opens.
