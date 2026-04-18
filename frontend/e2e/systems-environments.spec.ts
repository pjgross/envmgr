import { test, expect, type Page } from '@playwright/test';

const TENANT = 'e2e';
const USERNAME = 'e2eadmin';
const PASSWORD = 'e2epassword123';

async function login(page: Page) {
  await page.goto('/login');
  await page.getByLabel('Tenant').fill(TENANT);
  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /login/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Note: seed_e2e.py seeds only a tenant + user (no systems/environments/custom fields).
// Tests below verify DataGrid structure; data-driven tests (row click, custom columns)
// should be added when seed data is extended.

// --- Systems ---

test('Systems page renders the data grid', async ({ page }) => {
  await login(page);
  await page.goto('/systems');
  await expect(page.locator('[role="grid"]')).toBeVisible();
});

test('Systems grid has core column headers', async ({ page }) => {
  await login(page);
  await page.goto('/systems');
  await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Description' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'GitHub' })).toBeVisible();
});

test('Systems page has New System button', async ({ page }) => {
  await login(page);
  await page.goto('/systems');
  await expect(page.getByRole('button', { name: /new system/i })).toBeVisible();
});

test('Systems search field is visible', async ({ page }) => {
  await login(page);
  await page.goto('/systems');
  await expect(page.getByPlaceholder('Search systems\u2026')).toBeVisible();
});

// --- Environments ---

test('Environments page renders the data grid', async ({ page }) => {
  await login(page);
  await page.goto('/environments');
  await expect(page.locator('[role="grid"]')).toBeVisible();
});

test('Environments grid has core column headers', async ({ page }) => {
  await login(page);
  await page.goto('/environments');
  await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
});

test('Environments status filter chips are visible', async ({ page }) => {
  await login(page);
  await page.goto('/environments');
  await expect(page.getByRole('button', { name: 'Active' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Inactive' }).first()).toBeVisible();
});

test('Environments page has New Environment button', async ({ page }) => {
  await login(page);
  await page.goto('/environments');
  await expect(page.getByRole('button', { name: /new environment/i })).toBeVisible();
});

test('Environments search field is visible', async ({ page }) => {
  await login(page);
  await page.goto('/environments');
  await expect(page.getByPlaceholder('Search environments\u2026')).toBeVisible();
});
