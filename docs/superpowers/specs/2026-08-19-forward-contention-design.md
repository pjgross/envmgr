# Phase 7 B6 — Forward contention as a calendar leading indicator

> Status: design approved 2026-08-19. The last sub-project in Phase 7, and the
> last line of [requirements.md §2.12](../../requirements.md).
>
> Gated on A4 (project-aware contention), which computes the verdicts and owns
> the escalation record. A4 deliberately left this surface empty: *"A4 adds no
> `BookingList` column and no calendar surface. Forward contention as a leading
> indicator is B6's line; building one here would pre-empt it."*

## 1. The problem

A4 computes a contention verdict for every conflicting pair of bookings, and it
is correct and well tested. It renders in exactly two places: the Conflicts
panel on a booking's own page, and the `/contentions` worklist.

Both are pull surfaces. You learn that two bookings collide in November by
opening one of them, or by reading a worklist you had a reason to open. Nobody
browsing the calendar in September sees it — and September is when moving a
booking is cheap. By the time the clash is visible in the ordinary flow of work,
it is imminent and the options are worse.

**B6 changes where contention is visible, not what it is.**

## 2. What B6 does, and the limit of it

**B6 ADDS NO WRITE PATH AT ALL.** No table, no column, no stored verdict,
nothing refused, nothing transitioned, no new state of any kind. It reads
bookings and A4's existing escalations and renders them in three new places.

This makes it the first pure-read sub-project in Phase 7. A3 warns, A4 advises,
B2 advises, B5 acts narrowly and pins exactly how far — **B6 touches nothing**,
and `tests/test_b6_writes_nothing.py` is the guard: exercising every B6 path
over a populated estate leaves every row byte-identical.

**Deviation on record.** §2.12 calls it a "leading indicator". B6 **predicts
nothing**. It surfaces existing facts earlier. A forecasting feature over a
register holding a few hundred bookings would be a worse product and a
less honest one; "leading" here means the information arrives while acting on it
is still cheap.

## 3. Architecture: one shared batch function

```
contention_states_for_bookings(db, tenant_id, booking_ids, now) -> dict[int, ContentionState]
```

One function, two consumers — `GET /bookings` (whose page feeds both the list
column and the calendar markers) and the horizon summary.

**The map contains only CONTENDED bookings; an absent key means no contention.**
There is deliberately no `none` state. A four-valued enum whose fourth value is
"nothing to say" invites a consumer to render it, and this branch has already
shipped an empty chip reading as a state of its own.

**One function, not two, is the point.** The list column, the calendar marker
and the booking's own Conflicts panel must never disagree about whether a
booking is contended. Two mechanisms answering one question is this codebase's
most-repeated defect class, and the fix each time has been to collapse them to
one authority.

### 3.1 Step one — a single overlap query

A self-join on `booking`: same `environment_id`, `b1.id < b2.id`, overlapping
windows (`b1.start_date < b2.end_date AND b2.start_date < b1.end_date`), both
live, both in the tenant, at least one side in the requested set.

`b1.id < b2.id` does two jobs: it halves the work, and it yields A4's
**normalised pair** directly, so the escalation lookup keys match without a
second normalisation step.

**ONLY ONE SIDE NEED BE IN THE REQUESTED SET, AND THIS IS LOAD-BEARING.** A
booking shown in September may clash with one running August to October, which
the calendar never renders. Requiring both sides in the range would silently
hide exactly the long-running bookings most likely to collide with something —
and the omission would look identical to an absence of contention.

**THE DATABASE DOES THE PAIRING.** Contention is pairwise, so a Python-side
implementation is O(N²) over a calendar's worth of bookings. Overlaps are sparse
in real estates: the cost of this design scales with the number of actual
clashes, not with how busy the calendar looks.

### 3.2 Step two — batch the escalations

`contention_service.escalations_for_pairs` already exists and already takes
normalised pairs. B6 adds no new query shape here.

### 3.3 Step three — fold each booking's pairs into one state

A booking may be in several contentions. Its rendered state is the **most
actionable** one, precedence **unowned → owned → decided**, because "nobody is
on this" is the state that needs a human. The individual pairs stay visible on
the booking's own page, which remains the authority on who wins and why.

### 3.4 Two traps this must not fall into

- **"Live" means `conflict_service.TERMINAL_STATES`, NOT
  `booking_states.INACTIVE_BOOKING_STATUSES`.** CLAUDE.md records that these
  two sets are deliberately different — the conflict set counts drafts *as*
  conflicts. Use the wrong one and the calendar and the Conflicts panel disagree
  about whether a clash exists at all.
