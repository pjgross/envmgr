# Phase 7: Multi-Project Coordination

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 4–6 weeks | Starts after Phase 6 completion

---

## Objectives

- Project management (teams, projects, members)
- Usage agreements between projects for shared environments
- Environment groups for coordinated bookings
- Project-aware conflict detection across bookings

---

## Planned Tasks

### Backend

- [ ] `Project` model (name, team, members, owned environments)
- [ ] `UsageAgreement` model (project A can use environment E during window W)
- [ ] `EnvironmentGroup` model (logical grouping of environments)
- [ ] Project-aware `BookingService` — checks agreements before approving
- [ ] Multi-project conflict detection logic
- [ ] API endpoints for projects, agreements, and groups

### Frontend

- [ ] `ProjectList.tsx` and `ProjectDetail.tsx` pages
- [ ] Usage agreement management UI
- [ ] Environment group view
- [ ] Booking conflict visualization across projects
- [ ] Project dashboard (bookings, environments, agreements)

---

## Notes

> Detailed task breakdown to be added when Phase 6 is complete and Phase 7 planning begins.
