# Phase 3 Sub-project 1 — Core Releases Smoke Checklist

> **Purpose**: Human-actionable browser walkthrough for reviewer / QA before merging `feature/phase-3-core-releases`.
> Mirrors the happy-path integration test at `backend/tests/integration/test_release_happy_path.py`.

---

## Prerequisites

- App running locally: `docker-compose up -d` + `uvicorn` + `npm run dev`
- Logged in as `admin` / `admin123` (tenant: `demo`)
- At least one System and one Environment exist (seed or create via Admin pages)

---

## Walkthrough

### 1 — Release Template Library

- Navigate to **Releases → Template Library** (sidebar or `/release-templates`)
- Click **New Template**
- Fill in: name = "Smoke Test Major", type = Major
- Add 2 phases: "SIT" (5 days) and "UAT" (5 days)
- Add 2 gates: "SIT Exit" (linked to SIT), "UAT Exit" (linked to UAT)
- Save — template appears in the list

### 2 — Instantiate a Release

- Click **Instantiate** on the template row (or use the action menu)
- Set release name = "Smoke Release 1", target date = next Friday
- Submit — redirected to the new Release detail page
- Verify status badge shows **Draft**

### 3 — Verify Phases and Gates materialised

- Open the **Phases** tab (or section) on the release detail
- Confirm SIT and UAT phases are listed with computed start/end dates
- Open the **Gates** tab — confirm "SIT Exit" and "UAT Exit" are listed with status Pending

### 4 — Add System Roles

- Open the **Systems** tab
- Click **Add System** — select an existing system, set role = **Changing**
- Add a second system (if available), set role = **Regression**
- Both rows appear in the systems table

### 5 — Book an Environment for SIT

- Open the **Environments** tab on the release
- Click **Add Booking**
- Select the environment, select the SIT phase, set date range within the SIT window
- Save — booking appears in the list
- Confirm the **Context Tag** column shows **deployment** (because the environment's system has role = Changing)

### 6 — Lifecycle: Draft → Submitted

- Return to the **Main** tab
- Click **Submit** (or the transition button for "submitted")
- Status badge updates to **Submitted**

### 7 — Approve and progress through lifecycle

- Click **Approve** → status = **Approved**
- Click **Start** (in_progress) → status = **In Progress**
- Click **Ready for Release** → status = **Ready for Release**
- Click **Complete** → status = **Completed**
- Confirm the **Actual Date** field is now populated

### 8 — Pass Gates

- Open the **Gates** tab (gates can be passed at any point after creation)
- Click **Pass** on "SIT Exit" → status turns green / Passed
- Click **Pass** on "UAT Exit" → same
- Confirm both gates show Passed

### 9 — Final Verification

- Refresh the release detail page
- Status = **Completed**, Actual Date is set
- Gates tab shows all gates Passed
- No error banners or console errors

---

## Done — branch is ready to merge.