- **THE COUNT IS OF CONTENTIONS, NOT BOOKINGS.** Two bookings clashing is ONE
  contention. Counting marked bookings double-counts every pair and inflates the
  headline number the whole feature exists to make trustworthy.

### 3.5 Once per response, never once per row

A3's rule, recorded after it measured a 50-row page through its per-booking
helper at roughly 150 queries. `contention_states_for_bookings` takes a list of
booking ids and is called once per response. A per-booking convenience wrapper
may exist as a cross-check, and if it does its docstring must say it has no
production caller — the precedent A3 set with `describe_gap`.

## 4. The three states

| State | Meaning | What it asks of a human |
|---|---|---|
| **unowned** | The pair clashes and no escalation exists | Someone should escalate it |
| **owned** | An escalation exists, awaiting a decision | Wait, or chase the named owner |
| **decided** | A decision has been recorded | Somebody must actually move a booking |

An **expired** escalation (A4's third state — the deadline passed unanswered)
renders as **owned**, because it still has a named owner who owes an answer;
the booking's own page says it is overdue. Four visual states on a calendar cell
is decoration rather than information.

**Decided contentions are still shown.** A4 advises and moves nothing, so a
decided contention still has two genuinely overlapping bookings until a human
reschedules one. Hiding them would make the calendar assert a tidiness the
estate does not have — and would hide precisely the cases where a decision was
made and never acted on.

## 5. The three surfaces

### 5.1 Calendar markers

A contended booking is marked in the month view, distinguishing the three
states. **Not by colour alone** — this repo has a completed a11y audit and
colour-only state encoding is exactly what it flags — so colour plus a glyph.
Clicking opens the booking's detail page, unchanged.

The calendar computes contention over the range it already fetches, so this adds
one batch call rather than a new fetch pattern.

### 5.2 The horizon summary

*"N contentions in the next 6 weeks"*, with a control to widen (2 / 6 / 12 / 26
weeks) and the choice held in the URL so a view can be shared.

**A contention falls inside the horizon when its OVERLAP INTERVAL does** — the
intersection of the two bookings, not either booking's own span. A pair that
starts clashing in four months is not a contention in the next six weeks, even
if one of its bookings begins tomorrow. Defining it on either booking's start
would report clashes that cannot happen yet.

**It is independent of the month being viewed.** That independence IS the
leading-indicator claim: a calendar only tells you about the month you navigated
to, so a summary tied to the visible range would answer a question you already
had to ask. It links through to `/contentions`, A4's existing worklist, which
already filters by state — B6 builds no second worklist.

### 5.3 The BookingList column

The same three states as a cell.

- **Permanently unsortable.** It is folded per response after the page is
  fetched, so it joins docs/pagination.md's permanently-unsortable set for the
  same reason `agreement_gap` became its thirteenth member.
- **Not filterable.** `/contentions` is the filtering surface. A filter here
  would require a second definition of the fold, and two definitions of one rule
  is the defect class §3 exists to avoid.
- Its `field` must be collision-safe against tenant custom-field keys.
  `BookingList` was namespaced `cf_<key>` on 2026-08-04 after a colliding key
  caused MUI to emit a visibility change that the page's own `saveColumnModel`
  persisted, silently hiding a real column.

## 6. Testing

- **`tests/test_b6_writes_nothing.py`** — the guard, over a populated estate,
  asserting every row byte-identical after exercising every B6 path.
- **Agreement with `conflict_service`** — the overlap query and the Conflicts
  panel must name the same pairs over one fixture. This gets a test rather than
  a comment precisely because it is two mechanisms answering one question.
- **The fold precedence**, with one booking in three contentions of different
  states, and a test that would fail if the precedence were reversed.
- **The count is pairs, not bookings** — pinned explicitly, with a fixture where
  the two numbers differ.
- **Dual engine.** A self-join with an overlap predicate and date comparisons is
  exactly where SQLite and PostgreSQL diverge.
- **A browser pass.** jsdom cannot reliably render FullCalendar, the same
  limitation that made B5's DataGrid checks load-bearing rather than a
  formality.

## 7. Out of scope

- **Prediction of any kind** — see §2.
- **A second worklist.** `/contentions` exists and filters by state.
- **Marking the releases calendar.** A separate endpoint with its own recently
  fixed date-range history; widening to it doubles the surface for no new
  information.
- **Any change to A4's verdict, escalation model or permissions.** B6 reads them
  and renders them. If B6 finds itself wanting a different verdict, that is a
  finding about A4, not a licence to compute a second opinion.
