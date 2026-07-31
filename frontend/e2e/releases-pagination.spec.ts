import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Credentials created by seed_e2e.py
const TENANT = 'e2e';
const USERNAME = 'e2eadmin';
const PASSWORD = 'e2epassword123';

// The Playwright `request` fixture talks to the backend directly — unlike the
// browser `page`, it does not go through the Vite dev server's `/api` proxy,
// so it needs the E2E backend's own port (see playwright.config.ts).
const API_BASE = 'http://localhost:8002/api/v1';

const RELEASE_COUNT = 30; // comfortably more than the 25-row default page
// ReleaseCreate has no `status` field — every release below is created in the
// Release model's default "draft" state (see backend/app/db/models/release.py).
// There's no PUT-based way to set status either (ReleaseUpdate omits it too);
// status only moves via POST /releases/{id}/transition, validated against the
// release's lifecycle template. The tenant's default "project" template
// (Major) allows draft -> cancelled with no required_fields and no role
// restriction beyond Admin (which e2eadmin is), so it needs no extra setup
// (unlike e.g. draft -> submitted, which requires target_date to be set).
// Moving a subset to "cancelled" gives a genuine mix of statuses so the
// Status filter assertion narrows a real total instead of leaving it
// unchanged (every release would already be "draft" otherwise).
const CANCELLED_COUNT = 6;
const DRAFT_COUNT = RELEASE_COUNT - CANCELLED_COUNT;

async function login(page: Page) {
  await page.goto('/login');
  await page.getByLabel('Tenant').fill(TENANT);
  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /login/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

async function apiLogin(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API_BASE}/auth/login`, {
    data: { tenant_slug: TENANT, username: USERNAME, password: PASSWORD },
  });
  expect(res.ok(), `login failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  const body = await res.json();
  return body.access_token as string;
}

/** Wait for the grid's first page to actually land, not just the request. */
async function waitForGridLoaded(page: Page) {
  await expect(page.locator('.MuiDataGrid-row').first()).toBeVisible();
}

test.describe('release list server-side pagination', () => {
  test.beforeAll(async ({ request }) => {
    const token = await apiLogin(request);
    const headers = { Authorization: `Bearer ${token}` };

    // seed_e2e.py creates only a tenant + user, so this tenant has no release
    // lifecycle template — POST /releases 422s ("No default release lifecycle
    // template found") without one. Real tenants get one from
    // release_defaults.seed_release_defaults_for_tenant() via
    // tenant_service.create_tenant(), which seed_e2e.py bypasses by
    // constructing the Tenant row directly. Create a minimal one here rather
    // than touching seed_e2e.py (shared state the other specs depend on).
    // `is_default: true` + `applies_to_kind: 'project'` makes it the
    // template new project releases resolve to automatically — no need to
    // pass lifecycle_template_id on every create call below.
    const templateRes = await request.post(`${API_BASE}/tenant/lifecycle-templates`, {
      headers,
      data: {
        name: 'E2E Release Lifecycle',
        is_default: true,
        entity_type: 'release',
        applies_to_kind: 'project',
        definition: {
          states: [
            { key: 'draft', label: 'Draft', is_initial: true, is_terminal: false },
            { key: 'cancelled', label: 'Cancelled', is_initial: false, is_terminal: true },
          ],
          transitions: [
            { from_state: 'draft', to_state: 'cancelled', label: 'Cancel', allowed_roles: ['Admin'] },
          ],
          field_permissions: {},
        },
      },
    });
    expect(
      templateRes.ok(),
      `create lifecycle template failed: ${templateRes.status()} ${await templateRes.text()}`
    ).toBeTruthy();

    // Zero-padded names so lexicographic (server-side) order matches numeric
    // order — the sort assertion checks the actual rendered order, not just
    // that a request went out, so this has to sort predictably.
    const ids: number[] = [];
    for (let i = 1; i <= RELEASE_COUNT; i++) {
      const name = `Release ${String(i).padStart(2, '0')}`;
      const res = await request.post(`${API_BASE}/releases`, {
        headers,
        data: { name, release_type: 'minor' },
      });
      expect(res.ok(), `create release failed: ${res.status()} ${await res.text()}`).toBeTruthy();
      const body = await res.json();
      ids.push(body.id as number);
    }

    for (const id of ids.slice(0, CANCELLED_COUNT)) {
      const res = await request.post(`${API_BASE}/releases/${id}/transition`, {
        headers,
        data: { to_state: 'cancelled' },
      });
      expect(res.ok(), `transition failed: ${res.status()} ${await res.text()}`).toBeTruthy();
    }
  });

  test('page 2 asks the server for the next window', async ({ page }) => {
    await login(page);
    await page.goto('/releases');
    await waitForGridLoaded(page);

    const request = page.waitForRequest(
      (r) => r.url().includes('/api/v1/releases') && r.url().includes('offset=25')
    );
    await page.getByRole('button', { name: /next page/i }).click();
    expect(await request).toBeTruthy();
  });

  test('sorting by name sends both sort parameters, ascending first', async ({ page }) => {
    await login(page);
    await page.goto('/releases');
    await waitForGridLoaded(page);

    const request = page.waitForRequest((r) => r.url().includes('sort_by=name'));
    await page.getByRole('columnheader', { name: 'Name' }).click();
    const url = (await request).url();
    expect(url).toContain('sort_by=name');
    // The endpoint's default_dir is desc; an omitted direction would silently
    // invert a first click.
    expect(url).toContain('sort_dir=asc');

    // The URL alone doesn't prove the rows came back in the right order —
    // assert the actual first rendered row is the alphabetically-first name.
    const firstRow = page.locator('.MuiDataGrid-row').first();
    await expect(firstRow.locator('[data-field="name"]')).toHaveText('Release 01');
  });

  test('a filter narrows the total, not just the visible rows', async ({ page }) => {
    await login(page);
    await page.goto('/releases');
    await waitForGridLoaded(page);

    const displayedRows = page.locator('.MuiTablePagination-displayedRows');
    await expect(displayedRows).toContainText(String(RELEASE_COUNT));
    const before = await displayedRows.innerText();

    // getByLabel('Status') is ambiguous here: the DataGrid's Status *column
    // header* also carries aria-label="Status" alongside the filter combobox.
    // The combobox's accessible name includes its current value ("Status
    // All"), so anchor on that rather than an exact match.
    await page.getByRole('combobox', { name: /^Status/ }).click();
    await page.getByRole('option', { name: 'Draft' }).click();

    await expect(displayedRows).not.toHaveText(before);
    await expect(displayedRows).toContainText(String(DRAFT_COUNT));
  });
});
